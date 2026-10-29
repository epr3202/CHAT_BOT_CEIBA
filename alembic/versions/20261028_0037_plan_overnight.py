"""Overnight plan intervals and availability-inquiry confirmation.

Downgrade deliberately fails while a conversation uses the new pending action.
It never clears business state to make the historical CHECK fit.

Revision ID: 20261028_0037
Revises: 20261007_0036
"""

import os
from datetime import time

import sqlalchemy as sa

from alembic import op

revision = "20261028_0037"
down_revision = "20261007_0036"
branch_labels = None
depends_on = None

# Historical catalog, frozen independently of future runtime imports.
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
    "SELECT_BOOKING_PLAN",
    "SELECT_BOOKING_DATETIME",
    "SELECT_BOOKING_TIME",
    "CONFIRM_BOOKING",
    "COLLECT_BOOKING_NAME",
)
ADDED = ("CONFIRM_AVAILABILITY_BOOKING",)


def pending_check(values: tuple[str, ...]) -> None:
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        "pending_action IS NULL OR pending_action IN ("
        + ", ".join(f"'{value}'" for value in values)
        + ")",
    )


def upgrade() -> None:
    op.add_column(
        "plan", sa.Column("overnight", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("plan", sa.Column("checkin_from", sa.Time(), nullable=True))
    op.add_column("plan", sa.Column("checkout_time", sa.Time(), nullable=True))
    op.create_check_constraint(
        "ck_plan_overnight_hours",
        "plan",
        "NOT overnight OR (checkin_from IS NOT NULL AND checkout_time IS NOT NULL)",
    )
    # Initial settings only. Subsequent changes belong to the audited plan editor;
    # loading the catalog again must not overwrite these persisted hours.
    checkin = time.fromisoformat(os.environ.get("LODGING_CHECKIN_FROM", "15:00"))
    checkout = time.fromisoformat(os.environ.get("LODGING_CHECKOUT_TIME", "11:00"))
    op.get_bind().execute(
        sa.text(
            "UPDATE plan SET overnight=true, checkin_from=:checkin, checkout_time=:checkout "
            "WHERE code='REFUGIO_DOS'"
        ),
        {"checkin": checkin, "checkout": checkout},
    )
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    pending_check(BEFORE + ADDED)


def downgrade() -> None:
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    # PostgreSQL rejects this CHECK if pending confirmations exist. Transactional
    # DDL then preserves the complete 0037 schema and every conversation value.
    pending_check(BEFORE)
    op.drop_constraint("ck_plan_overnight_hours", "plan", type_="check")
    op.drop_column("plan", "checkout_time")
    op.drop_column("plan", "checkin_from")
    op.drop_column("plan", "overnight")
