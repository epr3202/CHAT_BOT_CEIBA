from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from logging import getLogger
from typing import Any

from app.conversation.catalog_event_type import (
    CATALOG_EVENT_TYPE_LABELS,
    normalize_catalog_event_type_label,
)
from app.event.models import EVENT_TYPES

logger = getLogger(__name__)

MONTH_NAMES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

EVENT_TYPE_LABELS = {
    "WEDDING": "una boda",
    "CIVIL_WEDDING": "una boda civil",
    "PROPOSAL": "una propuesta de matrimonio",
    "BIRTHDAY": "un cumpleaños",
    "GRADUATION": "una graduación",
    "ANNIVERSARY": "un aniversario",
    "ROMANTIC_DINNER": "una cena romántica",
    "CORPORATE_EVENT": "un evento empresarial",
    "FAMILY_EVENT": "un evento familiar",
    "BAPTISM": "un bautizo",
    "FIRST_COMMUNION": "una primera comunión",
    "BABY_SHOWER": "un baby shower",
    "WORKSHOP": "un taller",
    "POOL_DAY": "un día de piscina",
    "PRIVATE_DINNER": "una cena privada",
    "GENDER_REVEAL": "una revelación de género",
    "OTHER": "una celebración",
}


def format_event_type(event_type: str | None) -> str:
    if event_type is None:
        return "tu celebración"
    if event_type not in EVENT_TYPES or event_type not in EVENT_TYPE_LABELS:
        raise ValueError(f"Missing presentation label for event_type: {event_type}")
    return EVENT_TYPE_LABELS[event_type]


def format_date_natural(value: date) -> str:
    return f"{value.day} de {MONTH_NAMES[value.month]} de {value.year}"


def format_month_natural(value: str) -> str:
    year, month = value.split("-", maxsplit=1)
    return f"{MONTH_NAMES[int(month)]} de {year}"


class VariablePresentationError(ValueError):
    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"Cannot present template variable: {variable}")


VariablePresenter = Callable[[Any], str]


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected text")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("Empty text")
    return normalized


def _normalized_lower_text(value: Any) -> str:
    return _normalized_text(value).casefold()


def _present_count(value: Any) -> str:
    if isinstance(value, bool):
        raise TypeError("Boolean is not a count")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("Negative count")
        return str(value)
    normalized = _normalized_text(value)
    if not normalized.isdecimal():
        raise ValueError("Invalid count")
    return normalized


def _present_date(value: Any) -> str:
    if isinstance(value, date):
        return format_date_natural(value)
    normalized = _normalized_text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        return format_date_natural(date.fromisoformat(normalized))
    return normalized


def _present_month(value: Any) -> str:
    normalized = _normalized_text(value)
    if re.fullmatch(r"\d{4}-\d{2}", normalized):
        return format_month_natural(normalized)
    return normalized


def _present_requested_services_summary(value: Any) -> str:
    normalized = _normalized_lower_text(value)
    for prefix in ("solo ", "solamente "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if not normalized:
        raise ValueError("Empty requested services summary")
    return normalized


_MISSING_FIELD_LABELS = {
    "event_type": "el tipo de evento",
    "guest_count": "la cantidad de invitados",
    "event_date": "la fecha del evento",
    "requested_services": "los servicios que deseas incluir",
    "quote_confirmation": "la confirmación de la solicitud",
}

_PENDING_TOPIC_LABELS = {
    "requested_services": "los servicios",
    "COLLECT_SERVICES": "los servicios",
}


def _present_closed_label(value: Any, labels: dict[str, str]) -> str:
    normalized = _normalized_text(value)
    try:
        return labels[normalized]
    except KeyError as error:
        if normalized in labels.values():
            return normalized
        raise ValueError("Unknown internal label") from error


_EVENT_TYPE_BY_NORMALIZED_VALUE = {
    normalize_catalog_event_type_label(candidate): event_type
    for event_type in EVENT_TYPES
    for candidate in (
        event_type,
        *CATALOG_EVENT_TYPE_LABELS[event_type],
        EVENT_TYPE_LABELS[event_type],
    )
}


def _present_event_type(value: Any) -> str:
    if value is None:
        return format_event_type(None)
    raw_value = str(value)
    normalized = normalize_catalog_event_type_label(raw_value)
    event_type = _EVENT_TYPE_BY_NORMALIZED_VALUE.get(normalized)
    if event_type is not None:
        return format_event_type(event_type)
    logger.warning(
        "event_type_presentation_fallback discarded_value=%r",
        raw_value,
        extra={
            "event": "event_type_presentation_fallback",
            "discarded_value": raw_value,
        },
    )
    return format_event_type(None)


VARIABLE_PRESENTERS: dict[str, VariablePresenter] = {
    "adult_guest_count": _present_count,
    "advisor_name": _normalized_text,
    "appointment_options": _normalized_text,
    "approved_price": _normalized_text,
    "child_guest_count": _present_count,
    "customer_name": _normalized_text,
    "email": _normalized_text,
    "event_date": _present_date,
    "event_month": _present_month,
    "event_type": _present_event_type,
    "guest_count": _present_count,
    "guest_count_range": _normalized_text,
    "map_url": _normalized_text,
    "missing_field": lambda value: _present_closed_label(value, _MISSING_FIELD_LABELS),
    "new_visit_date": _present_date,
    "new_visit_time": _normalized_text,
    "package_name": _normalized_text,
    "pending_topic": lambda value: _present_closed_label(value, _PENDING_TOPIC_LABELS),
    "rejection_reason_customer_safe": _normalized_text,
    "requested_services_summary": _present_requested_services_summary,
    "resolved_date": _present_date,
    "service_name": _normalized_lower_text,
    "total_guest_count": _present_count,
    "visit_attendee_count": _present_count,
    "visit_date": _present_date,
    "visit_time": _normalized_text,
}


def present_variables(variables: dict[str, Any]) -> dict[str, str]:
    presented: dict[str, str] = {}
    for variable, value in variables.items():
        presenter = VARIABLE_PRESENTERS.get(variable)
        if presenter is None:
            raise VariablePresentationError(variable)
        try:
            presented[variable] = presenter(value)
        except VariablePresentationError:
            raise
        except (TypeError, ValueError) as error:
            raise VariablePresentationError(variable) from error
    return presented
