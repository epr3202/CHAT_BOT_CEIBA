from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select

from app.ai.client import OpenRouterIntentClient
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.main import app
from tests.integration.helpers import (
    app_client,
    cleanup_test_environment,
    configure_test_environment,
    signature,
    whatsapp_message_payload,
)

ORIGINAL_CLASSIFY_INTENT = OpenRouterIntentClient.classify_intent
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", ORIGINAL_CLASSIFY_INTENT)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


def classification_payload(
    intent: str,
    *,
    confidence: float = 0.91,
    entities: dict[str, object] | None = None,
    information_category: str | None = None,
    requested_action: str | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    priority: str = "NORMAL",
) -> dict[str, object]:
    return {
        "primary_intent": intent,
        "secondary_intents": [],
        "sub_intent": None,
        "confidence": confidence,
        "information_category": information_category,
        "entities": entities or {},
        "requested_action": requested_action,
        "missing_fields": [],
        "needs_confirmation": False,
        "needs_human": needs_human,
        "handoff_reason": handoff_reason,
        "priority": priority,
        "context_reference": {},
        "reasoning_code": f"TEST_{intent}",
    }


def openrouter_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload),
                    }
                }
            ]
        },
    )


def mock_openrouter(
    respx_mock: respx.MockRouter,
    payloads: Sequence[dict[str, object] | Exception],
) -> None:
    side_effect: list[httpx.Response | Exception] = []
    for payload in payloads:
        if isinstance(payload, Exception):
            side_effect.append(payload)
            side_effect.append(payload)
        else:
            side_effect.append(openrouter_response(payload))
    respx_mock.post(OPENROUTER_CHAT_URL).mock(side_effect=side_effect)


async def post_whatsapp(
    client: AsyncClient,
    message_id: str,
    text: str,
    *,
    phone: str,
) -> None:
    body = whatsapp_message_payload(message_id, phone=phone, text=text)
    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )
    assert response.status_code == 200


async def latest_conversation(phone: str) -> Conversation:
    async with app.state.db_sessionmaker() as session:
        customer = await session.scalar(
            select(Customer).where(Customer.phone_number == f"+{phone}")
        )
        assert customer is not None
        conversation = await session.scalar(
            select(Conversation)
            .where(Conversation.customer_id == customer.id)
            .order_by(Conversation.id.desc())
            .limit(1)
        )
        assert conversation is not None
        return conversation


async def latest_outbox(phone: str) -> Outbox | None:
    async with app.state.db_sessionmaker() as session:
        return await session.scalar(
            select(Outbox)
            .where(Outbox.recipient_phone_number == f"+{phone}")
            .order_by(Outbox.id.desc())
            .limit(1)
        )


async def count_outbox(phone: str) -> int:
    async with app.state.db_sessionmaker() as session:
        return (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.recipient_phone_number == f"+{phone}")
            )
            or 0
        )


async def handoffs_for_conversation(conversation_id: int) -> list[Handoff]:
    async with app.state.db_sessionmaker() as session:
        result = await session.scalars(
            select(Handoff)
            .where(Handoff.conversation_id == conversation_id)
            .order_by(Handoff.id.asc())
        )
        return list(result.all())


async def audit_actions(conversation_id: int) -> list[str]:
    async with app.state.db_sessionmaker() as session:
        result = await session.scalars(
            select(AuditEvent.action)
            .where(
                AuditEvent.entity.in_(["conversation", "handoff"]),
                AuditEvent.new_value["conversation_id"].as_integer() == conversation_id,
            )
            .order_by(AuditEvent.id.asc())
        )
        return list(result.all())


async def create_conversation_precondition(
    *,
    phone: str,
    state: ConversationState,
    pending_action: str | None = None,
    bot_enabled: bool = True,
) -> int:
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=f"+{phone}")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=state,
                pending_action=pending_action,
                bot_enabled=bot_enabled,
            )
            session.add(conversation)
            await session.flush()
            message = Message(
                external_message_id=f"wamid.precondition.{phone}",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": "precondicion"}},
                provider_timestamp=None,
            )
            session.add(message)
            await session.flush()
            return conversation.id


@pytest.mark.asyncio
async def test_slice1_greeting_faq_and_farewell_follow_documented_templates(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload("GREETING", requested_action="ANSWER_GREETING"),
            classification_payload(
                "GENERAL_INFORMATION",
                information_category="ubicación",
                requested_action="START_INFORMATION_FLOW",
            ),
            classification_payload(
                "GENERAL_INFORMATION",
                information_category="ubicacion",
                requested_action="START_INFORMATION_FLOW",
            ),
            classification_payload("FAREWELL", requested_action="MARK_RESOLVED"),
        ],
    )

    phone_greeting = "573101001001"
    await post_whatsapp(client, "wamid.s1.greeting", "Hola.", phone=phone_greeting)
    greeting_conversation = await latest_conversation(phone_greeting)
    greeting_outbox = await latest_outbox(phone_greeting)
    assert greeting_conversation.last_question_code == "RESP-GREETING-001"
    assert greeting_conversation.state == "BOT_ACTIVE"
    assert greeting_outbox is not None

    phone_faq = "573101001002"
    await post_whatsapp(client, "wamid.s1.faq.maps", "Pásame la ubicación.", phone=phone_faq)
    faq_conversation = await latest_conversation(phone_faq)
    faq_outbox = await latest_outbox(phone_faq)
    assert faq_conversation.last_question_code == "RESP-LOCATION-002"
    assert faq_conversation.state == "BOT_ACTIVE"
    assert faq_outbox is not None
    assert "https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw" in faq_outbox.payload["text"][
        "body"
    ]
    assert await handoffs_for_conversation(faq_conversation.id) == []

    phone_location = "573101001012"
    await post_whatsapp(
        client,
        "wamid.s1.faq.location",
        "¿Dónde quedan ubicados?",
        phone=phone_location,
    )
    location_conversation = await latest_conversation(phone_location)
    location_outbox = await latest_outbox(phone_location)
    assert location_conversation.last_question_code == "RESP-LOCATION-001"
    assert location_conversation.state == "BOT_ACTIVE"
    assert location_outbox is not None
    assert await handoffs_for_conversation(location_conversation.id) == []

    phone_farewell = "573101001003"
    await post_whatsapp(
        client,
        "wamid.s1.farewell",
        "Gracias, era solo eso.",
        phone=phone_farewell,
    )
    farewell_conversation = await latest_conversation(phone_farewell)
    assert farewell_conversation.last_question_code == "RESP-FAREWELL-001"
    assert farewell_conversation.state == "RESOLVED"


@pytest.mark.asyncio
async def test_slice1_unknown_ladder_uses_three_documented_steps(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload("UNKNOWN", confidence=0.49),
            classification_payload("UNKNOWN", confidence=0.49),
            classification_payload("UNKNOWN", confidence=0.49),
        ],
    )
    phone = "573101001004"

    await post_whatsapp(client, "wamid.s1.unknown.1", "???", phone=phone)
    conversation = await latest_conversation(phone)
    assert conversation.last_question_code == "RESP-FALLBACK-001"
    assert conversation.failed_understanding_count == 1
    assert conversation.state == "BOT_ACTIVE"

    await post_whatsapp(client, "wamid.s1.unknown.2", "no sé", phone=phone)
    conversation = await latest_conversation(phone)
    assert conversation.last_question_code == "RESP-FALLBACK-002"
    assert conversation.failed_understanding_count == 2
    assert conversation.state == "BOT_ACTIVE"

    await post_whatsapp(client, "wamid.s1.unknown.3", "asdf", phone=phone)
    conversation = await latest_conversation(phone)
    handoffs = await handoffs_for_conversation(conversation.id)
    assert conversation.last_question_code == "RESP-FALLBACK-003"
    assert conversation.failed_understanding_count == 3
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert len(handoffs) == 1
    assert handoffs[0].reason == "LOW_CONFIDENCE"
    assert "HANDOFF_CREATED" in await audit_actions(conversation.id)


@pytest.mark.asyncio
async def test_slice1_direct_and_critical_handoffs_create_summary_audit_and_state(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload(
                "HUMAN_REQUEST",
                needs_human=True,
                handoff_reason="CUSTOMER_REQUEST",
                requested_action="CREATE_HANDOFF",
            ),
            classification_payload(
                "EMERGENCY",
                needs_human=True,
                handoff_reason="URGENT_EVENT",
                priority="CRITICAL",
                requested_action="CREATE_HANDOFF",
            ),
        ],
    )

    phone_human = "573101001005"
    await post_whatsapp(
        client,
        "wamid.s1.handoff.direct",
        "Quiero hablar con una persona.",
        phone=phone_human,
    )
    human_conversation = await latest_conversation(phone_human)
    human_handoffs = await handoffs_for_conversation(human_conversation.id)
    assert human_conversation.state == "WAITING_FOR_HUMAN"
    assert human_conversation.last_question_code == "RESP-HANDOFF-001"
    assert len(human_handoffs) == 1
    assert human_handoffs[0].reason == "CUSTOMER_REQUEST"
    assert human_handoffs[0].summary
    assert "HANDOFF_CREATED" in await audit_actions(human_conversation.id)

    phone_emergency = "573101001006"
    await post_whatsapp(
        client,
        "wamid.s1.handoff.critical",
        "Hay una emergencia en el evento.",
        phone=phone_emergency,
    )
    emergency_conversation = await latest_conversation(phone_emergency)
    emergency_handoffs = await handoffs_for_conversation(emergency_conversation.id)
    assert emergency_conversation.state == "WAITING_FOR_HUMAN"
    assert len(emergency_handoffs) == 1
    assert emergency_handoffs[0].reason == "URGENT_EVENT"
    assert emergency_handoffs[0].priority == "CRITICAL"


@pytest.mark.asyncio
async def test_slice1_off_hours_handoff_uses_off_hours_template(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.handoff.service.is_human_business_hours",
        lambda *_args, **_kwargs: False,
    )
    mock_openrouter(
        respx_mock,
        [
            classification_payload(
                "HUMAN_REQUEST",
                needs_human=True,
                handoff_reason="CUSTOMER_REQUEST",
                requested_action="CREATE_HANDOFF",
            )
        ],
    )

    phone = "573101001007"
    await post_whatsapp(client, "wamid.s1.handoff.offhours", "Asesor.", phone=phone)
    conversation = await latest_conversation(phone)
    outbox = await latest_outbox(phone)
    assert conversation.last_question_code == "RESP-HANDOFF-002"
    assert outbox is not None
    assert "martes a sábado" in outbox.payload["text"]["body"]
    assert "8:00 a. m." in outbox.payload["text"]["body"]
    assert "4:00 p. m." in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_slice1_pending_action_survives_general_information_interruption(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload(
                "GENERAL_INFORMATION",
                information_category="parqueadero",
                requested_action="START_INFORMATION_FLOW",
            )
        ],
    )
    phone = "573101001008"
    await create_conversation_precondition(
        phone=phone,
        state=ConversationState.COLLECTING_EVENT_DATA,
        pending_action="COLLECT_EVENT_TYPE",
    )

    await post_whatsapp(client, "wamid.s1.pending.parking", "¿Tienen parqueadero?", phone=phone)

    conversation = await latest_conversation(phone)
    assert conversation.last_question_code == "RESP-PARKING-001"
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "COLLECT_EVENT_TYPE"
    assert await handoffs_for_conversation(conversation.id) == []


@pytest.mark.asyncio
async def test_slice1_general_information_without_category_asks_clarification(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload(
                "GENERAL_INFORMATION",
                information_category=None,
                requested_action="START_INFORMATION_FLOW",
            )
        ],
    )
    phone = "573101001013"

    await post_whatsapp(client, "wamid.s1.faq.no.category", "Cuéntame más.", phone=phone)

    conversation = await latest_conversation(phone)
    outbox = await latest_outbox(phone)
    assert conversation.last_question_code == "RESP-FALLBACK-001"
    assert conversation.failed_understanding_count == 1
    assert conversation.state == "BOT_ACTIVE"
    assert outbox is not None
    assert "¿Buscas información" in outbox.payload["text"]["body"]
    assert await handoffs_for_conversation(conversation.id) == []


@pytest.mark.asyncio
async def test_slice1_ai_unavailable_during_faq_uses_deterministic_knowledge(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(respx_mock, [httpx.TimeoutException("openrouter timeout")])
    phone = "573101001009"

    await post_whatsapp(client, "wamid.s1.ai.down.faq", "¿Dónde quedan?", phone=phone)

    conversation = await latest_conversation(phone)
    outbox = await latest_outbox(phone)
    assert conversation.last_question_code in {"RESP-LOCATION-001", "RESP-LOCATION-002"}
    assert outbox is not None
    assert "Calle 71 #52-34" in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_slice1_bot_is_silent_in_waiting_for_human_and_human_active(
    client: AsyncClient,
    respx_mock: respx.MockRouter,
) -> None:
    mock_openrouter(
        respx_mock,
        [
            classification_payload("GREETING"),
            classification_payload("GREETING"),
        ],
    )

    waiting_phone = "573101001010"
    await create_conversation_precondition(
        phone=waiting_phone,
        state=ConversationState.WAITING_FOR_HUMAN,
    )
    await post_whatsapp(client, "wamid.s1.waiting.silent", "¿Ya me atienden?", phone=waiting_phone)
    assert await count_outbox(waiting_phone) == 0

    human_phone = "573101001011"
    await create_conversation_precondition(
        phone=human_phone,
        state=ConversationState.HUMAN_ACTIVE,
        bot_enabled=False,
    )
    await post_whatsapp(client, "wamid.s1.human.silent", "Hola bot", phone=human_phone)
    assert await count_outbox(human_phone) == 0
