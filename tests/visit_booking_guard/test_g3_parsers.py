from __future__ import annotations

from datetime import date, time

import pytest

from app.appointment.service import (
    resolve_visit_date_text,
)
from tests.visit_booking_guard.helpers import TODAY


def test_g3_e_conflicting_weekday_preserves_absolute_date() -> None:
    result = resolve_visit_date_text(
        "lunes 7 de octubre",
        today=TODAY,
        require_absolute_confirmation=True,
    )
    assert result.needs_confirmation is True
    assert result.resolved_date == date(2026, 10, 7), (
        "Do not silently replace the explicit October 7 with Monday October 5"
    )


def test_g3_e_next_occurrence_includes_leap_day() -> None:
    result = resolve_visit_date_text("29 de febrero", today=TODAY,
                                     require_absolute_confirmation=True)
    assert result.resolved_date == date(2028, 2, 29)


@pytest.mark.parametrize("message", ["miércoles 31 de febrero", "miércoles 7 de octubre de 2023"])
def test_g3_e_invalid_absolute_date_never_becomes_relative(message: str) -> None:
    result = resolve_visit_date_text(message, today=TODAY, require_absolute_confirmation=True)
    assert result.resolved_date is None
    assert result.interpretation == "NO_INTERPRETABLE"


@pytest.mark.parametrize("message,expected", [
    ("el 8", None), ("día 9", None), ("el 7/10", None), ("8 de octubre", None),
    ("el 8 a las 9", time(9)), ("día 9, 10 am", time(10)),
    ("el 7/10 a las 9", time(9)), ("7 de octubre, 09:00", time(9)),
    ("7 de octubre, 9 de la mañana", time(9)), ("9 de la noche", time(21)),
    ("8 de octubre a las 9 pm", time(21)), ("8 de octubre, 8 am", time(8)),
])
def test_g3_d_time_parser_discards_day_numbers(message: str, expected: time | None) -> None:
    import app.appointment.service as service

    parser = getattr(service, "parse_visit_time_text", None)
    assert callable(parser), "G3-D requires a pure time parser beside the visit date parser"
    assert parser(message, require_explicit=False) == expected
