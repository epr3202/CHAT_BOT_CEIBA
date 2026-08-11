"""pending confirmation and official pending actions

Revision ID: 20260810_0010
Revises: 20260810_0009
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260810_0010"
down_revision: str | None = "20260810_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PENDING_ACTIONS = (
    "NONE",
    "CLASSIFY_MESSAGE",
    "ANSWER_INFORMATION",
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
    op.add_column(
        "conversation",
        sa.Column("pending_confirmation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        "UPDATE conversation SET pending_action = NULL "
        f"WHERE pending_action IS NOT NULL AND pending_action NOT IN ({quoted(PENDING_ACTIONS)})"
    )
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        f"pending_action IS NULL OR pending_action IN ({quoted(PENDING_ACTIONS)})",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversation DROP CONSTRAINT IF EXISTS ck_conversation_pending_action")
    op.drop_column("conversation", "pending_confirmation")
