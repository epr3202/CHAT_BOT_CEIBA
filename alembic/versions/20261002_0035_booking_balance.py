"""Payment pre-review leases and scheduled balance reminders.

Revision ID: 20261002_0035
Revises: 20261002_0034
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261002_0035"
down_revision = "20261002_0034"
branch_labels = None
depends_on = None


def staff_event_check(include_balance: bool) -> None:
    values = "'EVIDENCE_RECEIVED','PAYMENT_PENDING_CREATED','TEST'"
    if include_balance:
        values += ",'BALANCE_OVERDUE'"
    op.create_check_constraint(
        "ck_staff_outbox_event_kind", "staff_outbox", f"event_kind IN ({values})"
    )


def upgrade() -> None:
    op.add_column(
        "payment_evidence", sa.Column("prereview_claim_token", postgresql.UUID(as_uuid=True))
    )
    op.add_column("payment_evidence", sa.Column("prereview_claimed_at", sa.DateTime(timezone=True)))
    op.add_column("reservation", sa.Column("balance_overdue_at", sa.DateTime(timezone=True)))
    op.create_table(
        "customer_notification",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reservation.reservation_id"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("template_name", sa.String(128), nullable=False),
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
            "kind IN ('BALANCE_REMINDER_EARLY','BALANCE_REMINDER_DUE')",
            name="ck_customer_notification_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','DELIVERED','READ',"
            "'FAILED','DEFERRED','EXPIRED')",
            name="ck_customer_notification_status",
        ),
        sa.UniqueConstraint(
            "reservation_id", "kind", name="uq_customer_notification_reservation_kind"
        ),
    )
    op.create_index(
        "ix_customer_notification_provider_message_id",
        "customer_notification",
        ["provider_message_id"],
    )
    op.create_index(
        "ix_customer_notification_due",
        "customer_notification",
        ["status", "next_attempt_at"],
        postgresql_where=sa.text("status IN ('PENDING','SENDING')"),
    )
    op.drop_constraint("ck_staff_outbox_event_kind", "staff_outbox", type_="check")
    staff_event_check(True)


def downgrade() -> None:
    # Restoring the old event CHECK fails loudly if new staff notices still exist.
    # Never delete operational history to make a production downgrade succeed.
    op.drop_constraint("ck_staff_outbox_event_kind", "staff_outbox", type_="check")
    staff_event_check(False)
    op.drop_table("customer_notification")
    op.drop_column("reservation", "balance_overdue_at")
    op.drop_column("payment_evidence", "prereview_claimed_at")
    op.drop_column("payment_evidence", "prereview_claim_token")
