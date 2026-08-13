from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.lead.models import Lead
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message
from app.quote.models import QuoteRequest
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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
        ENVIRONMENT="testing",
        _env_file=None,
    )


def classification(
    intent: str = "QUOTE_REQUEST",
    entities: list[ExtractedEntity] | None = None,
    information_category: str | None = None,
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.91,
        information_category=information_category,
        entities={},
        extracted_entities=entities or [],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TEST",
    )


def entity(
    name: str,
    raw_value: str,
    normalized_value: Any,
    quality_status: str = "PROVIDED",
    needs_confirmation: bool = False,
) -> ExtractedEntity:
    return ExtractedEntity(
        entity=name,
        raw_value=raw_value,
        normalized_value=normalized_value,
        quality_status=quality_status,
        confidence=0.93,
        needs_confirmation=needs_confirmation,
        validation_errors=[],
    )


def date_entity(
    raw_value: str,
    event_date: str | None,
    event_month: str | None,
    event_date_type: str,
    quality_status: str = "PROVIDED",
) -> ExtractedEntity:
    return entity(
        "event_date",
        raw_value,
        {
            "event_date": event_date,
            "event_month": event_month,
            "event_date_type": event_date_type,
            "event_date_raw": raw_value,
        },
        quality_status=quality_status,
    )


async def seed_conversation(
    session: AsyncSession,
    state: ConversationState = ConversationState.BOT_ACTIVE,
) -> tuple[Customer, Conversation]:
    customer = Customer(phone_number="+573001112233")
    session.add(customer)
    await session.flush()
    conversation = Conversation(customer_id=customer.id, channel=Channel.WHATSAPP, state=state)
    session.add(conversation)
    await session.flush()
    return customer, conversation


async def run_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    conversation_id: int,
    customer_id: int,
    text: str,
    result: IntentClassification,
    external_message_id: str,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id, with_for_update=True)
            customer = await session.get(Customer, customer_id)
            assert conversation is not None
            assert customer is not None
            message = Message(
                external_message_id=external_message_id,
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": text}},
                provider_timestamp=None,
            )
            session.add(message)
            await session.flush()
            await orchestrate_inbound_message(
                session,
                settings,
                sessionmaker,
                OrchestrationInput(conversation, customer, message, text, external_message_id),
                classification=result,
            )


async def latest_outbox_body(sessionmaker: async_sessionmaker[AsyncSession]) -> str:
    async with sessionmaker() as session:
        outbox = await session.scalar(select(Outbox).order_by(Outbox.id.desc()).limit(1))
    assert outbox is not None
    return outbox.payload["text"]["body"]


async def capture_models(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[Customer, Conversation, Lead, Event]:
    async with sessionmaker() as session:
        customer = await session.scalar(select(Customer))
        conversation = await session.scalar(select(Conversation))
        lead = await session.scalar(select(Lead))
        event = await session.scalar(select(Event))
    assert customer is not None
    assert conversation is not None
    assert lead is not None
    assert event is not None
    return customer, conversation, lead, event


async def seed_quote_ready(
    session: AsyncSession,
    *,
    last_question_code: str = "RESP-QUOTE-002",
) -> tuple[Customer, Conversation]:
    customer = Customer(phone_number="+573001112233", full_name="Natalia")
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
        event_date=date(2026, 9, 13),
        event_date_type="EXACT",
        event_date_raw="13 de septiembre",
        guest_count=45,
        guest_count_status="PROVIDED",
    )
    session.add(event)
    await session.flush()
    session.add(
        EventServiceRequest(
            event_id=event.event_id,
            service_name="espacio",
            status="REQUESTED",
        )
    )
    quote_request = QuoteRequest(
        lead_id=lead.lead_id,
        event_id=event.event_id,
        request_status="DRAFT",
        minimum_data_complete=True,
        missing_fields=[],
        date_pending=False,
        summary_snapshot={"event_date_raw": "13 de septiembre"},
    )
    session.add(quote_request)
    conversation = Conversation(
        customer_id=customer.id,
        channel=Channel.WHATSAPP,
        state=ConversationState.QUOTE_REQUEST_READY,
        pending_action="CONFIRM_QUOTE_REQUEST",
        last_question_code=last_question_code,
        active_lead_id=lead.lead_id,
    )
    session.add(conversation)
    await session.flush()
    return customer, conversation


def complete_entities(date_value: str = "2026-12-12") -> list[ExtractedEntity]:
    return [
        entity("full_name", "Soy Natalia", "Natalia"),
        entity("event_type", "boda", "WEDDING"),
        entity("guest_count", "45 personas", 45),
        date_entity("12 de diciembre", date_value, None, "EXACT"),
        entity("estimated_budget", "10 millones", 10000000),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("message_text", ["Si", "Correcto", "Dale", "sí.", "SI", "👍"])
async def test_p0a_confirm_quote_request_resolves_deterministically_without_repeating_summary(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
    message_text: str,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_quote_ready(session)

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        message_text,
        classification("MODIFY_EVENT_DATA", []),
        f"wamid.p0a.confirm.{message_text}",
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation.id)
        quote_request = await session.scalar(select(QuoteRequest))
        bodies = [
            row.payload["text"]["body"] for row in (await session.scalars(select(Outbox))).all()
        ]
    assert conversation is not None
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert quote_request is not None
    assert quote_request.request_status == "READY"
    assert not any("Para confirmar:" in body for body in bodies)


@pytest.mark.asyncio
async def test_p0a_plain_no_returns_to_capture_without_repeating_summary(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_quote_ready(session)

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "No",
        classification("QUOTE_REQUEST", []),
        "wamid.p0a.deny",
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation.id)
        quote_request = await session.scalar(select(QuoteRequest))
        bodies = [
            row.payload["text"]["body"] for row in (await session.scalars(select(Outbox))).all()
        ]
    assert conversation is not None
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action != "CONFIRM_QUOTE_REQUEST"
    assert quote_request is not None
    assert quote_request.request_status == "DRAFT"
    assert not any("Para confirmar:" in body for body in bodies)


@pytest.mark.asyncio
async def test_p0a_denial_with_content_goes_to_classifier_and_applies_correction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_quote_ready(session)

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "no, son 40 personas",
        classification("MODIFY_EVENT_DATA", [entity("guest_count", "40 personas", 40)]),
        "wamid.p0a.deny.content",
    )

    _customer, conversation, _lead, event = await capture_models(sessionmaker_fixture)
    assert event.guest_count == 40
    assert conversation.state == "QUOTE_REQUEST_READY"


@pytest.mark.asyncio
async def test_p0a_confirmation_template_cannot_be_emitted_twice_in_a_row(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_quote_ready(session)
            previous_message = Message(
                external_message_id="wamid.p0a.previous",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": "setup"}},
                provider_timestamp=None,
            )
            session.add(previous_message)
            await session.flush()
            session.add(
                Outbox(
                    conversation_id=conversation.id,
                    message_id=previous_message.id,
                    channel=Channel.WHATSAPP,
                    recipient_phone_number=customer.phone_number,
                    payload={
                        "type": "text",
                        "text": {"body": "Para confirmar: resumen previo. ¿Está correcto?"},
                    },
                )
            )

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Correcto",
        classification("MODIFY_EVENT_DATA", []),
        "wamid.p0a.antiloop",
    )
    async with sessionmaker_fixture() as session:
        bodies = [
            row.payload["text"]["body"]
            for row in (await session.scalars(select(Outbox).order_by(Outbox.id))).all()
        ]
    assert len([body for body in bodies if body.startswith("Para confirmar:")]) == 1


@pytest.mark.asyncio
async def test_p0a_confirm_pending_action_is_resolved_before_llm(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            await seed_quote_ready(session)

    async def fail_if_called(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        raise AssertionError("LLM classifier must not run for deterministic CONFIRM")

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", fail_if_called)
    payload = json.loads(
        whatsapp_message_payload("wamid.p0a.before-llm", text="Si").decode()
    )

    await process_whatsapp_webhook(payload, sessionmaker_fixture, "req-p0a-before-llm")

    async with sessionmaker_fixture() as session:
        conversation = await session.scalar(select(Conversation))
        quote_request = await session.scalar(select(QuoteRequest))
    assert conversation is not None
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert quote_request is not None
    assert quote_request.request_status == "READY"


@pytest.mark.asyncio
async def test_tc_collect_001_multiple_fields_persist_in_one_turn(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Soy Natalia, boda para 45 personas el 12 de diciembre, tengo 10 millones.",
        classification(entities=complete_entities()),
        "wamid.tc.collect.001",
    )
    customer, conversation, lead, event = await capture_models(sessionmaker_fixture)

    assert customer.full_name == "Natalia"
    assert event.event_type == "WEDDING"
    assert event.guest_count == 45
    assert event.event_date == date(2026, 12, 12)
    assert str(lead.estimated_budget.quantize(0)) == "10000000"
    assert conversation.pending_action == "COLLECT_SERVICES"
    assert conversation.pending_fields == ["requested_services"]
    assert "servicios" in await latest_outbox_body(sessionmaker_fixture)


@pytest.mark.asyncio
async def test_tc_collect_002_approximate_date_triplet(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(
                session, ConversationState.COLLECTING_EVENT_DATA
            )

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "En diciembre.",
        classification(
            "EVENT_INFORMATION", [date_entity("en diciembre", None, "2026-12", "APPROXIMATE")]
        ),
        "wamid.tc.collect.002",
    )
    _customer, _conversation, _lead, event = await capture_models(sessionmaker_fixture)

    assert event.event_month == "2026-12"
    assert event.event_date is None
    assert event.event_date_type == "APPROXIMATE"
    assert event.event_date_raw == "en diciembre"


@pytest.mark.asyncio
async def test_tc_collect_003_flexible_date_triplet_with_month(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(
                session, ConversationState.COLLECTING_EVENT_DATA
            )

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Cualquier sábado de febrero.",
        classification(
            "EVENT_INFORMATION",
            [date_entity("Cualquier sábado de febrero", None, "2027-02", "FLEXIBLE")],
        ),
        "wamid.tc.collect.003",
    )
    _customer, _conversation, _lead, event = await capture_models(sessionmaker_fixture)

    assert event.event_month == "2027-02"
    assert event.event_date_type == "FLEXIBLE"
    assert event.event_date is None


@pytest.mark.asyncio
async def test_tc_collect_004_unknown_declared_enables_ready(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)

    entities = [
        entity("full_name", "Soy Natalia", "Natalia"),
        entity("event_type", "boda", "WEDDING"),
        entity("guest_count", "45 personas", 45),
        date_entity("Todavía no sé la fecha", None, None, "UNKNOWN"),
        entity("estimated_budget", "10 millones", 10000000),
        entity("requested_services", "gastronomía", ["gastronomía"]),
    ]
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Todavía no sé la fecha.",
        classification(entities=entities),
        "wamid.tc.collect.004",
    )
    _customer, conversation, _lead, event = await capture_models(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        quote_request = await session.scalar(select(QuoteRequest))

    assert event.event_date_type == "UNKNOWN"
    assert event.event_date is None
    assert event.event_month is None
    assert event.event_date_raw == "Todavía no sé la fecha"
    assert conversation.pending_fields == []
    assert conversation.state == "QUOTE_REQUEST_READY"
    assert quote_request is not None
    assert quote_request.date_pending is True


@pytest.mark.asyncio
async def test_tc_collect_005_date_correction_is_atomic_and_audited(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Soy Natalia, boda para 45 personas el 12 de diciembre, tengo 10 millones.",
        classification(entities=complete_entities()),
        "wamid.tc.collect.005a",
    )
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Mejor déjalo para enero.",
        classification(
            "MODIFY_EVENT_DATA",
            [date_entity("Mejor déjalo para enero", None, "2027-01", "APPROXIMATE", "CORRECTED")],
        ),
        "wamid.tc.collect.005b",
    )
    _customer, conversation, _lead, event = await capture_models(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "EVENT_DATE_CORRECTED")
        )

    assert event.event_date is None
    assert event.event_month == "2027-01"
    assert event.event_date_type == "APPROXIMATE"
    assert event.event_date_raw == "Mejor déjalo para enero"
    assert audit is not None
    assert audit.old_value["event_date"] == "2026-12-12"
    assert conversation.pending_action != "COLLECT_EVENT_DATE"


@pytest.mark.asyncio
async def test_tc_collect_006_third_party_name_does_not_fill_customer_name(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(
                session, ConversationState.COLLECTING_EVENT_DATA
            )

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "La novia se llama Natalia.",
        classification("EVENT_INFORMATION", []),
        "wamid.tc.collect.006",
    )
    customer, conversation, _lead, _event = await capture_models(sessionmaker_fixture)

    assert customer.full_name is None
    assert "full_name" in conversation.pending_fields


@pytest.mark.asyncio
async def test_tc_collect_007_inferred_name_requires_confirmation(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)

    entities = complete_entities() + [entity("requested_services", "gastronomía", ["gastronomía"])]
    entities[0] = entity("full_name", "Natalia", "Natalia", "PENDING_CONFIRMATION", True)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Natalia, boda para 45 personas.",
        classification(entities=entities),
        "wamid.tc.collect.007a",
    )
    customer, conversation, _lead, _event = await capture_models(sessionmaker_fixture)
    assert customer.full_name is None
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "COLLECT_CUSTOMER_NAME"

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Sí",
        classification("EVENT_INFORMATION", []),
        "wamid.tc.collect.007b",
    )
    customer, conversation, _lead, _event = await capture_models(sessionmaker_fixture)
    assert customer.full_name == "Natalia"
    assert conversation.state == "QUOTE_REQUEST_READY"


@pytest.mark.asyncio
async def test_tc_collect_008_budget_declined_once_is_not_reasked(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)

    setup_entities = [
        entity("full_name", "Soy Natalia", "Natalia"),
        entity("event_type", "boda", "WEDDING"),
        entity("guest_count", "45 personas", 45),
        date_entity("12 de diciembre", "2026-12-12", None, "EXACT"),
    ]
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "setup",
        classification(entities=setup_entities),
        "wamid.tc.collect.008a",
    )
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Prefiero no decirlo.",
        classification(
            "EVENT_INFORMATION", [entity("budget_declined", "Prefiero no decirlo", True)]
        ),
        "wamid.tc.collect.008b",
    )
    _customer, conversation, lead, _event = await capture_models(sessionmaker_fixture)

    assert lead.budget_data_status == "DECLINED"
    assert "estimated_budget" not in conversation.pending_fields
    assert conversation.pending_action == "COLLECT_SERVICES"
    assert "presupuesto" not in (await latest_outbox_body(sessionmaker_fixture)).casefold()


@pytest.mark.asyncio
async def test_tc_collect_009_spontaneous_budget_after_decline_is_provided(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "setup",
        classification(entities=[entity("budget_declined", "no", True)]),
        "wamid.tc.collect.009a",
    )
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Bueno, tengo unos 6 millones.",
        classification("EVENT_INFORMATION", [entity("estimated_budget", "6 millones", 6000000)]),
        "wamid.tc.collect.009b",
    )
    _customer, _conversation, lead, _event = await capture_models(sessionmaker_fixture)
    assert lead.budget_data_status == "PROVIDED"
    assert str(lead.estimated_budget.quantize(0)) == "6000000"


@pytest.mark.asyncio
async def test_tc_collect_010_below_reference_is_invisible(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Tengo dos millones y medio.",
        classification(
            "EVENT_INFORMATION", [entity("estimated_budget", "dos millones y medio", 2500000)]
        ),
        "wamid.tc.collect.010",
    )
    _customer, _conversation, lead, _event = await capture_models(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        bodies = [
            row.payload["text"]["body"] for row in (await session.scalars(select(Outbox))).all()
        ]
    assert lead.budget_range == "BELOW_REFERENCE"
    assert all("BELOW_REFERENCE" not in body for body in bodies)


@pytest.mark.asyncio
async def test_tc_collect_019_budget_evasion_is_declined_deterministically(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)

    setup_entities = [
        entity("full_name", "Soy Natalia", "Natalia"),
        entity("event_type", "boda", "WEDDING"),
        entity("guest_count", "45 personas", 45),
        date_entity("12 de diciembre", "2026-12-12", None, "EXACT"),
    ]
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "setup",
        classification(entities=setup_entities),
        "wamid.tc.collect.019a",
    )
    _customer, conversation, lead, _event = await capture_models(sessionmaker_fixture)
    assert lead.budget_data_status == "ASKED_PENDING"
    assert conversation.pending_action == "COLLECT_BUDGET"

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Mejor quiero gastronomía.",
        classification(
            "EVENT_INFORMATION",
            [entity("requested_services", "gastronomía", ["gastronomía"])],
        ),
        "wamid.tc.collect.019b",
    )
    _customer, conversation, lead, _event = await capture_models(sessionmaker_fixture)
    assert lead.budget_data_status == "DECLINED"
    assert conversation.state == "QUOTE_REQUEST_READY"
    assert "presupuesto" not in (await latest_outbox_body(sessionmaker_fixture)).casefold()

    for index in range(3):
        await run_turn(
            sessionmaker_fixture,
            settings,
            conversation.id,
            customer.id,
            f"Dato adicional {index}",
            classification("MODIFY_EVENT_DATA", []),
            f"wamid.tc.collect.019c{index}",
        )
        assert "presupuesto" not in (await latest_outbox_body(sessionmaker_fixture)).casefold()


@pytest.mark.asyncio
async def test_tc_collect_011_faq_preserves_pending_action(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(
                session, ConversationState.COLLECTING_EVENT_DATA
            )
            conversation.pending_action = "COLLECT_EVENT_DATE"

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "¿Tienen parqueadero?",
        classification("GENERAL_INFORMATION", information_category="parqueadero"),
        "wamid.tc.collect.011",
    )
    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation.id)
    assert conversation is not None
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "COLLECT_EVENT_DATE"


@pytest.mark.asyncio
async def test_tc_collect_012_quote_now_without_minimums_stays_collecting(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(
                session, ConversationState.COLLECTING_EVENT_DATA
            )

    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Sí, cotízame ya.",
        classification("QUOTE_REQUEST", []),
        "wamid.tc.collect.012",
    )
    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation.id)
    assert conversation is not None
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "COLLECT_EVENT_TYPE"


@pytest.mark.asyncio
async def test_tc_collect_013_duplicate_webhook_is_idempotent_during_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await configure_test_environment(monkeypatch)

    async def classify_quote(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return classification(entities=complete_entities())

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_quote)
    payload = json.loads(
        whatsapp_message_payload("wamid.tc.collect.013", text="Soy Natalia").decode()
    )
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))

    await asyncio.gather(
        process_whatsapp_webhook(payload, sessionmaker, "req-a"),
        process_whatsapp_webhook(payload, sessionmaker, "req-b"),
    )
    async with sessionmaker() as session:
        message_count = await session.scalar(select(func.count()).select_from(Message))
        lead_count = await session.scalar(select(func.count()).select_from(Lead))
        quote_count = await session.scalar(select(func.count()).select_from(QuoteRequest))
        outbox_count = await session.scalar(select(func.count()).select_from(Outbox))

    assert message_count == 1
    assert lead_count == 1
    assert quote_count == 0
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_tc_collect_014_one_question_per_turn(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Me interesa una boda.",
        classification(entities=[entity("event_type", "boda", "WEDDING")]),
        "wamid.tc.collect.014",
    )
    body = await latest_outbox_body(sessionmaker_fixture)
    assert body.count("?") == 1


@pytest.mark.asyncio
async def test_tc_collect_016_silence_about_date_keeps_date_pending(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Soy Andrés, quiero una boda para 40 personas.",
        classification(
            entities=[
                entity("full_name", "Soy Andrés", "Andrés"),
                entity("event_type", "boda", "WEDDING"),
                entity("guest_count", "40 personas", 40),
            ]
        ),
        "wamid.tc.collect.016",
    )
    _customer, conversation, _lead, event = await capture_models(sessionmaker_fixture)
    assert event.event_date_type is None
    assert "event_date" in conversation.pending_fields
    assert conversation.pending_action == "COLLECT_EVENT_DATE"


@pytest.mark.asyncio
async def test_tc_collect_017_date_pending_summary_uses_variant_without_placeholders(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    entities = [
        entity("full_name", "Soy Natalia", "Natalia"),
        entity("event_type", "boda", "WEDDING"),
        entity("guest_count", "45 personas", 45),
        date_entity("Todavía no sé la fecha", None, None, "UNKNOWN"),
        entity("estimated_budget", "10 millones", 10000000),
        entity("requested_services", "gastronomía", ["gastronomía"]),
    ]
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Todavía no sé la fecha.",
        classification(entities=entities),
        "wamid.tc.collect.017",
    )
    body = await latest_outbox_body(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        quote_request = await session.scalar(select(QuoteRequest))
    assert "fecha aún por definir" in body
    assert all(token not in body for token in ("None", "null", "{event_date}"))
    assert quote_request is not None
    assert quote_request.summary_snapshot["event_date_raw"] == "Todavía no sé la fecha"


@pytest.mark.asyncio
async def test_tc_collect_018_visit_flow_still_requires_absolute_date(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation = await seed_conversation(session)
    await run_turn(
        sessionmaker_fixture,
        settings,
        conversation.id,
        customer.id,
        "Quiero agendar una visita el otro sábado.",
        classification("SCHEDULE_VISIT", []),
        "wamid.tc.collect.018",
    )
    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation.id)
        quote_request = await session.scalar(select(QuoteRequest))
    assert conversation is not None
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert quote_request is None
