from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.appointment.models import Appointment
from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset, CatalogEventTypeMap
from app.channel.inbound import process_whatsapp_webhook
from app.channel.media import sha256_file
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    cleanup_test_environment,
    configure_test_environment,
    database_sessionmaker,
    reset_test_database,
    whatsapp_message_payload,
)

CATALOG_CAPTURE_ACTION = "COLLECT_CATALOG_EVENT_TYPE"
PHONE = "+57300999%04d"


@pytest.fixture(autouse=True)
async def test_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setenv("CATALOG_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    yield
    await cleanup_test_environment()


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async for sessionmaker in database_sessionmaker():
        yield sessionmaker


def classification(
    intent: str,
    *,
    confidence: float = 0.95,
    information_category: str | None = None,
    event_type: str | None = None,
    requested_action: str | None = None,
) -> IntentClassification:
    extracted_entities: list[ExtractedEntity] = []
    if event_type is not None:
        extracted_entities.append(
            ExtractedEntity(
                entity="event_type",
                raw_value=event_type,
                normalized_value=event_type,
                quality_status="PROVIDED",
                confidence=0.95,
                needs_confirmation=False,
                validation_errors=[],
            )
        )
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=confidence,
        information_category=information_category,
        entities={},
        extracted_entities=extracted_entities,
        requested_action=requested_action,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_CATCAP",
    )


def catalog_request(*, event_type: str | None = None) -> IntentClassification:
    return classification(
        "GENERAL_INFORMATION",
        information_category="catalogo",
        event_type=event_type,
        requested_action="START_INFORMATION_FLOW",
    )


async def seed_context(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_type: str | None = None,
    with_lead: bool = True,
    state: ConversationState = ConversationState.BOT_ACTIVE,
    pending_action: str | None = None,
    failed_understanding_count: int = 0,
) -> tuple[int, UUID | None]:
    phone = PHONE % (uuid4().int % 10_000)
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead_id: UUID | None = None
            if with_lead:
                lead = Lead(
                    customer_id=customer.id,
                    channel=Channel.WHATSAPP,
                    lead_status="QUALIFYING",
                )
                session.add(lead)
                await session.flush()
                lead_id = lead.lead_id
                session.add(Event(lead_id=lead_id, event_type=event_type))
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=state,
                active_lead_id=lead_id,
                pending_action=pending_action,
                failed_understanding_count=failed_understanding_count,
            )
            session.add(conversation)
            await session.flush()
            return conversation.id, lead_id


async def install_catalog_capture(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: int
) -> None:
    # Phase 2 must reach the missing behavior before the official validator exists.
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(pending_action=CATALOG_CAPTURE_ACTION)
            )


async def add_inbound(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: int, text: str
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            inbound = Message(
                external_message_id=f"wamid.catcap.{uuid4()}",
                conversation_id=conversation.id,
                customer_id=conversation.customer_id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": text}},
                provider_timestamp=None,
            )
            session.add(inbound)
            await session.flush()
            return inbound.id


async def orchestrate(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
    text: str,
    result: IntentClassification,
    *,
    request_id: str,
) -> None:
    inbound_id = await add_inbound(sessionmaker, conversation_id, text)
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            inbound = await session.get(Message, inbound_id)
            assert conversation is not None
            assert inbound is not None
            customer = await session.get(Customer, conversation.customer_id)
            assert customer is not None
            await orchestrate_inbound_message(
                session,
                get_settings(),
                sessionmaker,
                OrchestrationInput(conversation, customer, inbound, text, request_id),
                result,
            )


async def seed_catalog(
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    event_type: str = "ROMANTIC_DINNER",
    send_mode: str = "ON_REQUEST",
) -> UUID:
    file_path = tmp_path / f"{event_type.lower()}-{uuid4()}.pdf"
    file_path.write_bytes(b"%PDF-1.4\nfixture")
    async with sessionmaker() as session:
        async with session.begin():
            asset = CatalogAsset(
                name=f"Catálogo {event_type}",
                file_path=file_path.name,
                file_hash=sha256_file(file_path),
                mime_type="application/pdf",
                file_size=file_path.stat().st_size,
                active=True,
                version=1,
            )
            session.add(asset)
            await session.flush()
            session.add(
                CatalogEventTypeMap(
                    catalog_asset_id=asset.catalog_asset_id,
                    event_type=event_type,
                    send_mode=send_mode,
                )
            )
            return asset.catalog_asset_id


async def snapshot(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: int
) -> Conversation:
    async with sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    return conversation


async def outboxes(
    sessionmaker: async_sessionmaker[AsyncSession], *, kind: str | None = None
) -> list[Outbox]:
    async with sessionmaker() as session:
        query = select(Outbox).order_by(Outbox.id)
        if kind is not None:
            query = query.where(Outbox.message_kind == kind)
        return list((await session.scalars(query)).all())


async def audit(
    sessionmaker: async_sessionmaker[AsyncSession], action: str
) -> AuditEvent | None:
    async with sessionmaker() as session:
        return await session.scalar(select(AuditEvent).where(AuditEvent.action == action))


@pytest.mark.asyncio
async def test_tc_catcap_001_same_message_entity_sends_without_lead(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, _ = await seed_context(
        sessionmaker_fixture, with_lead=False, pending_action="CONFIRM_QUOTE_REQUEST"
    )

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Quiero ver los planes románticos",
        catalog_request(event_type="ROMANTIC_DINNER"),
        request_id="req-catcap-001",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    assert len(await outboxes(sessionmaker_fixture, kind="DOCUMENT")) == 1
    assert conversation.last_question_code != "RESP-CATALOG-002"
    assert conversation.pending_action == "CONFIRM_QUOTE_REQUEST"
    async with sessionmaker_fixture() as session:
        handoff_count = await session.scalar(select(func.count()).select_from(Handoff))
    assert handoff_count == 0


@pytest.mark.asyncio
async def test_tc_catcap_002_question_installs_capture_action(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, with_lead=False)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "¿Tienen catálogo?",
        catalog_request(),
        request_id="req-catcap-002",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    started = await audit(sessionmaker_fixture, "CATALOG_CAPTURE_STARTED")
    assert conversation.last_question_code == "RESP-CATALOG-002"
    assert conversation.pending_action == CATALOG_CAPTURE_ACTION
    assert started is not None
    assert started.request_id == "req-catcap-002"


@pytest.mark.asyncio
async def test_tc_catcap_003_label_beats_ask_confirmation_band(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Cena romántica",
        classification("GENERAL_INFORMATION", confidence=0.65),
        request_id="req-catcap-003",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    assert len(await outboxes(sessionmaker_fixture, kind="DOCUMENT")) == 1
    assert conversation.pending_action is None
    assert conversation.last_question_code != "RESP-FALLBACK-004"


@pytest.mark.asyncio
async def test_tc_catcap_004_entity_without_mapping_returns_unavailable(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Es para una propuesta",
        classification("EVENT_INFORMATION", event_type="PROPOSAL"),
        request_id="req-catcap-004",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
    assert conversation.last_question_code == "RESP-CATALOG-003"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.bot_enabled is False
    assert handoff is not None
    assert handoff.reason == "CATALOG_NOT_AVAILABLE"
    assert "PROPOSAL" in handoff.summary
    unavailable = await audit(sessionmaker_fixture, "CATALOG_HANDOFF_NOT_AVAILABLE")
    assert unavailable is not None
    assert unavailable.new_value is not None
    assert unavailable.new_value["event_type"] == "PROPOSAL"


@pytest.mark.asyncio
async def test_tc_catcap_005_first_unresolved_answer_reprompts(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "quiero algo bonito",
        classification("UNKNOWN"),
        request_id="req-catcap-005",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    assert conversation.last_question_code == "RESP-CATALOG-002"
    assert conversation.failed_understanding_count == 1
    assert conversation.pending_action == CATALOG_CAPTURE_ACTION
    assert await audit(sessionmaker_fixture, "CATALOG_EVENT_TYPE_UNRESOLVED") is not None


@pytest.mark.asyncio
async def test_tc_catcap_006_second_unresolved_answer_returns_to_normal_routing(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(
        sessionmaker_fixture, event_type=None, failed_understanding_count=1
    )
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "todavía no sé",
        classification("UNKNOWN"),
        request_id="req-catcap-006",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    unresolved = await audit(sessionmaker_fixture, "CATALOG_EVENT_TYPE_UNRESOLVED")
    assert conversation.failed_understanding_count == 2
    assert conversation.pending_action != CATALOG_CAPTURE_ACTION
    assert conversation.last_question_code == "RESP-FALLBACK-002"
    assert unresolved is not None
    assert unresolved.request_id == "req-catcap-006"


@pytest.mark.asyncio
async def test_tc_catcap_007_high_confidence_visit_abandons_capture(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Quiero agendar una visita",
        classification("SCHEDULE_VISIT"),
        request_id="req-catcap-007",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    abandoned = await audit(sessionmaker_fixture, "CATALOG_CAPTURE_ABANDONED")
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_DATE.value
    assert conversation.pending_action == "SELECT_VISIT_DATE"
    assert abandoned is not None
    assert abandoned.request_id == "req-catcap-007"


@pytest.mark.asyncio
async def test_tc_catcap_008_cycle_preserves_confirmed_appointment(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, lead_id = await seed_context(
        sessionmaker_fixture,
        event_type=None,
        state=ConversationState.APPOINTMENT_CONFIRMED,
    )
    async with sessionmaker_fixture() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            appointment = Appointment(
                customer_id=conversation.customer_id,
                lead_id=lead_id,
                appointment_date=date(2026, 9, 19),
                start_time=time(9),
                attendee_count=2,
                visit_reason="planes románticos",
                appointment_status="CONFIRMED",
                external_calendar_id=f"calendar-{uuid4().hex}",
            )
            session.add(appointment)
            await session.flush()
            appointment_id = appointment.appointment_id

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Quiero el catálogo",
        catalog_request(),
        request_id="req-catcap-008-start",
    )
    await install_catalog_capture(sessionmaker_fixture, conversation_id)
    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Cena romántica",
        classification("GENERAL_INFORMATION", confidence=0.65),
        request_id="req-catcap-008-resolve",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        appointment = await session.get(Appointment, appointment_id)
    assert len(await outboxes(sessionmaker_fixture, kind="DOCUMENT")) == 1
    assert conversation.state == ConversationState.APPOINTMENT_CONFIRMED.value
    assert appointment is not None
    assert appointment.appointment_status == "CONFIRMED"
    assert appointment.appointment_date == date(2026, 9, 19)
    assert appointment.start_time == time(9)
    assert appointment.attendee_count == 2


@pytest.mark.asyncio
async def test_tc_catcap_009_message_entity_precedes_lead_event(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    romantic_asset_id = await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type="WEDDING")

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Quiero los planes románticos",
        catalog_request(event_type="ROMANTIC_DINNER"),
        request_id="req-catcap-009",
    )

    documents = await outboxes(sessionmaker_fixture, kind="DOCUMENT")
    assert len(documents) == 1
    assert documents[0].catalog_asset_id == romantic_asset_id


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["CENA ROMANTICA", "los planes románticos"])
async def test_tc_catcap_010_normalized_romantic_label_without_entity_resolves(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path, reply: str
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        reply,
        classification("GENERAL_INFORMATION", confidence=0.65),
        request_id="req-catcap-010",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    assert len(await outboxes(sessionmaker_fixture, kind="DOCUMENT")) == 1
    assert conversation.pending_action is None
    assert conversation.last_question_code != "RESP-FALLBACK-004"


@pytest.mark.asyncio
async def test_tc_catcap_011_duplicate_webhook_enqueues_one_catalog(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path)
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)
    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        customer = await session.get(Customer, conversation.customer_id)
    assert customer is not None

    async def classify_capture_reply(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        return classification(
            "GENERAL_INFORMATION", confidence=0.65, event_type="ROMANTIC_DINNER"
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_capture_reply)
    payload = json.loads(
        whatsapp_message_payload(
            "wamid.catcap.011",
            phone=customer.phone_number.removeprefix("+"),
            text="Cena romántica",
        ).decode()
    )

    await process_whatsapp_webhook(payload, sessionmaker_fixture, "req-catcap-011-a")
    await process_whatsapp_webhook(payload, sessionmaker_fixture, "req-catcap-011-b")

    async with sessionmaker_fixture() as session:
        inbound_count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.external_message_id == "wamid.catcap.011")
        )
    assert inbound_count == 1
    assert len(await outboxes(sessionmaker_fixture, kind="DOCUMENT")) == 1


@pytest.mark.asyncio
async def test_tc_catcap_012_emergency_abandons_capture_and_hands_off(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Hay una emergencia",
        classification("EMERGENCY"),
        request_id="req-catcap-012",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
    abandoned = await audit(sessionmaker_fixture, "CATALOG_CAPTURE_ABANDONED")
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert handoff is not None
    assert handoff.reason == "URGENT_EVENT"
    assert abandoned is not None
    assert abandoned.request_id == "req-catcap-012"


@pytest.mark.asyncio
async def test_tc_catcap_013_exact_proposal_label_never_partially_matches_wedding(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_catalog(sessionmaker_fixture, tmp_path, event_type="WEDDING")
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Propuesta de matrimonio",
        classification("GENERAL_INFORMATION", confidence=0.65),
        request_id="req-catcap-013",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
    assert conversation.last_question_code == "RESP-CATALOG-003"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.bot_enabled is False
    assert await outboxes(sessionmaker_fixture, kind="DOCUMENT") == []
    assert handoff is not None
    assert handoff.reason == "CATALOG_NOT_AVAILABLE"
    assert "PROPOSAL" in handoff.summary
    unavailable = await audit(sessionmaker_fixture, "CATALOG_HANDOFF_NOT_AVAILABLE")
    assert unavailable is not None
    assert unavailable.new_value is not None
    assert unavailable.new_value["event_type"] == "PROPOSAL"


@pytest.mark.asyncio
async def test_tc_catcap_014_explicit_gender_reveal_without_mapping_hands_off(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        "Quiero el catálogo de revelación de género",
        catalog_request(event_type="GENDER_REVEAL"),
        request_id="req-catcap-014",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
    unavailable = await audit(sessionmaker_fixture, "CATALOG_HANDOFF_NOT_AVAILABLE")
    assert conversation.last_question_code == "RESP-CATALOG-003"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.bot_enabled is False
    assert handoff is not None
    assert handoff.reason == "CATALOG_NOT_AVAILABLE"
    assert "GENDER_REVEAL" in handoff.summary
    assert unavailable is not None
    assert unavailable.request_id == "req-catcap-014"
    assert unavailable.new_value is not None
    assert unavailable.new_value["event_type"] == "GENDER_REVEAL"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply", ["revelación de género", "revelacion de genero", "gender reveal"]
)
async def test_tc_catcap_015_gender_reveal_labels_resolve_and_handoff(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], reply: str
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    await install_catalog_capture(sessionmaker_fixture, conversation_id)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        reply,
        classification("GENERAL_INFORMATION", confidence=0.65),
        request_id="req-catcap-015",
    )

    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
    assert conversation.last_question_code == "RESP-CATALOG-003"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert handoff is not None
    assert handoff.reason == "CATALOG_NOT_AVAILABLE"
    assert "GENDER_REVEAL" in handoff.summary


@pytest.mark.asyncio
async def test_tc_catcap_016_duplicate_unavailable_webhook_creates_one_handoff(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    conversation_id, _ = await seed_context(sessionmaker_fixture, event_type=None)
    conversation = await snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        customer = await session.get(Customer, conversation.customer_id)
    assert customer is not None

    async def classify_gender_reveal_request(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        return catalog_request(event_type="GENDER_REVEAL")

    monkeypatch.setattr(
        OpenRouterIntentClient, "classify_intent", classify_gender_reveal_request
    )
    payload = json.loads(
        whatsapp_message_payload(
            "wamid.catcap.016",
            phone=customer.phone_number.removeprefix("+"),
            text="Quiero el catálogo de revelación de género",
        ).decode()
    )

    await process_whatsapp_webhook(payload, sessionmaker_fixture, "req-catcap-016-a")
    await process_whatsapp_webhook(payload, sessionmaker_fixture, "req-catcap-016-b")

    async with sessionmaker_fixture() as session:
        handoff_count = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.conversation_id == conversation_id)
        )
        response_count = await session.scalar(
            select(func.count())
            .select_from(Outbox)
            .where(Outbox.conversation_id == conversation_id)
        )
    assert handoff_count == 1
    assert response_count == 1
