from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.reservation.models import Reservation
from tests.booking_backend.helpers import BOGOTA, START, plan, settings, symbol

MODULE = "app.reservation.availability"


@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "calendar_plain",
        "calendar_summary",
        "calendar_description",
        "reserved_exclusive",
        "reserved_shared",
        "pending",
        "review",
        "expired",
        "cancelled",
        "calendar_edge",
        "reservation_edge",
    ],
)
def test_r1_d3_matrix(exclusive: bool, case: str) -> None:
    evaluate = symbol(MODULE, "evaluate_booking_availability")
    event_cls = symbol("app.calendar.adapter", "CalendarEvent")
    events, reservations = [], []
    expected = []
    if case.startswith("calendar"):
        end = START if case == "calendar_edge" else START + timedelta(hours=1)
        events.append(
            event_cls(
                event_id="ext",
                calendar_id="a",
                summary="exclusividad" if case != "calendar_plain" else "Visita",
                description=None,
                start=START - timedelta(hours=1),
                end=end,
            )
        )
        if case == "calendar_description":
            events = [
                event_cls(
                    event_id="ext",
                    calendar_id="a",
                    summary="Cena",
                    description="Con EXCLUSÍVIDAD",
                    start=START,
                    end=end,
                )
            ]
        if case in {"calendar_summary", "calendar_description"}:
            expected = [("CALENDAR_EXCLUSIVE", "ext")]
    elif case != "empty":
        status = {
            "pending": "PAYMENT_PENDING",
            "review": "PAYMENT_REVIEW",
            "expired": "EXPIRED",
            "cancelled": "CANCELLED",
        }.get(case, "RESERVED")
        row = Reservation(
            reservation_id=uuid4(),
            status=status,
            starts_at=START - timedelta(hours=1),
            ends_at=START if case == "reservation_edge" else START + timedelta(hours=1),
        )
        row.plan = plan(exclusive=case != "reserved_shared")
        reservations.append(row)
        if case == "reserved_exclusive":
            expected = [("RESERVED_EXCLUSIVE", str(row.reservation_id))]
        elif case == "reserved_shared" and exclusive:
            expected = [("RESERVED_CONFLICT", str(row.reservation_id))]
    result = evaluate(
        plan=plan(exclusive=exclusive),
        starts_at=START,
        ends_at=START + timedelta(hours=3),
        calendar_events=events,
        reservations=reservations,
        exclusivity_keyword=" Exclusividad ",
    )
    assert result.available is (not expected)
    assert [(b.kind, b.ref) for b in result.blockers] == expected


@pytest.mark.parametrize(
    "start,end,today,reason",
    [
        (START, START + timedelta(hours=9), date(2030, 10, 9), None),
        (
            START - timedelta(minutes=1),
            START + timedelta(hours=3),
            date(2030, 10, 9),
            "OUTSIDE_HOURS",
        ),
        (START, START + timedelta(hours=9, minutes=1), date(2030, 10, 9), None),
        (
            START + timedelta(hours=8),
            START + timedelta(hours=13),
            date(2030, 10, 9),
            "CROSSES_MIDNIGHT",
        ),
        (START, START + timedelta(hours=3), date(2030, 10, 10), "MIN_LEAD_DAYS"),
        (START, START, date(2030, 10, 9), "INVALID_RANGE"),
        (
            datetime(2030, 10, 11, 0, tzinfo=UTC),
            datetime(2030, 10, 11, 2, tzinfo=UTC),
            date(2030, 10, 9),
            None,
        ),
        (
            datetime(2030, 10, 11, 0, tzinfo=UTC),
            datetime(2030, 10, 11, 2, tzinfo=UTC),
            date(2030, 10, 10),
            "MIN_LEAD_DAYS",
        ),
    ],
)
def test_r2_window(start: datetime, end: datetime, today: date, reason: str | None) -> None:
    validate = symbol(MODULE, "validate_booking_window")
    result = validate(start, end, settings(), today=today)
    assert (result.ok, result.reason) == (reason is None, reason)


def test_r2_default_clock_uses_bogota(monkeypatch: pytest.MonkeyPatch) -> None:
    validate = symbol(MODULE, "validate_booking_window")

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2030, 10, 10, 2, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(MODULE + ".datetime", Clock)
    assert validate(START, START + timedelta(hours=3), settings()).ok
    assert START.astimezone(BOGOTA).date() == date(2030, 10, 10)


@pytest.mark.parametrize("confirmed_schedule", [False, True])
def test_extra_request_does_not_set_calendar_exclusivity(confirmed_schedule: bool) -> None:
    from app.calendar.adapter import CalendarEvent
    from app.reservation.availability import evaluate_booking_availability

    selected = plan()
    from app.reservation.calendar_description import reservation_calendar_description

    snapshot = (
        "Datos informados por el cliente:\nFecha deseada: 99 de enero\n"
        "Adicional por cotizar: consultar exclusividad"
    )
    row = Reservation(
        reservation_id=uuid4(),
        status="RESERVED",
        starts_at=START,
        ends_at=START + timedelta(hours=3),
        commercial_details=snapshot,
    )
    row.plan = selected
    row.external_calendar_id = row.reservation_id.hex
    description = f"{snapshot}\nreservation_id: {row.reservation_id}"
    if confirmed_schedule:
        description = reservation_calendar_description(description, START, row.ends_at)
    event = CalendarEvent(
        row.external_calendar_id,
        "a",
        selected.name,
        description,
        START,
        row.ends_at,
    )
    check = evaluate_booking_availability(
        plan=selected,
        starts_at=START,
        ends_at=row.ends_at,
        calendar_events=[event],
        reservations=[row],
        exclusivity_keyword="exclusividad",
    )
    assert check.available and not check.blockers
