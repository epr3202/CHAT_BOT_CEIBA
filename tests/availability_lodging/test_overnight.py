from datetime import datetime, time, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.orchestrator.booking_flow import BookingAgendaService
from app.plan.models import Plan
from app.reservation.availability import (
    BookingAvailability,
    evaluate_booking_availability,
    validate_booking_window,
)
from app.reservation.booking import create_pending_reservation
from app.reservation.models import Reservation
from app.reservation.settlement import sync_reservation_calendar
from tests.availability_lodging.helpers import START, require_overnight_columns, seed_booking
from tests.booking_backend.helpers import plan as pure_plan
from tests.booking_backend.helpers import settings
from tests.booking_conversation.helpers import code
from tests.visit_booking_guard.helpers import BOGOTA, Harness


async def create_overnight_request(harness: Harness) -> Reservation:
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        row = await session.get(Conversation, conversation.id)
        return await create_pending_reservation(
            session,
            lead=await session.get(Lead, row.active_lead_id),
            event=await session.scalar(select(Event).where(Event.lead_id == row.active_lead_id)),
            plan=await session.scalar(select(Plan).where(Plan.code == "REFUGIO_DOS")),
            customer=await session.get(Customer, row.customer_id),
            conversation=row,
            starts_at=START,
            actor="SYSTEM",
            request_id=str(uuid4()),
        )


async def test_R_refugio_19_valid_and_ends_at_next_checkout(harness: Harness) -> None:
    require_overnight_columns()
    await seed_booking(harness, code="REFUGIO_DOS")
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("CONFIRM")]
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert await harness.rows(Reservation) == []
    reservation = await create_overnight_request(harness)
    checkout = datetime.combine(START.date() + timedelta(days=1), time(11), tzinfo=BOGOTA)
    assert reservation.ends_at == checkout
    assert reservation.status == "PAYMENT_PENDING"
    assert harness.calendar.created_event_ids == []


async def test_R_refugio_before_checkin_asks_time(harness: Harness) -> None:
    require_overnight_columns()
    await seed_booking(harness, code="REFUGIO_DOS", starts_at=START.replace(hour=13))
    await harness.send("17 de noviembre 1 pm")
    await harness.assert_completed()
    assert harness.codes == [code("TIME")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_TIME"
    assert await harness.rows(Reservation) == []


def test_V_non_overnight_still_rejects_crossing_midnight() -> None:
    start = START.replace(hour=22, minute=30)
    result = validate_booking_window(
        start,
        start + timedelta(hours=3),
        settings(BOOKING_LATEST_START="23:00", BOOKING_HOURS_END="24:00"),
        today=START.date() - timedelta(days=1),
    )
    assert (result.ok, result.reason) == (False, "CROSSES_MIDNIGHT")


def overnight_overlap(*, exclusive: bool, overnight: bool) -> BookingAvailability:
    saturday = START + timedelta(days=4)
    assert saturday.weekday() == 5
    sunday = (saturday + timedelta(days=1)).replace(hour=9)
    occupied = pure_plan(code="REFUGIO_DOS")
    occupied.overnight, occupied.checkin_from, occupied.checkout_time = True, time(15), time(11)
    reservation = Reservation(
        reservation_id=uuid4(),
        status="RESERVED",
        starts_at=saturday,
        ends_at=sunday.replace(hour=11),
    )
    reservation.plan = occupied
    candidate = pure_plan(code="CANDIDATE", exclusive=exclusive)
    candidate.overnight = overnight
    return evaluate_booking_availability(
        plan=candidate,
        starts_at=sunday,
        ends_at=sunday + timedelta(hours=3),
        calendar_events=[],
        reservations=[reservation],
        exclusivity_keyword="exclusividad",
    )


@pytest.mark.parametrize("exclusive,overnight", [(True, False), (False, True)])
def test_R_reserved_overnight_blocks_exclusive_or_overnight(
    exclusive: bool, overnight: bool
) -> None:
    result = overnight_overlap(exclusive=exclusive, overnight=overnight)
    assert result.available is False
    assert [blocker.kind for blocker in result.blockers] == ["RESERVED_OVERNIGHT"]


def test_V_reserved_overnight_does_not_block_shared_plan() -> None:
    result = overnight_overlap(exclusive=False, overnight=False)
    assert result.available is True
    assert result.blockers == []


async def test_R_calendar_receives_real_overnight_end(harness: Harness) -> None:
    require_overnight_columns()
    await seed_booking(harness, code="REFUGIO_DOS")
    reservation = await create_overnight_request(harness)
    async with harness.db.begin() as session:
        row = await session.get(Reservation, reservation.reservation_id)
        # Synthetic human-confirmed fixture, not a bot confirmation.
        row.status, row.amount_paid_cop = "RESERVED", row.price_cop
    await sync_reservation_calendar(
        reservation.reservation_id,
        calendar=harness.calendar,
        sessionmaker=harness.db,
        settings=get_settings(),
    )
    external = await harness.calendar.get_event(reservation.reservation_id.hex)
    assert external.start == START
    assert external.end == datetime.combine(
        START.date() + timedelta(days=1), time(11), tzinfo=BOGOTA
    )


async def test_R_agenda_fetch_uses_real_checkout(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_overnight_columns()
    plan = await seed_booking(harness, code="REFUGIO_DOS")
    queries = []
    original = harness.calendar.list_events

    async def observe(*args: Any, **kwargs: Any) -> Any:
        queries.append((args, kwargs))
        return await original(*args, **kwargs)

    monkeypatch.setattr(harness.calendar, "list_events", observe)
    result = await BookingAgendaService(harness.db, get_settings()).booking_availability(
        plan.plan_id, START, plan.duration_minutes
    )
    assert result.available
    assert len(queries) == 1
    assert queries[0][0][1] == datetime.combine(
        START.date() + timedelta(days=1), time(11), tzinfo=BOGOTA
    )


async def test_R_overnight_check_rejects_missing_hours(harness: Harness) -> None:
    require_overnight_columns()
    error = None
    try:
        async with harness.db.begin() as session:
            plan = await session.scalar(select(Plan).where(Plan.code == "REFUGIO_DOS"))
            plan.overnight, plan.checkin_from, plan.checkout_time = True, None, None
            await session.flush()
    except IntegrityError as exc:
        error = exc
    assert error is not None, "PostgreSQL debe rechazar overnight sin sus dos horas"
    assert error.orig.sqlstate == "23514"
