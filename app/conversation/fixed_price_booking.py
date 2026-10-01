"""Pure recognition of a new fixed-price booking request, outside pending flows."""

from __future__ import annotations

import re

from app.conversation.catalog_event_type import (
    FIXED_PRICE_EVENT_TYPES,
    normalize_catalog_event_type_label,
)

FIXED_PRICE_BOOKING_REASON = "FIXED_PRICE_BOOKING_REQUEST"
SELF_SERVICE_BOOKING_REASON = "SELF_SERVICE_BOOKING"
BOOKING_ACTIONS = frozenset({
    "SELECT_BOOKING_PLAN", "SELECT_BOOKING_DATETIME", "SELECT_BOOKING_TIME", "CONFIRM_BOOKING",
})
BOOKING_EXPRESSIONS = frozenset({
    "agendar", "reservar", "separar", "apartar", "programar", "cuadrar", "quiero la fecha",
})
VISIT_EXPRESSIONS = frozenset({"visita", "visitar", "conocer el lugar", "ir a ver"})


def _phrase_pattern(expressions: frozenset[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(item) for item in sorted(expressions)) + r")\b")


_BOOKING_PATTERN = _phrase_pattern(BOOKING_EXPRESSIONS)
_VISIT_PATTERN = _phrase_pattern(VISIT_EXPRESSIONS)


def booking_guard_eligible(
    state: str | None, pending_action: str | None, bot_enabled: bool,
) -> bool:
    return (
        bot_enabled and pending_action is None
        and state in {"BOT_ACTIVE", "ANSWERING_INFORMATION"}
    )


def is_fixed_price_booking(message_text: str, event_type: str | None) -> bool:
    if event_type not in FIXED_PRICE_EVENT_TYPES:
        return False
    normalized = normalize_catalog_event_type_label(message_text)
    return bool(_BOOKING_PATTERN.search(normalized) and not _VISIT_PATTERN.search(normalized))
