"""catalog assets and document outbox

Revision ID: 20260813_0014
Revises: 20260813_0013
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0014"
down_revision: str | None = "20260813_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES_SQL = (
    "'WEDDING', 'CIVIL_WEDDING', 'PROPOSAL', 'BIRTHDAY', 'GRADUATION', "
    "'ANNIVERSARY', 'ROMANTIC_DINNER', 'CORPORATE_EVENT', 'FAMILY_EVENT', "
    "'BAPTISM', 'FIRST_COMMUNION', 'BABY_SHOWER', 'WORKSHOP', 'POOL_DAY', "
    "'PRIVATE_DINNER', 'OTHER'"
)

PENDING_ACTIONS = (
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


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "catalog_asset",
        sa.Column("catalog_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=127), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("media_id", sa.String(length=255), nullable=True),
        sa.Column("media_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("mime_type = 'application/pdf'", name="ck_catalog_asset_mime_type_pdf"),
        sa.CheckConstraint("file_size > 0", name="ck_catalog_asset_file_size_positive"),
        sa.CheckConstraint("version >= 1", name="ck_catalog_asset_version_positive"),
        sa.PrimaryKeyConstraint("catalog_asset_id"),
    )
    op.create_table(
        "catalog_event_type_map",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalog_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"event_type IN ({EVENT_TYPES_SQL})",
            name="ck_catalog_event_type_map_event_type",
        ),
        sa.ForeignKeyConstraint(["catalog_asset_id"], ["catalog_asset.catalog_asset_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("catalog_asset_id", "event_type", name="uq_catalog_asset_event_type"),
    )
    op.create_index(
        op.f("ix_catalog_event_type_map_catalog_asset_id"),
        "catalog_event_type_map",
        ["catalog_asset_id"],
    )
    op.create_index(
        op.f("ix_catalog_event_type_map_event_type"),
        "catalog_event_type_map",
        ["event_type"],
    )
    op.add_column(
        "outbox",
        sa.Column("message_kind", sa.String(length=32), nullable=False, server_default="TEXT"),
    )
    op.add_column(
        "outbox",
        sa.Column("catalog_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("outbox", "message_kind", server_default=None)
    op.create_foreign_key(
        op.f("fk_outbox_catalog_asset_id_catalog_asset"),
        "outbox",
        "catalog_asset",
        ["catalog_asset_id"],
        ["catalog_asset_id"],
    )
    op.create_check_constraint(
        "ck_outbox_message_kind",
        "outbox",
        "message_kind IN ('TEXT', 'DOCUMENT')",
    )
    op.create_check_constraint(
        "ck_outbox_document_has_catalog_asset",
        "outbox",
        "message_kind != 'DOCUMENT' OR catalog_asset_id IS NOT NULL",
    )
    op.create_table(
        "catalog_send",
        sa.Column("catalog_send_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("outbound_message_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trigger IN ('PROACTIVE', 'EXPLICIT_REQUEST')",
            name="ck_catalog_send_trigger",
        ),
        sa.ForeignKeyConstraint(["catalog_asset_id"], ["catalog_asset.catalog_asset_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.lead_id"]),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbox.id"]),
        sa.PrimaryKeyConstraint("catalog_send_id"),
    )
    op.create_index(op.f("ix_catalog_send_lead_id"), "catalog_send", ["lead_id"])
    op.create_index(
        op.f("ix_catalog_send_catalog_asset_id"),
        "catalog_send",
        ["catalog_asset_id"],
    )
    op.create_index(
        "uq_catalog_send_proactive_lead_asset",
        "catalog_send",
        ["lead_id", "catalog_asset_id"],
        unique=True,
        postgresql_where=sa.text("trigger = 'PROACTIVE'"),
    )
    op.execute("ALTER TABLE conversation DROP CONSTRAINT IF EXISTS ck_conversation_pending_action")
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        f"pending_action IS NULL OR pending_action IN ({quoted(PENDING_ACTIONS)})",
    )


def downgrade() -> None:
    previous_actions = tuple(action for action in PENDING_ACTIONS if action != "SEND_CATALOG")
    op.execute("ALTER TABLE conversation DROP CONSTRAINT IF EXISTS ck_conversation_pending_action")
    op.execute(
        "UPDATE conversation SET pending_action = NULL WHERE pending_action = 'SEND_CATALOG'"
    )
    op.create_check_constraint(
        "ck_conversation_pending_action",
        "conversation",
        f"pending_action IS NULL OR pending_action IN ({quoted(previous_actions)})",
    )
    op.drop_index("uq_catalog_send_proactive_lead_asset", table_name="catalog_send")
    op.drop_index(op.f("ix_catalog_send_catalog_asset_id"), table_name="catalog_send")
    op.drop_index(op.f("ix_catalog_send_lead_id"), table_name="catalog_send")
    op.drop_table("catalog_send")
    op.drop_constraint("ck_outbox_document_has_catalog_asset", "outbox", type_="check")
    op.drop_constraint("ck_outbox_message_kind", "outbox", type_="check")
    op.drop_constraint(
        op.f("fk_outbox_catalog_asset_id_catalog_asset"),
        "outbox",
        type_="foreignkey",
    )
    op.drop_column("outbox", "catalog_asset_id")
    op.drop_column("outbox", "message_kind")
    op.drop_index(
        op.f("ix_catalog_event_type_map_event_type"),
        table_name="catalog_event_type_map",
    )
    op.drop_index(
        op.f("ix_catalog_event_type_map_catalog_asset_id"),
        table_name="catalog_event_type_map",
    )
    op.drop_table("catalog_event_type_map")
    op.drop_table("catalog_asset")
