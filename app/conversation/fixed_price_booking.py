"""Pure recognition of a new fixed-price booking request, outside pending flows."""

from __future__ import annotations

import re
from typing import Any

from app.conversation.catalog_event_type import (
    FIXED_PRICE_EVENT_TYPES,
    normalize_catalog_event_type_label,
)

FIXED_PRICE_BOOKING_REASON = "FIXED_PRICE_BOOKING_REQUEST"
SELF_SERVICE_BOOKING_REASON = "SELF_SERVICE_BOOKING"
FIXED_PRICE_INFORMATION_CODES = {
    "PROPOSAL": "RESP-EVENTS-PROPOSAL-001",
    "ROMANTIC_DINNER": "RESP-EVENTS-ROMANTIC-001",
}
# An informational interruption is not an answer to the catalog's plan invitation.
_PLAN_INFORMATION_WORDS = frozenset(
    {
        "catalogo", "catalogos", "pdf", "brochure", "ubicacion", "mapa", "horario", "horarios",
        "parqueadero", "capacidad", "piscina", "mascotas", "proveedores", "alimentos",
        "bebidas", "licor", "descorche", "alojamiento", "pago", "pagos", "pagar",
        "comprobante", "cancelar", "cancelacion", "devolucion", "descuento", "queja",
        "emergencia", "ayuda", "informacion", "informarme",
        "espacios", "identidad", "seguridad", "servicios", "visitas", "respuesta",
        "precio", "precios", "valor", "cuesta", "tarjetas", "transferencia",
        "hola", "gracias", "adios",
    }
)
BOOKING_ACTIONS = frozenset(
    {
        "SELECT_BOOKING_PLAN",
        "SELECT_BOOKING_DATETIME",
        "SELECT_BOOKING_TIME",
        "CONFIRM_BOOKING",
        "COLLECT_BOOKING_NAME",
    }
)
BOOKING_EXPRESSIONS = frozenset(
    {
        "agendar",
        "reservar",
        "separar",
        "apartar",
        "programar",
        "cuadrar",
        "quiero la fecha",
    }
)
VISIT_EXPRESSIONS = frozenset({"visita", "visitar", "conocer el lugar", "ir a ver"})
_PLAN_STOP_WORDS = frozenset(
    {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "y",
        "para",
        "entre",
        "un",
        "una",
    }
)
GENERIC_CAPTURE_ACTIONS = frozenset(
    {
        "COLLECT_EVENT_TYPE",
        "COLLECT_GUEST_COUNT",
        "COLLECT_EVENT_DATE",
        "COLLECT_CUSTOMER_NAME",
        "COLLECT_BUDGET",
        "COLLECT_SERVICES",
    }
)


def _phrase_pattern(expressions: frozenset[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(item) for item in sorted(expressions)) + r")\b")


_BOOKING_PATTERN = _phrase_pattern(BOOKING_EXPRESSIONS)
_VISIT_PATTERN = _phrase_pattern(VISIT_EXPRESSIONS)


def booking_guard_eligible(
    state: str | None,
    pending_action: str | None,
    bot_enabled: bool,
    *,
    self_service: bool = False,
) -> bool:
    return bot_enabled and (
        pending_action is None
        and state in {"BOT_ACTIVE", "ANSWERING_INFORMATION"}
        or self_service
        and state == "NEW"
        and pending_action is None
        or self_service
        and state == "COLLECTING_EVENT_DATA"
        and pending_action in GENERIC_CAPTURE_ACTIONS | {None}
    )


def is_explicit_visit_request(message_text: str) -> bool:
    normalized = normalize_catalog_event_type_label(message_text)
    return bool(_VISIT_PATTERN.search(normalized))


def is_fixed_price_catalog_followup(event_type: str | None, last_question_code: str | None) -> bool:
    return (
        event_type in FIXED_PRICE_INFORMATION_CODES
        and last_question_code == FIXED_PRICE_INFORMATION_CODES[event_type]
    )


def is_catalog_plan_choice(message_text: str, *, has_date: bool = False) -> bool:
    """Keep unknown plan replies in selection while preserving explicit information requests."""
    normalized = normalize_catalog_event_type_label(message_text)
    words = set(re.findall(r"\w+", normalized))
    information_question = re.match(
        r"^(?:(?:y|pero)\s+)?(?:donde|como|cuanto|cuando|cual|que|por que)\b", normalized
    )
    explicit_choice = re.match(r"^(?:me interesa|quiero|el de)\b", normalized)
    return (
        bool(words)
        and not words.intersection(_PLAN_INFORMATION_WORDS)
        and not information_question
        and (not has_date or bool(explicit_choice))
    )


def is_fixed_price_booking(message_text: str, event_type: str | None) -> bool:
    if event_type not in FIXED_PRICE_EVENT_TYPES:
        return False
    normalized = normalize_catalog_event_type_label(message_text)
    return bool(_BOOKING_PATTERN.search(normalized) and not is_explicit_visit_request(message_text))


def _within_edit_distance(left: str, right: str, max_edits: int) -> bool:
    if max_edits == 0 or left == right:
        return left == right
    if abs(len(left) - len(right)) > max_edits:
        return False
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_character in enumerate(right, start=1):
        current = [row]
        for column, left_character in enumerate(left, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_character != right_character),
                )
            )
        if min(current) > max_edits:
            return False
        previous = current
    return previous[-1] <= max_edits


def match_booking_plan(message_text: str, plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match every significant name word, in any order, with a per-word edit budget.

    Normalized plan words allow two edits at six or more letters, one at four or
    five, and none at three or fewer. Names come from the server's active catalog;
    multiple matches and visit requests leave the existing selection flow in control.
    """
    normalized = normalize_catalog_event_type_label(message_text)
    if is_explicit_visit_request(message_text):
        return None
    words = set(re.findall(r"\w+", normalized))
    matches = []
    for plan in plans:
        significant_words = [
            word
            for word in re.findall(
                r"\w+",
                normalize_catalog_event_type_label(plan["name"]),
            )
            if word not in _PLAN_STOP_WORDS
        ]
        if not significant_words:
            continue
        for word in significant_words:
            max_edits = 2 if len(word) >= 6 else 1 if len(word) >= 4 else 0
            if not any(_within_edit_distance(word, candidate, max_edits) for candidate in words):
                break
        else:
            matches.append(plan)
    return matches[0] if len(matches) == 1 else None
