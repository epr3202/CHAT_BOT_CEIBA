"""Add fixed-price plans, reservations and optional payment-evidence linkage.

Revision ID: 20260930_0028
Revises: 20260910_0027
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0028"
down_revision = "20260910_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("price_cop", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("exclusive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("weekend_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_plan_code"),
        sa.CheckConstraint("event_type IN ('ROMANTIC_DINNER', 'PROPOSAL')",
                           name="ck_plan_event_type"),
        sa.CheckConstraint("price_cop > 0", name="ck_plan_price_positive"),
        sa.CheckConstraint("duration_minutes > 0", name="ck_plan_duration_positive"),
    )
    op.create_table(
        "reservation",
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lead.lead_id"),
                  nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event.event_id"),
                  nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plan.plan_id"),
                  nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"),
                  nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_cop", sa.Integer(), nullable=False),
        sa.Column("amount_paid_cop", sa.Integer(), nullable=False),
        sa.Column("payment_kind", sa.String(16), nullable=True),
        sa.Column("balance_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_calendar_id", sa.String(255), nullable=True),
        sa.Column("calendar_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('PAYMENT_PENDING', 'PAYMENT_REVIEW', 'RESERVED', 'EXPIRED', 'CANCELLED')",
            name="ck_reservation_status",
        ),
        sa.CheckConstraint("payment_kind IS NULL OR payment_kind IN ('DEPOSIT', 'FULL')",
                           name="ck_reservation_payment_kind"),
        sa.CheckConstraint("price_cop > 0", name="ck_reservation_price_positive"),
        sa.CheckConstraint("amount_paid_cop >= 0", name="ck_reservation_paid_nonnegative"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_reservation_time_range"),
    )
    op.create_index("ix_reservation_starts_at_status", "reservation", ["starts_at", "status"])
    op.add_column("payment_evidence", sa.Column(
        "reservation_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        "fk_payment_evidence_reservation", "payment_evidence", "reservation",
        ["reservation_id"], ["reservation_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_payment_evidence_reservation", "payment_evidence", type_="foreignkey")
    op.drop_column("payment_evidence", "reservation_id")
    op.drop_index("ix_reservation_starts_at_status", table_name="reservation")
    op.drop_table("reservation")
    op.drop_table("plan")
