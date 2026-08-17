"""appointment holiday blocked date

Revision ID: 20260813_0017
Revises: 20260813_0016
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0017"
down_revision: str | None = "20260813_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holiday",
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('SEEDED', 'MANUAL')", name="ck_holiday_source"),
        sa.PrimaryKeyConstraint("holiday_date"),
    )
    op.create_table(
        "blocked_date",
        sa.Column("blocked_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("blocked_date"),
    )
    op.create_table(
        "appointment",
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("appointment_type", sa.String(length=32), nullable=False),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("attendee_count", sa.Integer(), nullable=False),
        sa.Column("visitor_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("visit_reason", sa.String(length=255), nullable=False),
        sa.Column("appointment_status", sa.String(length=32), nullable=False),
        sa.Column("assigned_manager_id", sa.Integer(), nullable=True),
        sa.Column("external_calendar_id", sa.String(length=255), nullable=True),
        sa.Column("reminder_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reschedule_count", sa.Integer(), nullable=False),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("no_show_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("internal_notes", sa.String(length=2000), nullable=True),
        sa.Column("requires_reconciliation", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("appointment_type IN ('VISIT')", name="ck_appointment_type"),
        sa.CheckConstraint(
            "appointment_status IN ("
            "'PENDING_CONFIRMATION', "
            "'CONFIRMED', "
            "'RESCHEDULED', "
            "'CANCELLED', "
            "'LATE_CANCEL', "
            "'COMPLETED', "
            "'NO_SHOW'"
            ")",
            name="ck_appointment_status",
        ),
        sa.CheckConstraint(
            "start_time IN ('08:00:00', '09:00:00', '10:00:00', '11:00:00')",
            name="ck_appointment_start_time",
        ),
        sa.CheckConstraint("attendee_count BETWEEN 1 AND 3", name="ck_appointment_attendees"),
        sa.CheckConstraint("reschedule_count >= 0", name="ck_appointment_reschedule_count"),
        sa.CheckConstraint("timezone = 'America/Bogota'", name="ck_appointment_timezone"),
        sa.CheckConstraint(
            "appointment_status != 'CONFIRMED' OR external_calendar_id IS NOT NULL",
            name="ck_appointment_confirmed_external_calendar",
        ),
        sa.ForeignKeyConstraint(["assigned_manager_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.lead_id"]),
        sa.PrimaryKeyConstraint("appointment_id"),
        sa.UniqueConstraint("external_calendar_id"),
    )
    op.create_index("ix_appointment_appointment_date", "appointment", ["appointment_date"])
    op.create_index("ix_appointment_assigned_manager_id", "appointment", ["assigned_manager_id"])
    op.create_index("ix_appointment_customer_id", "appointment", ["customer_id"])
    op.create_index("ix_appointment_lead_id", "appointment", ["lead_id"])
    op.create_index(
        "uq_appointment_active_slot",
        "appointment",
        ["appointment_date", "start_time"],
        unique=True,
        postgresql_where=sa.text(
            "appointment_status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'RESCHEDULED')"
        ),
    )
    op.create_table(
        "appointment_change",
        sa.Column("appointment_change_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_date", sa.Date(), nullable=False),
        sa.Column("previous_start_time", sa.Time(), nullable=False),
        sa.Column("new_date", sa.Date(), nullable=False),
        sa.Column("new_start_time", sa.Time(), nullable=False),
        sa.Column("change_reason", sa.String(length=500), nullable=True),
        sa.Column("changed_by_type", sa.String(length=32), nullable=False),
        sa.Column("changed_by_id", sa.String(length=128), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "changed_by_type IN ('SYSTEM', 'CUSTOMER', 'AGENT', 'BUSINESS_MANAGER')",
            name="ck_appointment_change_actor",
        ),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointment.appointment_id"]),
        sa.PrimaryKeyConstraint("appointment_change_id"),
    )
    op.create_index(
        "ix_appointment_change_appointment_id",
        "appointment_change",
        ["appointment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_appointment_change_appointment_id", table_name="appointment_change")
    op.drop_table("appointment_change")
    op.drop_index("uq_appointment_active_slot", table_name="appointment")
    op.drop_index("ix_appointment_lead_id", table_name="appointment")
    op.drop_index("ix_appointment_customer_id", table_name="appointment")
    op.drop_index("ix_appointment_assigned_manager_id", table_name="appointment")
    op.drop_index("ix_appointment_appointment_date", table_name="appointment")
    op.drop_table("appointment")
    op.drop_table("blocked_date")
    op.drop_table("holiday")
