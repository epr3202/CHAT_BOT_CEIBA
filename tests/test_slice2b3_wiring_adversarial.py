from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.appointment.models import Appointment
from app.calendar.adapter import EventNotFoundError, FakeCalendarAdapter
from app.channel.inbound import process_whatsapp_webhook
from app.channel.states import Channel
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.orchestrator import service as orchestrator_module
from app.quote.models import QuoteRequest
from app.scheduling.availability import slot_datetime
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)

BOGOTA = ZoneInfo("America/Bogota")
NOW = datetime(2026, 8, 19, 9, tzinfo=BOGOTA)
VISIT_DATE = date(2026, 9, 19)
NEW_VISIT_DATE = date(2026, 9, 23)
PHONE = "+573001112233"


class ClassifierQueue:
    def __init__(self) -> None:
        self.by_text: dict[str, IntentClassification] = {}

    def add(self, text: str, result: IntentClassification) -> None:
        self.by_text[text] = result

    async def classify(
        self,
        client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return self.by_text[message_text]


@pytest.fixture
async def wiring_context(
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

    async def classify(
        client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return await classifier.classify(client, message_text, context, conversation_id)

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify)
    monkeypatch.setattr(
        orchestrator_module,
        "get_calendar_adapter",
        lambda settings: calendar,
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
    confidence: float = 0.95,
    entities: list[ExtractedEntity] | None = None,
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=confidence,
        information_category=None,
        entities={},
        extracted_entities=entities or [],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_WIRE",
    )


def entity(name: str, raw: str, normalized: Any) -> ExtractedEntity:
    return ExtractedEntity(
        entity=name,
        raw_value=raw,
        normalized_value=normalized,
        quality_status="PROVIDED",
        confidence=0.95,
        needs_confirmation=False,
        validation_errors=[],
    )


async def send_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    classifier: ClassifierQueue,
    *,
    message_id: str,
    text: str,
    result: IntentClassification,
) -> None:
    classifier.add(text, result)
    payload = json.loads(
        whatsapp_message_payload(message_id, phone=PHONE.removeprefix("+"), text=text).decode()
    )
    await process_whatsapp_webhook(payload, sessionmaker, request_id=message_id)


async def seed_customer(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    full_name: str = "Natalia Pérez",
) -> Customer:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name=full_name)
            session.add(customer)
            await session.flush()
            return customer


async def seed_capture(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    include_pending_budget: bool = False,
) -> tuple[Customer, Conversation, Lead, Event]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                lead_status="QUALIFYING",
                budget_data_status=("NOT_ASKED" if include_pending_budget else "PROVIDED"),
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
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.COLLECTING_EVENT_DATA,
                active_lead_id=lead.lead_id,
                pending_action=(
                    "COLLECT_BUDGET" if include_pending_budget else "COLLECT_SERVICES"
                ),
                pending_fields=(
                    ["estimated_budget", "requested_services"]
                    if include_pending_budget
                    else ["requested_services"]
                ),
                last_question_code=(
                    "RESP-BUDGET-001" if include_pending_budget else "RESP-EVENT-DATA-006"
                ),
            )
            session.add(conversation)
            await session.flush()
            return customer, conversation, lead, event


async def seed_confirmed_appointment(
    sessionmaker: async_sessionmaker[AsyncSession],
    calendar: FakeCalendarAdapter,
) -> tuple[Customer, Conversation, Appointment]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            appointment = Appointment(
                customer_id=customer.id,
                appointment_date=VISIT_DATE,
                start_time=time(9),
                attendee_count=2,
                visit_reason="una boda",
                appointment_status="CONFIRMED",
                external_calendar_id="placeholder",
            )
            session.add(appointment)
            await session.flush()
            appointment.external_calendar_id = appointment.appointment_id.hex
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.APPOINTMENT_CONFIRMED,
            )
            session.add(conversation)
            await session.flush()
    await calendar.create_event(
        appointment.appointment_id.hex,
        "Visita comercial La Ceiba Club House",
        slot_datetime(VISIT_DATE, time(9)),
        slot_datetime(VISIT_DATE, time(9, 45)),
    )
    return customer, conversation, appointment


async def conversation_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Conversation:
    async with sessionmaker() as session:
        conversation = await session.scalar(select(Conversation).order_by(Conversation.id.desc()))
    assert conversation is not None
    return conversation


async def complete_schedule_until_confirmation(
    sessionmaker: async_sessionmaker[AsyncSession],
    classifier: ClassifierQueue,
    *,
    prefix: str,
) -> None:
    turns = [
        ("schedule", "quiero agendar una visita", classification("SCHEDULE_VISIT")),
        ("date", "19 de septiembre de 2026", classification("UNKNOWN")),
        ("time", "la de las 9", classification("UNKNOWN")),
        ("attendees", "2 personas", classification("UNKNOWN")),
        ("reason", "para una boda", classification("UNKNOWN")),
    ]
    for suffix, text, result in turns:
        await send_turn(
            sessionmaker,
            classifier,
            message_id=f"{prefix}.{suffix}",
            text=text,
            result=result,
        )


@pytest.mark.asyncio
async def test_tc_wire_001_complete_happy_path_from_webhook(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await complete_schedule_until_confirmation(sessionmaker, classifier, prefix="wire.001")

    pending = await conversation_snapshot(sessionmaker)
    assert pending.state == ConversationState.APPOINTMENT_PENDING_CONFIRMATION
    assert pending.last_question_code == "RESP-VISIT-CONFIRM-001"

    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.001.confirm",
        text="sí",
        result=classification("CONFIRM"),
    )

    confirmed = await conversation_snapshot(sessionmaker)
    async with sessionmaker() as session:
        visit = await session.scalar(select(Appointment))
    assert confirmed.state == ConversationState.APPOINTMENT_CONFIRMED
    assert confirmed.last_question_code == "RESP-VISIT-CONFIRM-003"
    assert visit is not None
    assert visit.appointment_status == "CONFIRMED"
    event = await calendar.get_event(visit.appointment_id.hex)
    assert event.start == slot_datetime(VISIT_DATE, time(9))


@pytest.mark.asyncio
async def test_tc_wire_002_incident_date_isolation(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_capture(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.002.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.002.date",
        text="19 de septiembre",
        result=classification("UNKNOWN"),
    )

    async with sessionmaker() as session:
        event = await session.scalar(select(Event))
        conversation = await session.scalar(select(Conversation))
    assert event is not None
    assert conversation is not None
    assert event.event_date == date(2027, 2, 20)
    assert conversation.visit_draft["visit_date"] == "2026-09-19"
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION


@pytest.mark.asyncio
async def test_tc_wire_003_capture_resumes_and_reaches_quote_ready(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_capture(sessionmaker)
    await complete_schedule_until_confirmation(sessionmaker, classifier, prefix="wire.003")
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.003.confirm",
        text="sí",
        result=classification("CONFIRM"),
    )

    resumed = await conversation_snapshot(sessionmaker)
    assert resumed.state == ConversationState.COLLECTING_EVENT_DATA
    assert resumed.pending_action == "COLLECT_SERVICES"
    assert resumed.last_question_code == "RESP-EVENT-DATA-006"

    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.003.services",
        text="solo el espacio",
        result=classification(
            "EVENT_INFORMATION",
            entities=[entity("requested_services", "solo el espacio", ["espacio"])],
        ),
    )
    async with sessionmaker() as session:
        conversation = await session.scalar(select(Conversation))
        event = await session.scalar(select(Event))
        quote = await session.scalar(select(QuoteRequest))
    assert conversation is not None
    assert event is not None
    assert quote is not None
    assert conversation.state == ConversationState.QUOTE_REQUEST_READY
    assert event.event_date == date(2027, 2, 20)


@pytest.mark.asyncio
async def test_tc_wire_004_low_confidence_does_not_interrupt_capture(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_capture(sessionmaker, include_pending_budget=True)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.004",
        text="tal vez quiero una visita",
        result=classification("SCHEDULE_VISIT", confidence=0.80),
    )

    conversation = await conversation_snapshot(sessionmaker)
    async with sessionmaker() as session:
        appointment_count = await session.scalar(select(func.count()).select_from(Appointment))
    assert conversation.state == ConversationState.COLLECTING_EVENT_DATA
    assert conversation.visit_draft is None
    assert appointment_count == 0
    assert (
        ConversationState(conversation.state) not in orchestrator_module.APPOINTMENT_FLOW_STATES
    )


@pytest.mark.asyncio
async def test_tc_wire_005_clean_schedule_creates_no_spurious_handoff(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.005",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    async with sessionmaker() as session:
        handoff_count = await session.scalar(select(func.count()).select_from(Handoff))
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_DATE
    assert conversation.bot_enabled is True
    assert handoff_count == 0


@pytest.mark.asyncio
async def test_tc_wire_006_reservation_information_still_handoffs(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.006",
        text="quiero reservar la fecha",
        result=classification("RESERVATION_INFORMATION"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN


@pytest.mark.asyncio
async def test_tc_wire_007_sensitive_intent_precedes_appointment_state_handler(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.007.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.007.human",
        text="quiero hablar con una persona",
        result=classification("HUMAN_REQUEST"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.visit_draft is None


@pytest.mark.asyncio
async def test_tc_wire_008_busy_slot_is_excluded_end_to_end(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    calendar.add_busy(
        "business-main",
        slot_datetime(VISIT_DATE, time(9)),
        slot_datetime(VISIT_DATE, time(9, 45)),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.008.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.008.date",
        text="19 de septiembre de 2026",
        result=classification("UNKNOWN"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert "09:00" not in conversation.visit_draft["offered_slots"]
    assert conversation.visit_draft["offered_slots"] == ["08:00", "10:00", "11:00"]


@pytest.mark.asyncio
async def test_tc_wire_009_reschedule_updates_the_existing_external_event(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, calendar, classifier = wiring_context
    _customer, _conversation, visit = await seed_confirmed_appointment(sessionmaker, calendar)
    turns = [
        ("start", "quiero reprogramar mi visita", classification("RESCHEDULE_VISIT")),
        ("date", "23 de septiembre de 2026", classification("UNKNOWN")),
        ("time", "a las 10", classification("UNKNOWN")),
        ("confirm", "sí", classification("CONFIRM")),
    ]
    for suffix, text, result in turns:
        await send_turn(
            sessionmaker,
            classifier,
            message_id=f"wire.009.{suffix}",
            text=text,
            result=result,
        )

    event = await calendar.get_event(visit.appointment_id.hex)
    assert event.start == slot_datetime(NEW_VISIT_DATE, time(10))


@pytest.mark.asyncio
async def test_tc_wire_010_cancellation_removes_external_event(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, calendar, classifier = wiring_context
    _customer, _conversation, visit = await seed_confirmed_appointment(sessionmaker, calendar)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.010.start",
        text="quiero cancelar mi visita",
        result=classification("CANCEL_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.010.confirm",
        text="sí",
        result=classification("CONFIRM"),
    )

    with pytest.raises(EventNotFoundError):
        await calendar.get_event(visit.appointment_id.hex)
    async with sessionmaker() as session:
        cancelled = await session.get(Appointment, visit.appointment_id)
    assert cancelled is not None
    assert cancelled.appointment_status in {"CANCELLED", "LATE_CANCEL"}


@pytest.mark.asyncio
async def test_tc_wire_011_unknown_inside_date_state_reprompts_without_lead_write(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.011.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.011.unknown",
        text="cuando el cielo esté bonito",
        result=classification("UNKNOWN"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    async with sessionmaker() as session:
        lead_count = await session.scalar(select(func.count()).select_from(Lead))
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_DATE
    assert conversation.last_question_code == "RESP-VISIT-003"
    assert lead_count == 0


@pytest.mark.asyncio
async def test_tc_wire_012_calendar_failure_during_confirmation_is_safe(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await complete_schedule_until_confirmation(sessionmaker, classifier, prefix="wire.012")
    calendar.raise_on.add("query")
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.012.confirm",
        text="sí",
        result=classification("CONFIRM"),
    )

    conversation = await conversation_snapshot(sessionmaker)
    async with sessionmaker() as session:
        confirmed_count = await session.scalar(
            select(func.count()).select_from(Appointment).where(
                Appointment.appointment_status == "CONFIRMED"
            )
        )
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN
    assert conversation.last_question_code == "RESP-CALENDAR-ERROR-001"
    assert confirmed_count == 0


@pytest.mark.parametrize("intent", ["RESCHEDULE_VISIT", "CANCEL_VISIT"])
@pytest.mark.asyncio
async def test_tc_wire_013_no_active_appointment_uses_service_code_and_handoff(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
    intent: str,
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    text = "quiero cambiar mi visita" if intent == "RESCHEDULE_VISIT" else "cancela mi visita"
    await send_turn(
        sessionmaker,
        classifier,
        message_id=f"wire.013.{intent.lower()}",
        text=text,
        result=classification(intent),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN
    assert conversation.last_question_code == (
        "RESP-RESCHEDULE-006"
        if intent == "RESCHEDULE_VISIT"
        else "RESP-CANCEL-VISIT-005"
    )


@pytest.mark.asyncio
async def test_tc_wire_014_exact_text_date_precedes_schedule_intent(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.014.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.014.date",
        text="26 de agosto",
        result=classification("SCHEDULE_VISIT", confidence=0.90),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION
    assert conversation.last_question_code == "RESP-VISIT-TIME-001"
    assert conversation.visit_draft["visit_date"] == "2026-08-26"
    assert conversation.visit_draft["offered_slots"] == ["08:00", "09:00", "10:00", "11:00"]


@pytest.mark.asyncio
async def test_tc_wire_015_numeric_date_precedes_schedule_intent(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.015.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.015.date",
        text="26-08-2026",
        result=classification("SCHEDULE_VISIT", confidence=0.90),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION
    assert conversation.last_question_code == "RESP-VISIT-TIME-001"
    assert conversation.visit_draft["visit_date"] == "2026-08-26"


@pytest.mark.asyncio
async def test_tc_wire_016_interpretable_time_precedes_schedule_intent(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.016.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.016.date",
        text="26 de agosto",
        result=classification("UNKNOWN"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.016.time",
        text="a las 9",
        result=classification("SCHEDULE_VISIT", confidence=0.90),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION
    assert conversation.pending_action == "COLLECT_VISIT_ATTENDEES"
    assert conversation.last_question_code == "RESP-VISIT-DATA-001"
    assert conversation.visit_draft["visit_time"] == "09:00"


@pytest.mark.asyncio
async def test_tc_wire_017_non_interpretable_schedule_intent_still_restarts_attempt(
    wiring_context: tuple[async_sessionmaker[AsyncSession], FakeCalendarAdapter, ClassifierQueue],
) -> None:
    sessionmaker, _calendar, classifier = wiring_context
    await seed_customer(sessionmaker)
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.017.schedule",
        text="quiero agendar una visita",
        result=classification("SCHEDULE_VISIT"),
    )
    await send_turn(
        sessionmaker,
        classifier,
        message_id="wire.017.restart",
        text="quiero empezar de nuevo",
        result=classification("SCHEDULE_VISIT", confidence=0.90),
    )

    conversation = await conversation_snapshot(sessionmaker)
    assert conversation.state == ConversationState.WAITING_FOR_APPOINTMENT_DATE
    assert conversation.last_question_code == "RESP-VISIT-003"
    assert conversation.visit_draft == {"mode": "SCHEDULE", "resume": None}
