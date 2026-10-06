from datetime import date, time

import pytest

from app.appointment.service import parse_visit_time_text, resolve_visit_date_text
from app.orchestrator.booking_flow import consume_date_time
from tests.booking_backend.helpers import settings


@pytest.mark.parametrize(
    "text,today,expected",
    [
        ("el 14", date(2026, 10, 5), date(2026, 10, 14)),
        ("día 14", date(2026, 10, 5), date(2026, 10, 14)),
        ("Me gustaría agendar para el 14", date(2026, 10, 5), date(2026, 10, 14)),
        ("el 14", date(2026, 10, 14), date(2026, 10, 14)),
        ("el 14", date(2026, 10, 22), date(2026, 11, 14)),
        ("el 14", date(2026, 12, 22), date(2027, 1, 14)),
        ("el 31", date(2026, 2, 22), date(2026, 3, 31)),
        ("el 29", date(2028, 2, 28), date(2028, 2, 29)),
    ],
)
def test_r3_day_without_month_requires_absolute_confirmation(
    text: str, today: date, expected: date
) -> None:
    result = resolve_visit_date_text(text, today=today, require_absolute_confirmation=True)
    assert result.resolved_date == expected
    assert result.needs_confirmation is True


@pytest.mark.parametrize("text", ["el 0", "el 32", "el 99", "el 31 de febrero"])
def test_r3_invalid_day_does_not_become_a_candidate(text: str) -> None:
    result = resolve_visit_date_text(
        text, today=date(2026, 10, 5), require_absolute_confirmation=True
    )
    assert result.resolved_date is None


@pytest.mark.parametrize("text", ["8", "somos 14"])
def test_r3_bare_clock_or_attendee_count_is_not_a_day(text: str) -> None:
    result = resolve_visit_date_text(
        text, today=date(2026, 10, 5), require_absolute_confirmation=True
    )
    assert result.resolved_date is None


@pytest.mark.parametrize("text,expected", [("el 14", None), ("el 14 a las 7 pm", time(19))])
def test_r3_day_without_month_stays_separate_from_clock(text: str, expected: time | None) -> None:
    assert parse_visit_time_text(text, require_explicit=True) == expected


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 10, 5), date(2026, 10, 14)),
        (date(2026, 10, 22), date(2026, 11, 14)),
        (date(2026, 12, 22), date(2027, 1, 14)),
    ],
)
def test_r3_booking_consumes_day_without_month_and_keeps_clock(today: date, expected: date) -> None:
    draft: dict[str, object] = {}
    assert consume_date_time(draft, "el 14 a las 7 pm", today, settings=settings())
    assert draft.get("date") == expected.isoformat()
    assert draft.get("date_confirmation") is True
    assert draft.get("time") == "19:00"
