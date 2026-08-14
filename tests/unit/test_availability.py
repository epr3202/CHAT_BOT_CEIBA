from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.appointment.models import Appointment, BlockedDate, Holiday
from app.calendar.adapter import BusyInterval, FakeCalendarAdapter
from app.channel.states import Channel
from app.customer.models import Customer
from app.lead.models import Lead
from app.scheduling.availability import AvailabilityService, validate_visit_date
from tests.integration.helpers import cleanup_test_environment, reset_test_database

BOGOTA = ZoneInfo("America/Bogota")


def dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=BOGOTA)


def test_validate_visit_date_prioritizes_visit_rules_without_io() -> None:
    today = date(2026, 8, 14)

    assert validate_visit_date(
        date(2026, 8, 17), today=today, holidays=set(), blocked_dates=set()
    ).response_code == "RESP-VISIT-006"
    assert validate_visit_date(
        date(2026, 8, 18),
        today=date(2026, 8, 16),
        holidays=set(),
        blocked_dates=set(),
    ).response_code == "RESP-VISIT-004"


async def test_available_slots_applies_local_and_freebusy_intersection() -> None:
    sessionmaker = await reset_test_database()
    visit_date = date(2026, 8, 18)
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number="+573001112233")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel=Channel.WHATSAPP, lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            session.add(
                Appointment(
                    customer_id=customer.id,
                    lead_id=lead.lead_id,
                    appointment_date=visit_date,
                    start_time=time(10),
                    attendee_count=2,
                    visit_reason="boda",
                    appointment_status="CONFIRMED",
                    external_calendar_id="local-confirmed",
                )
            )

    fake = FakeCalendarAdapter(
        busy_by_calendar={
            "main": [BusyInterval(dt(visit_date, 9), dt(visit_date, 9, 30))],
        }
    )
    service = AvailabilityService(
        sessionmaker=sessionmaker,
        calendar_adapter=fake,
        freebusy_calendar_ids=["write", "main"],
    )

    result = await service.available_slots(visit_date, today=date(2026, 8, 14))

    assert [slot.start_time for slot in result.slots] == [time(8), time(11)]
    assert result.response_code == "RESP-VISIT-TIME-001"
    await cleanup_test_environment()


async def test_available_slots_rejects_holidays_and_blocked_dates_from_table() -> None:
    sessionmaker = await reset_test_database()
    holiday = date(2026, 8, 18)
    blocked = date(2026, 8, 19)
    async with sessionmaker() as session:
        async with session.begin():
            session.add(Holiday(holiday_date=holiday, name="Festivo", source="SEEDED"))
            session.add(BlockedDate(blocked_date=blocked, reason="Cierre", actor="SYSTEM"))

    service = AvailabilityService(
        sessionmaker=sessionmaker,
        calendar_adapter=FakeCalendarAdapter(),
        freebusy_calendar_ids=["write"],
    )

    holiday_result = await service.available_slots(holiday, today=date(2026, 8, 14))
    blocked_result = await service.available_slots(blocked, today=date(2026, 8, 14))

    assert holiday_result.response_code == "RESP-VISIT-007"
    assert blocked_result.response_code == "RESP-VISIT-008"
    await cleanup_test_environment()
