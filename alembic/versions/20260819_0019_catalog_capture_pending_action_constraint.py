"""allow catalog event type capture as a pending action

Revision ID: 20260819_0019
Revises: 20260819_0018
Create Date: 2026-08-19 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0019"
down_revision: str | None = "20260819_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PENDING_ACTIONS_BEFORE = (
    "NONE",
    "CLASSIFY_MESSAGE",
    "ANSWER_INFORMATION",
    "SEND_CATALOG",
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

PENDING_ACTIONS_AFTER = (
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


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        f"pending_action IS NULL OR pending_action IN ({quoted(PENDING_ACTIONS_AFTER)})",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE conversation SET pending_action = NULL "
        "WHERE pending_action = 'COLLECT_CATALOG_EVENT_TYPE'"
    )
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        f"pending_action IS NULL OR pending_action IN ({quoted(PENDING_ACTIONS_BEFORE)})",
    )
