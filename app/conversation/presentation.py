from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

import structlog

from app.config.settings import Settings
from app.conversation.catalog_event_type import (
    CATALOG_EVENT_TYPE_LABELS,
    normalize_catalog_event_type_label,
)
from app.conversation.services_catalog import compose_requested_services_summary
from app.event.models import EVENT_TYPES
from app.plan.models import Plan

logger = structlog.get_logger(__name__)

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


def event_type_display_name(event_type: str | None) -> str | None:
    if event_type is None:
        return None
    label = EVENT_TYPE_LABELS.get(event_type)
    if not label:
        logger.warning("unknown_event_type_display_name", event_type=event_type)
        return None
    label = re.sub(r"^(?:un|una|el|la|los|las)\s+", "", label.strip(), flags=re.IGNORECASE)
    return label[:1].upper() + label[1:]


def visit_reason_summary(visit_reason: str) -> str:
    """Recognize an affirmative event label for display without rewriting stored intent."""
    normalized = normalize_catalog_event_type_label(visit_reason)
    label = re.sub(
        r"^(?:si\b[,\s]*)?(?:es\s+)?(?:para\s+)?(?:(?:un|una)\s+)?",
        "",
        normalized,
    )
    for event_type, aliases in CATALOG_EVENT_TYPE_LABELS.items():
        if label in {normalize_catalog_event_type_label(alias) for alias in aliases}:
            return format_event_type(event_type)
    return visit_reason


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


def _present_cop(value: Any) -> str:
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer COP amount")
    return "$" + f"{value:,}".replace(",", ".")


def _present_plan_name(value: Any) -> str:
    if not isinstance(value, Plan):
        raise TypeError("Expected a plan loaded from the catalog")
    return _normalized_text(value.name)


def _present_plan_options(value: Any) -> str:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("Expected active catalog plans")
    if any(not isinstance(plan, Plan) or not plan.active for plan in value):
        raise TypeError("Expected active catalog plans")
    plans = sorted(value, key=lambda plan: (plan.sort_order, plan.code))
    return "\n".join(
        f"{index}. {_present_plan_name(plan)}" for index, plan in enumerate(plans, start=1)
    )


def _present_bank(value: Any, field: str) -> str:
    if not isinstance(value, Settings):
        raise TypeError("Expected bank settings, never customer text")
    return _normalized_text(getattr(value, field))


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


_MONTH_NUMBER_BY_NAME = {name: number for number, name in MONTH_NAMES.items()}
_MONTH_NAME_PATTERN = "|".join(re.escape(name) for name in MONTH_NAMES.values())
_NATURAL_DATE_PATTERN = re.compile(
    rf"(?P<day>[1-9]|[12]\d|3[01]) de "
    rf"(?P<month>{_MONTH_NAME_PATTERN}) de (?P<year>[1-9]\d{{0,3}})"
)
_NATURAL_MONTH_PATTERN = re.compile(rf"(?:{_MONTH_NAME_PATTERN}) de [1-9]\d{{0,3}}")
_EVENT_MONTH_PATTERN = re.compile(r"[1-9]\d{3}-(?:0[1-9]|1[0-2])")
_TIME_PATTERN = r"(?:[01]\d|2[0-3]):[0-5]\d"
_APPOINTMENT_OPTIONS_PATTERN = re.compile(
    rf"(?:{_TIME_PATTERN}|{_TIME_PATTERN}(?:, {_TIME_PATTERN})* y {_TIME_PATTERN})"
)
_GUEST_COUNT_RANGE_PATTERN = re.compile(r"entre (?:0|[1-9]\d*) y (?:0|[1-9]\d*)")


def _present_date(value: Any) -> str:
    if isinstance(value, date):
        return format_date_natural(value)
    if not isinstance(value, str):
        raise TypeError("Expected date or preformatted date text")
    matched = _NATURAL_DATE_PATTERN.fullmatch(value)
    if matched is None:
        raise ValueError("Invalid natural date format")
    parsed = date(
        int(matched.group("year")),
        _MONTH_NUMBER_BY_NAME[matched.group("month")],
        int(matched.group("day")),
    )
    if format_date_natural(parsed) != value:
        raise ValueError("Invalid natural date value")
    return value


def _present_month(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected event month text")
    if _EVENT_MONTH_PATTERN.fullmatch(value) is not None:
        return format_month_natural(value)
    if _NATURAL_MONTH_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid natural month format")
    return value


def _present_time(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(_TIME_PATTERN, value) is None:
        raise ValueError("Invalid time format")
    return value


def _present_appointment_options(value: Any) -> str:
    if not isinstance(value, str) or _APPOINTMENT_OPTIONS_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid appointment options format")
    return value


def _present_guest_count_range(value: Any) -> str:
    if not isinstance(value, str) or _GUEST_COUNT_RANGE_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid guest count range format")
    return value


def _present_requested_services_summary(value: Any) -> str:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        raise TypeError("Expected requested service codes or legacy values")
    return compose_requested_services_summary([str(item) for item in values])


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
        "event_type_presentation_fallback",
        discarded_value=raw_value,
    )
    return format_event_type(None)


VARIABLE_PRESENTERS: dict[str, VariablePresenter] = {
    "plan_options": _present_plan_options,
    "plan_name": _present_plan_name,
    "booking_date": _present_date,
    "booking_time": _present_time,
    "total_amount": _present_cop,
    "deposit_amount": _present_cop,
    "missing_amount": _present_cop,
    "balance_due_date": _present_date,
    "bank_name": lambda value: _present_bank(value, "booking_bank_name"),
    "account_type": lambda value: _present_bank(value, "booking_account_type"),
    "account_number": lambda value: _present_bank(value, "booking_account_number"),
    "account_holder": lambda value: _present_bank(value, "booking_account_holder"),
    "adult_guest_count": _present_count,
    "advisor_name": _normalized_text,
    "appointment_options": _present_appointment_options,
    "approved_price": _normalized_text,
    "child_guest_count": _present_count,
    "customer_name": _normalized_text,
    "email": _normalized_text,
    "event_date": _present_date,
    "event_month": _present_month,
    "event_type": _present_event_type,
    "guest_count": _present_count,
    "guest_count_range": _present_guest_count_range,
    "map_url": _normalized_text,
    "missing_field": lambda value: _present_closed_label(value, _MISSING_FIELD_LABELS),
    "new_visit_date": _present_date,
    "new_visit_time": _present_time,
    "package_name": _normalized_text,
    "pending_topic": lambda value: _present_closed_label(value, _PENDING_TOPIC_LABELS),
    "rejection_reason_customer_safe": _normalized_text,
    "requested_services_summary": _present_requested_services_summary,
    "resolved_date": _present_date,
    "service_name": _normalized_lower_text,
    "total_guest_count": _present_count,
    "visit_attendee_count": _present_count,
    "visit_date": _present_date,
    "visit_time": _present_time,
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
