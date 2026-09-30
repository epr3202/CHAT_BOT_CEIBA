from __future__ import annotations

from datetime import date, time

import pytest
from structlog.testing import capture_logs

from app.appointment.service import (
    build_visit_description,
    interpret_visit_time,
    resolve_visit_date_text,
)
from app.conversation.presentation import EVENT_TYPE_LABELS
from app.event.models import EVENT_TYPES
from tests.visit_booking_guard.helpers import BOOK_ABSOLUTE, DATE_TIME, SLOTS, TIME_ONLY, TODAY


@pytest.mark.parametrize(
    ("message", "today", "expected", "interpretation", "confirmation"),
    [
        (BOOK_ABSOLUTE, TODAY, date(2026, 10, 7), "EXACTA", False),
        ("el miércoles", TODAY, date(2026, 9, 30), "RELATIVA", True),
        ("7 de octubre", date(2026, 10, 8), date(2027, 10, 7), "EXACTA", False),
        ("7 de octubre", date(2026, 10, 7), date(2026, 10, 7), "EXACTA", False),
        ("7 de octubre a las 9 de la mañana", TODAY, date(2026, 10, 7), "EXACTA", False),
    ],
    ids=[
        "r2b-incident-absolute",
        "r2b-relative-control",
        "d2-next-year",
        "d2-today",
        "d2-morning-is-not-tomorrow",
    ],
)
def test_r2b_date_resolution(
    message: str,
    today: date,
    expected: date,
    interpretation: str,
    confirmation: bool,
) -> None:
    result = resolve_visit_date_text(message, today=today, require_absolute_confirmation=True)
    assert (result.resolved_date, result.interpretation, result.needs_confirmation) == (
        expected,
        interpretation,
        confirmation,
    )


def test_r2b_conflicting_weekday_does_not_choose_a_different_day() -> None:
    result = resolve_visit_date_text(
        "lunes 7 de octubre",
        today=TODAY,
        require_absolute_confirmation=True,
    )
    assert result.needs_confirmation is True
    assert result.resolved_date in {None, date(2026, 10, 7)}, (
        "Do not silently replace the explicit October 7 with Monday October 5"
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("8", time(8)),
        ("8 am", time(8)),
        ("8:00", time(8)),
        (TIME_ONLY, time(8)),
        ("a las 9", time(9)),
        ("9 de la mañana", time(9)),
        (DATE_TIME, time(8)),
        ("el 7/10 a las 9", time(9)),
        ("8 de octubre a las 11", time(11)),
    ],
    ids=[
        "bare",
        "am",
        "colon",
        "incident-0800",
        "a-las",
        "morning",
        "incident-date-time",
        "numeric-date-time",
        "day-is-not-hour",
    ],
)
def test_r3b_time_parser_accepts_clock_not_day(message: str, expected: time) -> None:
    result = interpret_visit_time(message, SLOTS)
    assert (result.accepted, result.preferred_visit_time, result.interpretation) == (
        True,
        expected,
        "OFFERED_SLOT",
    )


@pytest.mark.parametrize("message", [BOOK_ABSOLUTE, "7 de octubre", "8 de octubre", "el 7/10"])
def test_r3b_date_alone_has_no_time(message: str) -> None:
    result = interpret_visit_time(message, SLOTS)
    assert (result.accepted, result.preferred_visit_time, result.interpretation) == (
        False,
        None,
        "NO_INTERPRETABLE",
    )


@pytest.mark.parametrize("message", ["8 pm", "7 de octubre a las 8 pm"])
def test_r3b_out_of_hours_is_preserved(message: str) -> None:
    result = interpret_visit_time(message, SLOTS)
    assert (result.accepted, result.preferred_visit_time, result.interpretation) == (
        False,
        time(20),
        "OUT_OF_HOURS",
    )
    assert result.response_code == "RESP-VISIT-TIME-002"


def test_r3b_unoffered_time_is_preserved() -> None:
    result = interpret_visit_time("08:00", [time(9)])
    assert result.accepted is False
    assert result.interpretation == "OUTSIDE_OFFER"
    assert result.response_code == "RESP-VISIT-TIME-004"


def description(event_type: str) -> str:
    return (
        build_visit_description(
            customer_name="Emerson",
            phone_number=None,
            event_type=event_type,
            event_guest_count=None,
            visit_attendee_count=3,
            visit_reason="si una boda",
        )
        or ""
    )


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_r5_calendar_label_parity_all_17_event_types(event_type: str) -> None:
    assert len(EVENT_TYPES) == 17
    assert set(EVENT_TYPE_LABELS) == set(EVENT_TYPES)
    lines = description(event_type).splitlines()
    type_lines = [
        line.removeprefix("Tipo de evento: ")
        for line in lines
        if line.startswith("Tipo de evento: ")
    ]
    assert len(type_lines) == 1
    label = type_lines[0]
    # Expected values are derived only from the user-designated source of truth.
    source = EVENT_TYPE_LABELS[event_type].split(" ", 1)[1]
    assert label == source[0].upper() + source[1:]
    assert label and label != event_type
    assert not label.casefold().startswith(("un ", "una ", "el ", "la ", "los ", "las "))


def test_r5_unknown_type_omits_raw_code_and_warns() -> None:
    with capture_logs() as logs:
        rendered = description("UNMAPPED_TYPE")
    assert "Tipo de evento:" not in rendered
    assert "UNMAPPED_TYPE" not in rendered
    assert "Motivo de la visita: si una boda" in rendered
    assert any(entry.get("log_level") == "warning" for entry in logs)


def test_r5_calendar_derives_label_from_presentation_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Detect a second hard-coded map even when it happens to contain the same 17 labels.
    monkeypatch.setitem(EVENT_TYPE_LABELS, "WEDDING", "una celebración de prueba")
    assert "Tipo de evento: Celebración de prueba" in description("WEDDING")
