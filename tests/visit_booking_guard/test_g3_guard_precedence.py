from __future__ import annotations

import pytest

from app.conversation.fixed_price_booking import BOOKING_EXPRESSIONS
from app.orchestrator.service import deterministic_booking_or_catalog_classification


def test_g3_c_booking_vocabulary_is_closed_and_immutable() -> None:
    assert isinstance(BOOKING_EXPRESSIONS, frozenset)
    assert BOOKING_EXPRESSIONS == {
        "agendar",
        "reservar",
        "separar",
        "apartar",
        "programar",
        "cuadrar",
        "quiero la fecha",
    }


@pytest.mark.parametrize(
    "state,pending,enabled,expected",
    [
        ("BOT_ACTIVE", None, True, True),
        ("ANSWERING_INFORMATION", None, True, True),
        ("BOT_ACTIVE", "COLLECT_CUSTOMER_NAME", True, False),
        ("COLLECTING_EVENT_DATA", "COLLECT_EVENT_DATE", True, False),
        ("WAITING_FOR_APPOINTMENT_SELECTION", "COLLECT_VISIT_REASON", True, False),
        ("APPOINTMENT_PENDING_CONFIRMATION", "CONFIRM_APPOINTMENT", True, False),
        ("BOT_ACTIVE", "CONFIRM_QUOTE_REQUEST", True, False),
        ("WAITING_FOR_HUMAN", None, True, False),
        ("HUMAN_ACTIVE", None, True, False),
        ("BOT_ACTIVE", None, False, False),
        ("APPOINTMENT_CONFIRMED", None, True, False),
    ],
)
def test_g3_a_pending_routes_and_human_states_exclude_guard(
    state: str,
    pending: str | None,
    enabled: bool,
    expected: bool,
) -> None:
    result = deterministic_booking_or_catalog_classification(
        "quiero reservar",
        {
            "state": state,
            "pending_action": pending,
            "bot_enabled": enabled,
            "booking_event": {"event_type": "ROMANTIC_DINNER"},
        },
    )
    assert (result is not None) is expected


def test_g3_b_catalog_label_resolves_before_llm_without_booking_guard() -> None:
    result = deterministic_booking_or_catalog_classification(
        "boda",
        {
            "state": "BOT_ACTIVE",
            "pending_action": "COLLECT_CATALOG_EVENT_TYPE",
            "booking_event": {"event_type": "ROMANTIC_DINNER"},
        },
    )
    assert result is not None and result.reasoning_code == "CATALOG_LABEL_MATCH"
