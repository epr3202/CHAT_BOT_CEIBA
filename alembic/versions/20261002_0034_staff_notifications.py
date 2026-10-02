"""Internal staff notifications, customer rejection reason and booking-name action.

Revision ID: 20261002_0034
Revises: 20260930_0033
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261002_0034"
down_revision = "20260930_0033"
branch_labels = None
depends_on = None

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
)
ADDED = ("COLLECT_BOOKING_NAME",)


def pending_check(values: tuple[str, ...]) -> None:
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        "pending_action IS NULL OR pending_action IN ("
        + ", ".join(f"'{value}'" for value in values)
        + ")",
    )


def upgrade() -> None:
    op.create_table(
        "notification_recipient",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False, unique=True),
        sa.Column("notify_on_evidence", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "notify_on_payment_pending", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True)),
        sa.Column("last_inbound_message_id", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            r"phone_number ~ '^\+[1-9][0-9]{7,14}$'", name="ck_notification_recipient_phone"
        ),
    )
    op.create_table(
        "staff_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "recipient_id",
            sa.BigInteger(),
            sa.ForeignKey("notification_recipient.id"),
            nullable=False,
        ),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("source_entity", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("message_kind", sa.String(16)),
        sa.Column("template_name", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_error_code", sa.Integer()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "event_kind IN ('EVIDENCE_RECEIVED','PAYMENT_PENDING_CREATED','TEST')",
            name="ck_staff_outbox_event_kind",
        ),
        sa.CheckConstraint(
            "message_kind IN ('TEXT','TEMPLATE')", name="ck_staff_outbox_message_kind"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','DELIVERED','READ',"
            "'FAILED','DEFERRED','EXPIRED')",
            name="ck_staff_outbox_status",
        ),
        sa.UniqueConstraint(
            "recipient_id",
            "event_kind",
            "source_entity",
            "source_id",
            name="uq_staff_outbox_source",
        ),
    )
    op.create_index("ix_staff_outbox_provider_message_id", "staff_outbox", ["provider_message_id"])
    op.create_index(
        "ix_staff_outbox_due",
        "staff_outbox",
        ["status", "next_attempt_at"],
        postgresql_where=sa.text("status IN ('PENDING','SENDING')"),
    )
    op.add_column("payment_evidence", sa.Column("customer_reason", sa.String(200), nullable=True))
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    pending_check(BEFORE + ADDED)


def downgrade() -> None:
    op.execute(
        "UPDATE conversation SET pending_action=NULL WHERE pending_action='COLLECT_BOOKING_NAME'"
    )
    op.drop_constraint("ck_conversation_pending_action", "conversation", type_="check")
    pending_check(BEFORE)
    op.drop_column("payment_evidence", "customer_reason")
    op.drop_index("ix_staff_outbox_due", table_name="staff_outbox")
    op.drop_index("ix_staff_outbox_provider_message_id", table_name="staff_outbox")
    op.drop_table("staff_outbox")
    op.drop_table("notification_recipient")
