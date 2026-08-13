"""quote capture models

Revision ID: 20260813_0013
Revises: 20260812_0012
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0013"
down_revision: str | None = "20260812_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead",
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("lead_status", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("estimated_budget", sa.Numeric(12, 2), nullable=True),
        sa.Column("budget_range", sa.String(length=32), nullable=False),
        sa.Column("budget_data_status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "lead_status IN ('NEW', 'QUALIFYING', 'QUALIFIED', 'QUOTE_REQUESTED')",
            name="ck_lead_status",
        ),
        sa.CheckConstraint("channel IN ('WHATSAPP')", name="ck_lead_channel"),
        sa.CheckConstraint(
            "budget_range IN ('NOT_PROVIDED', 'BELOW_REFERENCE', 'REFERENCE_RANGE', "
            "'PREMIUM', 'CUSTOM')",
            name="ck_lead_budget_range",
        ),
        sa.CheckConstraint(
            "budget_data_status IN ('NOT_ASKED', 'ASKED_PENDING', 'PROVIDED', "
            "'DECLINED', 'RANGE_PROVIDED', 'CORRECTED')",
            name="ck_lead_budget_data_status",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("lead_id"),
    )
    op.create_index(op.f("ix_lead_customer_id"), "lead", ["customer_id"])

    op.create_table(
        "event",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("event_type_other", sa.String(length=150), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_month", sa.String(length=7), nullable=True),
        sa.Column("event_date_type", sa.String(length=32), nullable=True),
        sa.Column("event_date_raw", sa.String(length=200), nullable=True),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column("guest_count_min", sa.Integer(), nullable=True),
        sa.Column("guest_count_max", sa.Integer(), nullable=True),
        sa.Column("guest_count_status", sa.String(length=32), nullable=True),
        sa.Column("special_requests", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type IS NULL OR event_type IN ('WEDDING', 'CIVIL_WEDDING', 'PROPOSAL', "
            "'BIRTHDAY', 'GRADUATION', 'ANNIVERSARY', 'ROMANTIC_DINNER', "
            "'CORPORATE_EVENT', 'FAMILY_EVENT', 'BAPTISM', 'FIRST_COMMUNION', "
            "'BABY_SHOWER', 'WORKSHOP', 'POOL_DAY', 'PRIVATE_DINNER', 'OTHER')",
            name="ck_event_type",
        ),
        sa.CheckConstraint(
            "event_date_type IS NULL OR event_date_type IN "
            "('EXACT', 'APPROXIMATE', 'FLEXIBLE', 'UNKNOWN')",
            name="ck_event_date_type",
        ),
        sa.CheckConstraint(
            "guest_count_status IS NULL OR guest_count_status IN "
            "('PROVIDED', 'RANGE', 'ESTIMATED')",
            name="ck_event_guest_count_status",
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.lead_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(op.f("ix_event_lead_id"), "event", ["lead_id"])

    op.create_table(
        "event_service_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('REQUESTED', 'REMOVED')",
            name="ck_event_service_request_status",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["event.event_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_service_request_event_id"),
        "event_service_request",
        ["event_id"],
    )

    op.create_table(
        "quote_request",
        sa.Column("quote_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_status", sa.String(length=32), nullable=False),
        sa.Column("minimum_data_complete", sa.Boolean(), nullable=False),
        sa.Column("missing_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("date_pending", sa.Boolean(), nullable=False),
        sa.Column("summary_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "request_status IN ('DRAFT', 'READY')",
            name="ck_quote_request_status",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["event.event_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.lead_id"]),
        sa.PrimaryKeyConstraint("quote_request_id"),
    )
    op.create_index(op.f("ix_quote_request_event_id"), "quote_request", ["event_id"])
    op.create_index(op.f("ix_quote_request_lead_id"), "quote_request", ["lead_id"])

    op.add_column(
        "conversation",
        sa.Column(
            "pending_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "conversation",
        sa.Column("active_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("conversation", "pending_fields", server_default=None)
    op.create_index(op.f("ix_conversation_active_lead_id"), "conversation", ["active_lead_id"])
    op.create_foreign_key(
        op.f("fk_conversation_active_lead_id_lead"),
        "conversation",
        "lead",
        ["active_lead_id"],
        ["lead_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_conversation_active_lead_id_lead"), "conversation", type_="foreignkey"
    )
    op.drop_index(op.f("ix_conversation_active_lead_id"), table_name="conversation")
    op.drop_column("conversation", "active_lead_id")
    op.drop_column("conversation", "pending_fields")
    op.drop_index(op.f("ix_quote_request_lead_id"), table_name="quote_request")
    op.drop_index(op.f("ix_quote_request_event_id"), table_name="quote_request")
    op.drop_table("quote_request")
    op.drop_index(op.f("ix_event_service_request_event_id"), table_name="event_service_request")
    op.drop_table("event_service_request")
    op.drop_index(op.f("ix_event_lead_id"), table_name="event")
    op.drop_table("event")
    op.drop_index(op.f("ix_lead_customer_id"), table_name="lead")
    op.drop_table("lead")
