"""Persist deterministic booking slots and extend the pending-action catalog.

Revision ID: 20260930_0031
Revises: 20260930_0030
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0031"
down_revision = "20260930_0030"
branch_labels = None
depends_on = None

# Frozen historical catalogs: migration behavior must not depend on runtime imports.
BEFORE = (
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
ADDED = ("SELECT_BOOKING_PLAN", "SELECT_BOOKING_DATETIME", "SELECT_BOOKING_TIME", "CONFIRM_BOOKING")


def check(values: tuple[str, ...]) -> None:
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        "pending_action IS NULL OR pending_action IN ("
        + ", ".join(f"'{value}'" for value in values)
        + ")",
    )


def upgrade() -> None:
    op.add_column("conversation", sa.Column("booking_draft", postgresql.JSONB(), nullable=True))
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    check(BEFORE + ADDED)


def downgrade() -> None:
    op.execute(
        "UPDATE conversation SET pending_action = NULL WHERE pending_action IN ("
        + ", ".join(f"'{value}'" for value in ADDED)
        + ")"
    )
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    check(BEFORE)
    op.drop_column("conversation", "booking_draft")
