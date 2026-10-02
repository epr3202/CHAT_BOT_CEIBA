from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from app.conversation.pending_actions import PENDING_ACTIONS

MIGRATION_PATH = Path("alembic/versions/20260819_0019_catalog_capture_pending_action_constraint.py")


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("catalog_capture_constraint_0019", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_capture_constraint_lists_are_complete_and_reversible() -> None:
    migration = load_migration()

    # 0019 remains frozen; 0031 extends its catalog with booking actions.
    booking_path = Path("alembic/versions/20260930_0031_booking_draft.py")
    booking_spec = importlib.util.spec_from_file_location("booking_constraint_0031", booking_path)
    assert booking_spec is not None and booking_spec.loader is not None
    booking = importlib.util.module_from_spec(booking_spec)
    booking_spec.loader.exec_module(booking)
    assert migration.PENDING_ACTIONS_AFTER == booking.BEFORE
    assert booking.BEFORE + booking.ADDED + ("COLLECT_BOOKING_NAME",) == PENDING_ACTIONS
    assert migration.PENDING_ACTIONS_BEFORE == tuple(
        action
        for action in migration.PENDING_ACTIONS_AFTER
        if action != "COLLECT_CATALOG_EVENT_TYPE"
    )
    assert migration.PENDING_ACTIONS_AFTER == (
        "NONE",
        "CLASSIFY_MESSAGE",
        "ANSWER_INFORMATION",
        "SEND_CATALOG",
        "COLLECT_CATALOG_EVENT_TYPE",
        "COLLECT_EVENT_TYPE",
        "COLLECT_GUEST_COUNT",
        "COLLECT_EVENT_DATE",
        "COLLECT_CUSTOMER_NAME",
        "COLLECT_BUDGET",
        "COLLECT_SERVICES",
        "CONFIRM_QUOTE_REQUEST",
        "SELECT_VISIT_DATE",
        "CONFIRM_VISIT_DATE",
        "SELECT_VISIT_TIME",
        "COLLECT_VISIT_ATTENDEES",
        "COLLECT_VISIT_REASON",
        "CONFIRM_APPOINTMENT",
        "CONFIRM_RESCHEDULE",
        "CONFIRM_VISIT_CANCELLATION",
        "CONFIRM_EVENT_CANCELLATION",
        "WAIT_FOR_HUMAN",
        "WAIT_FOR_PAYMENT_REVIEW",
        "WAIT_FOR_RESERVATION_CONFIRMATION",
    )
