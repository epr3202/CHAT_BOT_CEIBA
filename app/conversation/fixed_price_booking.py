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
BOOKING_ACTIONS = frozenset({
    "SELECT_BOOKING_PLAN", "SELECT_BOOKING_DATETIME", "SELECT_BOOKING_TIME", "CONFIRM_BOOKING",
})
BOOKING_EXPRESSIONS = frozenset({
    "agendar", "reservar", "separar", "apartar", "programar", "cuadrar", "quiero la fecha",
})
VISIT_EXPRESSIONS = frozenset({"visita", "visitar", "conocer el lugar", "ir a ver"})
GENERIC_CAPTURE_ACTIONS = frozenset({
    "COLLECT_EVENT_TYPE", "COLLECT_GUEST_COUNT", "COLLECT_EVENT_DATE",
    "COLLECT_CUSTOMER_NAME", "COLLECT_BUDGET", "COLLECT_SERVICES",
})


def _phrase_pattern(expressions: frozenset[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(item) for item in sorted(expressions)) + r")\b")


_BOOKING_PATTERN = _phrase_pattern(BOOKING_EXPRESSIONS)
_VISIT_PATTERN = _phrase_pattern(VISIT_EXPRESSIONS)


def booking_guard_eligible(
    state: str | None, pending_action: str | None, bot_enabled: bool,
    *, self_service: bool = False,
) -> bool:
    return (
        bot_enabled and (
            pending_action is None and state in {"BOT_ACTIVE", "ANSWERING_INFORMATION"}
            or self_service and state == "NEW" and pending_action is None
            or self_service and state == "COLLECTING_EVENT_DATA"
            and pending_action in GENERIC_CAPTURE_ACTIONS | {None}
        )
    )


def is_fixed_price_booking(message_text: str, event_type: str | None) -> bool:
    if event_type not in FIXED_PRICE_EVENT_TYPES:
        return False
    normalized = normalize_catalog_event_type_label(message_text)
    return bool(_BOOKING_PATTERN.search(normalized) and not _VISIT_PATTERN.search(normalized))


def _within_one_edit(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    i = j = errors = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i, j = i + 1, j + 1
        else:
            errors += 1
            if errors > 1:
                return False
            if len(left) == len(right):
                i += 1
            j += 1
    return errors + (len(right) - j) <= 1


def match_booking_plan(message_text: str, plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Unique active name within a phrase, accents/case normalized and at most one edit.

    Names come from the server's active catalog. Ambiguous names and visit requests
    leave the existing classifier/selection flow in control.
    """
    normalized = normalize_catalog_event_type_label(message_text)
    if _VISIT_PATTERN.search(normalized):
        return None
    words = re.findall(r"\w+", normalized)
    exact, tolerant = [], []
    for plan in plans:
        name = " ".join(re.findall(r"\w+", normalize_catalog_event_type_label(plan["name"])))
        size = len(name.split())
        candidates = {
            " ".join(words[start:start + count])
            for count in {max(1, size - 1), size, size + 1}
            for start in range(len(words) - count + 1)
        }
        if name in candidates:
            exact.append(plan)
        elif len(name) >= 8 and any(_within_one_edit(name, value) for value in candidates):
            tolerant.append(plan)
    matches = exact or tolerant
    return matches[0] if len(matches) == 1 else None
