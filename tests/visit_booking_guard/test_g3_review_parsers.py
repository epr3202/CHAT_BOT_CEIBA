from __future__ import annotations

import inspect
from datetime import date, time

import pytest

from app.appointment.service import parse_visit_time_text, resolve_visit_date_text
from app.conversation.presentation import present_variables
from tests.visit_booking_guard.helpers import TODAY


@pytest.mark.parametrize("message,expected", [
    ("8", None), ("somos 10", None), ("ocho", None), ("el 8", None),
    ("quiero visitar el 7 de octubre, somos 10", None),
    ("a las 8", time(8)), ("8 am", time(8)), ("08:00", time(8)),
    ("8 de la mañana", time(8)), ("8 de la tarde", time(20)),
    ("8 de la noche", time(20)), ("8 pm", time(20)),
    ("7 de octubre, somos 10, a las 9", time(9)),
])
def test_g3_c1_date_context_requires_an_explicit_clock(
    message: str, expected: time | None,
) -> None:
    assert "require_explicit" in inspect.signature(parse_visit_time_text).parameters
    assert parse_visit_time_text(message, require_explicit=True) == expected


def test_g3_c1_time_context_accepts_bare_hour() -> None:
    assert "require_explicit" in inspect.signature(parse_visit_time_text).parameters
    assert parse_visit_time_text("8", require_explicit=False) == time(8)


@pytest.mark.parametrize("response_code", [None, "RESP-CATALOG-001", "RESP-VISIT-CONFIRM-001"])
def test_g3_c2_free_reason_is_scoped_to_visit_confirmation(response_code: str | None) -> None:
    expected = "conocer el salón" if response_code == "RESP-VISIT-CONFIRM-001" else "tu celebración"
    assert present_variables({"event_type": "conocer el salón"}, response_code=response_code) == {
        "event_type": expected,
    }
    assert present_variables({"event_type": "WEDDING"}, response_code=response_code) == {
        "event_type": "una boda",
    }


@pytest.mark.parametrize("message,raw,expected", [
    ("quiero reservar para mañana", "mañana", date(2026, 9, 30)),
    ("reservar pasado mañana", "pasado mañana", date(2026, 10, 1)),
    ("reservar hoy", "hoy", TODAY),
    ("  reservar el MIÉRCOLES  ", "el MIÉRCOLES", date(2026, 9, 30)),
    ("reservar próximo sábado", "próximo sábado", date(2026, 10, 3)),
    ("reservar el sa\u0301bado", "el sa\u0301bado", date(2026, 10, 3)),
])
def test_g3_c3_relative_expression_preserves_spelling_and_date_rules(
    message: str, raw: str, expected: date,
) -> None:
    result = resolve_visit_date_text(message, today=TODAY, require_absolute_confirmation=True)
    assert result.matched_text == raw
    assert result.resolved_date == expected
    assert result.interpretation == "RELATIVA" and result.needs_confirmation is True
