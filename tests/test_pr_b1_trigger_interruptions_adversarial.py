from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.calendar.adapter import FakeCalendarAdapter
from app.channel import inbound as inbound_module
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.channel.states import Channel
from app.config.settings import Settings, get_settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.orchestrator import service as orchestrator_module
from app.orchestrator.service import requested_services_summary
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)
from tests.test_slice2b3_wiring_adversarial import (
    ClassifierQueue,
    complete_schedule_until_confirmation,
)
from tests.test_slice2b3_wiring_adversarial import (
    classification as visit_classification,
)
from tests.test_slice2b3_wiring_adversarial import (
    conversation_snapshot as visit_conversation_snapshot,
)
from tests.test_slice2b3_wiring_adversarial import (
    seed_capture as seed_visit_capture,
)
from tests.test_slice2b3_wiring_adversarial import (
    send_turn as send_visit_turn,
)

PHONE = "+573001112233"
SECOND_PHONE = "+573009998877"
NOW = datetime(2026, 8, 24, 9, tzinfo=ZoneInfo("America/Bogota"))
EVENT_TYPE_QUESTION_CODES = frozenset(
    {"RESP-GREETING-001", "RESP-EVENT-DATA-013", "RESP-PRICE-001"}
)
MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260824_0023_pr_b1_capture_context.py"
)


@pytest.fixture
async def sessionmaker_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await configure_test_environment(monkeypatch)
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    yield sessionmaker


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL_INTENT="openai/test-model",
        OPENROUTER_TIMEOUT_SECONDS=0.2,
        OPENROUTER_MAX_RETRIES=0,
        AI_PROMPT_VERSION="intent_v4",
        ENVIRONMENT="testing",
        _env_file=None,
    )


@pytest.fixture
async def visit_wiring_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue]
]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setenv("CALENDAR_ADAPTER", "fake")
    monkeypatch.setenv("GOOGLE_FREEBUSY_CALENDAR_IDS", "visits,business-main")
    get_settings.cache_clear()
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    calendar = FakeCalendarAdapter()
    classifier = ClassifierQueue()

    async def classify_general(
        client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        return await classifier.classify(client, message_text, context, conversation_id)

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(
        orchestrator_module,
        "get_calendar_adapter",
        lambda _settings: calendar,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "current_bogota_datetime",
        lambda: NOW,
        raising=False,
    )
    yield sessionmaker, calendar, classifier
    get_settings.cache_clear()


def classification(
    intent: str,
    *,
    entities: list[ExtractedEntity] | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    reasoning_code: str = "TC_B1_GENERAL",
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category=None,
        entities={},
        extracted_entities=entities or [],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=needs_human,
        handoff_reason=handoff_reason,
        priority="NORMAL",
        context_reference={},
        reasoning_code=reasoning_code,
    )


def event_type_entity(raw_value: str, normalized_value: str) -> ExtractedEntity:
    return ExtractedEntity(
        entity="event_type",
        raw_value=raw_value,
        normalized_value=normalized_value,
        quality_status="PROVIDED",
        confidence=0.95,
        needs_confirmation=False,
        validation_errors=[],
    )


def completion_payload(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-pr-b1-test",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(arguments)}}],
    }


def classification_payload(
    intent: str,
    *,
    entities: list[dict[str, object]] | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
) -> dict[str, object]:
    return {
        "primary_intent": intent,
        "secondary_intents": [],
        "sub_intent": None,
        "confidence": 0.95,
        "information_category": None,
        "entities": {},
        "extracted_entities": entities or [],
        "requested_action": None,
        "missing_fields": [],
        "needs_confirmation": False,
        "needs_human": needs_human,
        "handoff_reason": handoff_reason,
        "priority": "NORMAL",
        "context_reference": {},
        "reasoning_code": "TC_B1_HTTP_GENERAL",
    }


async def seed_post_greeting(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    phone: str = PHONE,
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                last_question_code="RESP-GREETING-001",
            )
            session.add(conversation)
            await session.flush()
            return conversation.id


async def seed_capture(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    phone: str = PHONE,
    failed_understanding_count: int = 0,
    legacy_service: str | None = None,
) -> tuple[int, UUID, UUID]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                lead_status="QUALIFYING",
                budget_data_status="PROVIDED",
            )
            session.add(lead)
            await session.flush()
            event = Event(
                lead_id=lead.lead_id,
                event_type="WEDDING",
                event_date=date(2027, 2, 20),
                event_date_type="EXACT",
                event_date_raw="20 de febrero de 2027",
                guest_count=40,
                guest_count_status="PROVIDED",
            )
            session.add(event)
            await session.flush()
            if legacy_service is not None:
                session.add(
                    EventServiceRequest(
                        event_id=event.event_id,
                        service_name=legacy_service,
                        status="REQUESTED",
                    )
                )
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.COLLECTING_EVENT_DATA,
                active_lead_id=lead.lead_id,
                pending_action="COLLECT_SERVICES",
                pending_fields=["requested_services"],
                last_question_code="RESP-EVENT-DATA-006",
                failed_understanding_count=failed_understanding_count,
            )
            session.add(conversation)
            await session.flush()
            return conversation.id, event.event_id, lead.lead_id


async def seed_formal_event_type_capture(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> UUID:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                lead_status="QUALIFYING",
                budget_data_status="NOT_ASKED",
            )
            session.add(lead)
            await session.flush()
            event = Event(lead_id=lead.lead_id)
            session.add(event)
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.COLLECTING_EVENT_DATA,
                active_lead_id=lead.lead_id,
                pending_action="COLLECT_EVENT_TYPE",
                pending_fields=["event_type"],
                last_question_code="RESP-EVENT-DATA-013",
            )
            session.add(conversation)
            await session.flush()
            return event.event_id


async def send_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    message_id: str,
    text: str,
    phone: str = PHONE,
) -> None:
    payload = json.loads(
        whatsapp_message_payload(
            message_id,
            phone=phone.removeprefix("+"),
            text=text,
        ).decode()
    )
    await process_whatsapp_webhook(payload, sessionmaker, request_id=uuid4())


async def conversation_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
) -> Conversation:
    async with sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    return conversation


async def event_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: UUID,
) -> Event:
    async with sessionmaker() as session:
        event = await session.get(Event, event_id)
    assert event is not None
    return event


async def service_rows(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: UUID,
) -> list[EventServiceRequest]:
    async with sessionmaker() as session:
        return list(
            await session.scalars(
                select(EventServiceRequest)
                .where(EventServiceRequest.event_id == event_id)
                .order_by(EventServiceRequest.created_at, EventServiceRequest.id)
            )
        )


async def outbox_bodies(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
) -> list[str]:
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(
                select(Outbox)
                .where(Outbox.conversation_id == conversation_id)
                .order_by(Outbox.id)
            )
        )
    return [str(row.payload["text"]["body"]) for row in rows]


async def no_llm(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError("A deterministic match must not invoke any LLM task")


@pytest.mark.asyncio
@respx.mock
async def test_tc_b1_001_post_greeting_unknown_uses_extraction_bridge_and_instrumentation(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id = await seed_post_greeting(sessionmaker_fixture)
    responses = [
        httpx.Response(200, json=completion_payload(classification_payload("UNKNOWN"))),
        httpx.Response(200, json=completion_payload({"event_type": "boda"})),
    ]
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=responses
    )

    await send_turn(sessionmaker_fixture, message_id="tc-b1-001", text="La boda")

    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
        executions = list(
            await session.scalars(select(AIExecution).order_by(AIExecution.id))
        )
    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    assert route.call_count == 2
    assert event is not None
    assert event.event_type == "WEDDING"
    assert conversation.last_question_code == "RESP-EVENT-DATA-004"
    assert conversation.last_intent == "EVENT_INFORMATION"
    assert all("RESP-FALLBACK" not in body for body in await outbox_bodies(
        sessionmaker_fixture, conversation_id
    ))
    extraction = next(row for row in executions if row.task == "EVENT_TYPE_EXTRACTION")
    assert extraction.prompt_version == "event_type_extraction_v1"


@pytest.mark.asyncio
async def test_tc_b1_002_valid_general_event_at_greeting_skips_extra_extraction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_post_greeting(sessionmaker_fixture)
    extraction_calls: list[str] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification(
            "EVENT_INFORMATION",
            entities=[event_type_entity("Una boda", "WEDDING")],
        )

    async def extract_event_type(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append(message_text)
        return "WEDDING"

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract_event_type)

    await send_turn(sessionmaker_fixture, message_id="tc-b1-002", text="Una boda")

    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert extraction_calls == []
    assert event is not None and event.event_type == "WEDDING"
    assert getattr(inbound_module, "EVENT_TYPE_QUESTION_CODES", None) == (
        EVENT_TYPE_QUESTION_CODES
    )


@pytest.mark.asyncio
async def test_tc_b1_003_formal_collect_event_type_still_triggers_extraction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id = await seed_formal_event_type_capture(sessionmaker_fixture)
    extraction_calls: list[str] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification("EVENT_INFORMATION")

    async def extract_event_type(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append(message_text)
        return "WEDDING"

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract_event_type)

    await send_turn(sessionmaker_fixture, message_id="tc-b1-003", text="La boda")

    assert extraction_calls == ["La boda"]
    assert (await event_snapshot(sessionmaker_fixture, event_id)).event_type == "WEDDING"
    assert getattr(inbound_module, "EVENT_TYPE_QUESTION_CODES", None) == (
        EVENT_TYPE_QUESTION_CODES
    )


@pytest.mark.asyncio
@respx.mock
async def test_tc_b1_004_payment_interrupts_services_and_preserves_capture_context(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _event_id, lead_id = await seed_capture(sessionmaker_fixture)
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=completion_payload(
                classification_payload(
                    "PAYMENT_MESSAGE",
                    needs_human=True,
                    handoff_reason="PAYMENT_REVIEW",
                )
            ),
        )
    )

    await send_turn(sessionmaker_fixture, message_id="tc-b1-004", text="Ya pagué")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(select(Handoff))
        executions = list(await session.scalars(select(AIExecution)))
    assert route.call_count == 1
    assert [row.task for row in executions] == ["INTENT_CLASSIFICATION"]
    assert handoff is not None and handoff.reason == "PAYMENT_REVIEW"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.active_lead_id == lead_id
    assert "requested_services" in conversation.pending_fields
    assert all("identificar los servicios" not in body.casefold() for body in await outbox_bodies(
        sessionmaker_fixture, conversation_id
    ))


@pytest.mark.asyncio
async def test_tc_b1_005_human_request_interrupts_without_losing_capture_context(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id, _event_id, lead_id = await seed_capture(sessionmaker_fixture)
    general_calls: list[str] = []
    service_calls: list[str] = []

    async def classify_general(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> IntentClassification:
        general_calls.append(message_text)
        return classification(
            "HUMAN_REQUEST",
            needs_human=True,
            handoff_reason="CUSTOMER_REQUEST",
        )

    async def classify_services(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        service_calls.append(message_text)
        return []

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", classify_services)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-005",
        text="quiero hablar con un asesor",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(select(Handoff))
    assert general_calls == ["quiero hablar con un asesor"]
    assert service_calls == []
    assert handoff is not None and handoff.reason == "CUSTOMER_REQUEST"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.active_lead_id == lead_id
    assert conversation.pending_fields == ["requested_services"]


@pytest.mark.asyncio
async def test_tc_b1_006_visit_interrupts_and_resumes_services_end_to_end(
    visit_wiring_context: tuple[
        async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue
    ],
) -> None:
    sessionmaker, _calendar, classifier = visit_wiring_context
    await seed_visit_capture(sessionmaker)
    await complete_schedule_until_confirmation(sessionmaker, classifier, prefix="tc-b1-006")
    await send_visit_turn(
        sessionmaker,
        classifier,
        message_id="tc-b1-006.confirm",
        text="sí",
        result=visit_classification("CONFIRM"),
    )

    conversation = await visit_conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.COLLECTING_EVENT_DATA
    assert conversation.pending_action == "COLLECT_SERVICES"
    assert conversation.last_question_code == "RESP-EVENT-DATA-006"
    assert not hasattr(inbound_module, "is_explicit_visit_request")


@pytest.mark.asyncio
async def test_tc_b1_007_event_cancellation_interrupts_services(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id, _event_id, _lead_id = await seed_capture(sessionmaker_fixture)
    general_calls: list[str] = []

    async def classify_general(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> IntentClassification:
        general_calls.append(message_text)
        return classification(
            "EVENT_CANCELLATION",
            needs_human=True,
            handoff_reason="CANCELLATION",
        )

    async def classify_services(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("Cancellation must not reach SERVICES_CLASSIFICATION")

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", classify_services)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-007",
        text="quiero cancelar el evento",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(select(Handoff))
    assert general_calls == ["quiero cancelar el evento"]
    assert handoff is not None and handoff.reason == "CANCELLATION"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"


@pytest.mark.asyncio
async def test_tc_b1_008_free_service_answer_calls_general_then_services_once(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _conversation_id, event_id, _lead_id = await seed_capture(sessionmaker_fixture)
    general_calls: list[str] = []
    service_calls: list[str] = []

    async def classify_general(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> IntentClassification:
        general_calls.append(message_text)
        return classification("EVENT_INFORMATION")

    async def classify_services(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        service_calls.append(message_text)
        return ["DECORATION"]

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", classify_services)

    text = "quiero que todo se vea inolvidable"
    await send_turn(sessionmaker_fixture, message_id="tc-b1-008", text=text)

    assert general_calls == [text]
    assert service_calls == [text]
    assert [row.service_name for row in await service_rows(
        sessionmaker_fixture, event_id
    )] == ["DECORATION"]


@pytest.mark.asyncio
async def test_tc_b1_009_deterministic_match_keeps_absolute_precedence(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _conversation_id, event_id, _lead_id = await seed_capture(sessionmaker_fixture)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", no_llm)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", no_llm)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-009",
        text="espacio y gastronomía",
    )

    assert {row.service_name for row in await service_rows(
        sessionmaker_fixture, event_id
    )} == {"VENUE", "FOOD"}
    assert not hasattr(inbound_module, "is_explicit_visit_request")


@pytest.mark.asyncio
async def test_tc_b1_010_services_retry_counter_is_isolated_from_general_failures(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id, _event_id, _lead_id = await seed_capture(
        sessionmaker_fixture,
        failed_understanding_count=2,
    )

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification("UNKNOWN")

    async def classify_services(*_args: object, **_kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", classify_services)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-010.first",
        text="no sé cómo explicarlo",
    )
    first = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    first_bodies = await outbox_bodies(sessionmaker_fixture, conversation_id)
    assert first.state == ConversationState.COLLECTING_EVENT_DATA
    assert first.pending_action == "COLLECT_SERVICES"
    assert first.failed_understanding_count == 2
    assert getattr(first, "services_failed_understanding_count", None) == 1
    assert sum("identificar los servicios" in body.casefold() for body in first_bodies) == 1

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-010.second",
        text="sigo sin saber cómo decirlo",
    )
    second = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    assert second.state == ConversationState.WAITING_FOR_HUMAN
    assert second.pending_action == "WAIT_FOR_HUMAN"


@pytest.mark.asyncio
async def test_tc_b1_011_summary_and_positions_preserve_two_and_three_mentions(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_conversation_id, first_event_id, _lead_id = await seed_capture(
        sessionmaker_fixture,
        phone=PHONE,
    )
    second_conversation_id, second_event_id, _second_lead_id = await seed_capture(
        sessionmaker_fixture,
        phone=SECOND_PHONE,
    )
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", no_llm)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", no_llm)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-011.two",
        text="Espacio y gastronomía",
        phone=PHONE,
    )
    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-011.three",
        text="DJ, gastronomía y espacio",
        phone=SECOND_PHONE,
    )

    first_rows = await service_rows(sessionmaker_fixture, first_event_id)
    second_rows = await service_rows(sessionmaker_fixture, second_event_id)
    assert [row.service_name for row in first_rows] == ["VENUE", "FOOD"]
    assert [getattr(row, "position", None) for row in first_rows] == [0, 1]
    assert [row.service_name for row in second_rows] == ["DJ", "FOOD", "VENUE"]
    assert [getattr(row, "position", None) for row in second_rows] == [0, 1, 2]
    assert any(
        "el espacio y la gastronomía" in body
        for body in await outbox_bodies(sessionmaker_fixture, first_conversation_id)
    )
    assert any(
        "el DJ, la gastronomía y el espacio" in body
        for body in await outbox_bodies(sessionmaker_fixture, second_conversation_id)
    )


@pytest.mark.asyncio
async def test_tc_b1_012_unknown_without_directed_value_uses_normal_unknown_flow(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_post_greeting(sessionmaker_fixture)
    extraction_calls: list[str] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification("UNKNOWN")

    async def extract_event_type(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append(message_text)
        return None

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract_event_type)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-012",
        text="algo muy especial",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert extraction_calls == ["algo muy especial"]
    assert event is None
    assert conversation.last_intent == "UNKNOWN"
    assert conversation.last_question_code == "RESP-FALLBACK-001"
    assert conversation.failed_understanding_count == 1


@pytest.mark.asyncio
async def test_tc_b1_013_sensitive_intent_at_event_question_is_never_bridged(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_post_greeting(sessionmaker_fixture)
    extraction_calls: list[str] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification(
            "PAYMENT_MESSAGE",
            needs_human=True,
            handoff_reason="PAYMENT_REVIEW",
        )

    async def extract_event_type(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append(message_text)
        return "WEDDING"

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract_event_type)

    await send_turn(sessionmaker_fixture, message_id="tc-b1-013", text="Ya pagué")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
        handoff = await session.scalar(select(Handoff))
    assert extraction_calls == ["Ya pagué"]
    assert event is None
    assert handoff is not None and handoff.reason == "PAYMENT_REVIEW"
    assert conversation.last_intent == "PAYMENT_MESSAGE"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"


def test_tc_b1_014_migration_0023_and_metadata_have_exact_two_column_parity() -> None:
    assert MIGRATION_PATH.exists(), "La migración aditiva 0023 es un entregable de G3"
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "20260824_0023"' in migration
    assert 'down_revision: str | None = "20260821_0022"' in migration
    assert migration.count("op.add_column(") == 2
    assert migration.count("op.drop_column(") == 2
    assert '"conversation"' in migration
    assert '"services_failed_understanding_count"' in migration
    assert '"event_service_request"' in migration
    assert '"position"' in migration

    conversation_columns = Conversation.__table__.columns
    service_columns = EventServiceRequest.__table__.columns
    assert "services_failed_understanding_count" in conversation_columns
    assert conversation_columns["services_failed_understanding_count"].nullable is True
    assert "position" in service_columns
    assert service_columns["position"].nullable is True


@pytest.mark.asyncio
async def test_tc_b1_015_new_positions_sort_before_legacy_null_rows(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _conversation_id, event_id, _lead_id = await seed_capture(
        sessionmaker_fixture,
        legacy_service="Solo Fotomatón Especial",
    )
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", no_llm)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", no_llm)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b1-015",
        text="espacio y gastronomía",
    )

    assert "position" in EventServiceRequest.__table__.columns
    async with sessionmaker_fixture() as session:
        event = await session.get(Event, event_id)
        assert event is not None
        values = await requested_services_summary(session, event)
    assert values == ["VENUE", "FOOD", "Solo Fotomatón Especial"]
