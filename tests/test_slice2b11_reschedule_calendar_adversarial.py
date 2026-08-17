from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.appointment.models import Appointment
from app.appointment.service import VisitSchedulingService
from app.calendar.adapter import AlreadyExistsError, FakeCalendarAdapter
from app.channel.states import Channel
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.lead.models import Lead
from tests.integration.helpers import cleanup_test_environment, reset_test_database

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 8, 14)
ORIGINAL_DATE = date(2026, 8, 18)
NEW_DATE = date(2026, 8, 19)
SUMMARY = "Visita comercial La Ceiba Club House"


def at_bogota(target_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(target_date, time(hour, minute), tzinfo=BOGOTA)


async def prepare_database() -> Any:
    sessionmaker = await reset_test_database()
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                KnowledgeEntry(
                    code="RESP-AI-ERROR-001",
                    category="Fallback",
                    question_summary="Error",
                    answer_template="Error seguro.",
                    allowed_variables=[],
                    version=1,
                    status="APPROVED",
                )
            )
    return sessionmaker


async def seed_customer_context(sessionmaker: Any) -> tuple[int, Any]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=f"+573{uuid4().int % 10_000_0000:08d}")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel=Channel.WHATSAPP, lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                active_lead_id=lead.lead_id,
            )
            session.add(conversation)
            return customer.id, lead.lead_id


async def seed_confirmed_appointment(
    sessionmaker: Any,
    *,
    fake: FakeCalendarAdapter | None = None,
    seed_external_event: bool = True,
) -> Appointment:
    customer_id, lead_id = await seed_customer_context(sessionmaker)
    appointment_id = uuid4()
    appointment = Appointment(
        appointment_id=appointment_id,
        customer_id=customer_id,
        lead_id=lead_id,
        appointment_date=ORIGINAL_DATE,
        start_time=time(9),
        timezone="America/Bogota",
        attendee_count=2,
        visit_reason="boda",
        appointment_status="CONFIRMED",
        external_calendar_id=appointment_id.hex,
    )
    async with sessionmaker() as session:
        async with session.begin():
            session.add(appointment)
            await session.flush()
    if fake is not None and seed_external_event:
        await fake.create_event(
            appointment_id.hex,
            SUMMARY,
            at_bogota(ORIGINAL_DATE, 9),
            at_bogota(ORIGINAL_DATE, 9, 45),
        )
    async with sessionmaker() as session:
        return await session.get(Appointment, appointment_id)


def visit_service(sessionmaker: Any, fake: FakeCalendarAdapter) -> VisitSchedulingService:
    return VisitSchedulingService(
        sessionmaker=sessionmaker,
        calendar_adapter=fake,
        freebusy_calendar_ids=["write-calendar", "business-main"],
    )


@pytest.fixture(autouse=True)
async def cleanup_settings() -> Any:
    yield
    await cleanup_test_environment()


async def test_tc_resched_cal_001_success_moves_external_event_to_new_window() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(sessionmaker, fake=fake)
    service = visit_service(sessionmaker, fake)

    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert event.start == at_bogota(NEW_DATE, 10)
    assert event.end == at_bogota(NEW_DATE, 10, 45)


async def test_tc_resched_cal_002_update_uses_original_event_id_without_suffixes() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(sessionmaker, fake=fake)
    service = visit_service(sessionmaker, fake)

    await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    assert fake.updated_event_ids == [appointment.appointment_id.hex]


async def test_tc_resched_cal_003_missing_external_event_falls_back_to_create() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(
        sessionmaker,
        fake=fake,
        seed_external_event=False,
    )
    service = visit_service(sessionmaker, fake)

    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert fake.created_event_ids == [appointment.appointment_id.hex]
    assert event.start == at_bogota(NEW_DATE, 10)
    assert event.end == at_bogota(NEW_DATE, 10, 45)


async def test_tc_resched_cal_004_transient_update_failure_retries_and_succeeds() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter(fail_update_once=True)
    appointment = await seed_confirmed_appointment(sessionmaker, fake=fake)
    service = visit_service(sessionmaker, fake)

    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert fake.update_call_count == 2
    assert event.start == at_bogota(NEW_DATE, 10)


async def test_tc_resched_cal_005_persistent_update_failure_leaves_db_untouched() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter(raise_on={"update"})
    appointment = await seed_confirmed_appointment(sessionmaker, fake=fake)
    service = visit_service(sessionmaker, fake)

    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    async with sessionmaker() as session:
        unchanged = await session.get(Appointment, appointment.appointment_id)
    assert result.response_code == "RESP-CALENDAR-ERROR-003"
    assert unchanged.appointment_date == ORIGINAL_DATE
    assert unchanged.start_time == time(9)
    assert unchanged.reschedule_count == 0


async def test_tc_resched_cal_006_double_reschedule_same_window_is_idempotent() -> None:
    sessionmaker = await prepare_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(sessionmaker, fake=fake)
    service = visit_service(sessionmaker, fake)

    first = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )
    async with sessionmaker() as session:
        moved = await session.get(Appointment, appointment.appointment_id)
        moved.appointment_status = "CONFIRMED"
        moved.appointment_date = ORIGINAL_DATE
        moved.start_time = time(9)
        await session.commit()
    second = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert first.response_code == "RESP-RESCHEDULE-004"
    assert second.response_code == "RESP-RESCHEDULE-004"
    assert event.start == at_bogota(NEW_DATE, 10)
    assert event.end == at_bogota(NEW_DATE, 10, 45)


async def test_tc_resched_cal_007_confirmation_still_reconciles_already_existing_create(
    monkeypatch: Any,
) -> None:
    sessionmaker = await prepare_database()
    customer_id, lead_id = await seed_customer_context(sessionmaker)
    fake = FakeCalendarAdapter()
    service = visit_service(sessionmaker, fake)

    async def create_already_exists(*args: Any, **kwargs: Any) -> None:
        raise AlreadyExistsError("calendar event already exists")

    monkeypatch.setattr(fake, "create_event", create_already_exists)

    result = await service.confirm_appointment(
        customer_id=customer_id,
        lead_id=lead_id,
        conversation_id=1,
        visit_date=ORIGINAL_DATE,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(TODAY, 9),
    )

    async with sessionmaker() as session:
        appointment = await session.get(Appointment, result.appointment_id)
    assert result.response_code == "RESP-VISIT-CONFIRM-003"
    assert appointment.appointment_status == "CONFIRMED"
    assert appointment.external_calendar_id == appointment.appointment_id.hex
    assert fake.updated_event_ids == []
