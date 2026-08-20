from __future__ import annotations

import inspect
from datetime import date, datetime, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

import app.appointment.service as appointment_service
from app.appointment.models import Appointment
from app.appointment.service import VisitSchedulingService
from app.calendar.adapter import FakeCalendarAdapter
from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.integration.helpers import cleanup_test_environment, reset_test_database

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 8, 14)
ORIGINAL_DATE = date(2026, 8, 18)
NEW_DATE = date(2026, 8, 19)
SUMMARY = "Visita comercial La Ceiba Club House"
FULL_DESCRIPTION = "\n".join(
    (
        "Nombre del cliente: Natalia Pérez",
        "Teléfono: +573001112233",
        "Tipo de evento: WEDDING",
        "Invitados del evento: 80",
        "Asistentes a la visita: 2",
        "Motivo de la visita: Conocer el salón",
    )
)


def at_bogota(target_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(target_date, time(hour, minute), tzinfo=BOGOTA)


def service(sessionmaker: Any, fake: FakeCalendarAdapter) -> VisitSchedulingService:
    return VisitSchedulingService(
        sessionmaker=sessionmaker,
        calendar_adapter=fake,
        freebusy_calendar_ids=["write-calendar", "business-main"],
    )


async def seed_customer(
    sessionmaker: Any, *, with_lead: bool
) -> tuple[int, int, Any | None]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number="+573001112233", full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead_id = None
            if with_lead:
                lead = Lead(
                    customer_id=customer.id,
                    channel=Channel.WHATSAPP,
                    lead_status="QUALIFYING",
                )
                session.add(lead)
                await session.flush()
                lead_id = lead.lead_id
                session.add(Event(lead_id=lead_id, event_type="WEDDING", guest_count=80))
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                active_lead_id=lead_id,
            )
            session.add(conversation)
            await session.flush()
            return customer.id, conversation.id, lead_id


async def seed_confirmed_appointment(
    sessionmaker: Any,
    fake: FakeCalendarAdapter,
    *,
    external_exists: bool,
) -> Appointment:
    customer_id, _conversation_id, lead_id = await seed_customer(
        sessionmaker, with_lead=True
    )
    appointment = Appointment(
        appointment_id=uuid4(),
        customer_id=customer_id,
        lead_id=lead_id,
        appointment_date=ORIGINAL_DATE,
        start_time=time(9),
        attendee_count=2,
        visit_reason="Conocer el salón",
        appointment_status="CONFIRMED",
    )
    appointment.external_calendar_id = appointment.appointment_id.hex
    async with sessionmaker() as session:
        async with session.begin():
            session.add(appointment)
            await session.flush()
    if external_exists:
        assert "description" in inspect.signature(fake.create_event).parameters
        await fake.create_event(
            appointment.appointment_id.hex,
            SUMMARY,
            at_bogota(ORIGINAL_DATE, 9),
            at_bogota(ORIGINAL_DATE, 9, 45),
            description="Descripción obsoleta",
        )
    return appointment


@pytest.fixture(autouse=True)
async def cleanup_settings() -> Any:
    yield
    await cleanup_test_environment()


def test_tc_caldesc_001_pure_builder_formats_all_fields_in_documented_order() -> None:
    builder = getattr(appointment_service, "build_visit_description", None)
    assert callable(builder), "build_visit_description must be a pure public helper"

    assert builder(
        customer_name="Natalia Pérez",
        phone_number="+573001112233",
        event_type="WEDDING",
        event_guest_count=80,
        visit_attendee_count=2,
        visit_reason="Conocer el salón",
    ) == FULL_DESCRIPTION


def test_tc_caldesc_002_pure_builder_omits_missing_lines_without_placeholders() -> None:
    builder = getattr(appointment_service, "build_visit_description", None)
    assert callable(builder), "build_visit_description must be a pure public helper"

    description = builder(
        customer_name="Natalia Pérez",
        phone_number="+573001112233",
        event_type=None,
        event_guest_count=None,
        visit_attendee_count=1,
        visit_reason="Conocer el lugar",
    )
    assert description == "\n".join(
        (
            "Nombre del cliente: Natalia Pérez",
            "Teléfono: +573001112233",
            "Asistentes a la visita: 1",
            "Motivo de la visita: Conocer el lugar",
        )
    )
    assert "None" not in description
    assert "Sin " not in description


@pytest.mark.asyncio
async def test_tc_caldesc_002b_fake_adapter_accepts_and_exposes_description() -> None:
    fake = FakeCalendarAdapter()
    assert "description" in inspect.signature(fake.create_event).parameters
    assert inspect.signature(fake.create_event).parameters["description"].default is None

    event = await fake.create_event(
        "0abcde12345",
        SUMMARY,
        at_bogota(ORIGINAL_DATE, 9),
        at_bogota(ORIGINAL_DATE, 9, 45),
        description="Nombre del cliente: Natalia Pérez",
    )

    assert event.description == "Nombre del cliente: Natalia Pérez"


@pytest.mark.asyncio
async def test_tc_caldesc_003_confirmation_with_complete_lead_populates_fake_event() -> None:
    sessionmaker = await reset_test_database()
    customer_id, conversation_id, lead_id = await seed_customer(sessionmaker, with_lead=True)
    fake = FakeCalendarAdapter()

    result = await service(sessionmaker, fake).confirm_appointment(
        customer_id=customer_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        visit_date=ORIGINAL_DATE,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="Conocer el salón",
        customer_confirmation=True,
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(result.appointment_id.hex)
    assert hasattr(event, "description")
    assert event.description == FULL_DESCRIPTION


@pytest.mark.asyncio
async def test_tc_caldesc_004_confirmation_without_lead_omits_event_lines() -> None:
    sessionmaker = await reset_test_database()
    customer_id, conversation_id, lead_id = await seed_customer(sessionmaker, with_lead=False)
    fake = FakeCalendarAdapter()

    result = await service(sessionmaker, fake).confirm_appointment(
        customer_id=customer_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        visit_date=ORIGINAL_DATE,
        visit_time=time(9),
        attendee_count=1,
        visit_reason="Conocer el lugar",
        customer_confirmation=True,
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(result.appointment_id.hex)
    assert hasattr(event, "description")
    assert event.description == "\n".join(
        (
            "Nombre del cliente: Natalia Pérez",
            "Teléfono: +573001112233",
            "Asistentes a la visita: 1",
            "Motivo de la visita: Conocer el lugar",
        )
    )


@pytest.mark.asyncio
async def test_tc_caldesc_005_reschedule_rebuilds_description_without_duplication() -> None:
    sessionmaker = await reset_test_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(
        sessionmaker, fake, external_exists=True
    )

    result = await service(sessionmaker, fake).reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert event.description == FULL_DESCRIPTION
    assert event.description.count("Nombre del cliente:") == 1
    assert "Descripción obsoleta" not in event.description


@pytest.mark.asyncio
async def test_tc_caldesc_006_event_not_found_reconciliation_recreates_description() -> None:
    sessionmaker = await reset_test_database()
    fake = FakeCalendarAdapter()
    appointment = await seed_confirmed_appointment(
        sessionmaker, fake, external_exists=False
    )

    result = await service(sessionmaker, fake).reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )

    event = await fake.get_event(appointment.appointment_id.hex)
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert fake.created_event_ids == [appointment.appointment_id.hex]
    assert hasattr(event, "description")
    assert event.description == FULL_DESCRIPTION
