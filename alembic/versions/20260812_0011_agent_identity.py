"""agent identity and direct takeover assignment

Revision ID: 20260812_0011
Revises: 20260810_0010
Create Date: 2026-08-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_0011"
down_revision: str | None = "20260810_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("token_hash"),
    )
    op.add_column("conversation", sa.Column("assigned_agent_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_conversation_assigned_agent_id"),
        "conversation",
        ["assigned_agent_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_conversation_assigned_agent_id_agent"),
        "conversation",
        "agent",
        ["assigned_agent_id"],
        ["id"],
    )
    op.add_column("handoff", sa.Column("assigned_agent_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_handoff_assigned_agent_id"),
        "handoff",
        ["assigned_agent_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_handoff_assigned_agent_id_agent"),
        "handoff",
        "agent",
        ["assigned_agent_id"],
        ["id"],
    )
    op.drop_constraint("ck_handoff_reason", "handoff", type_="check")
    op.create_check_constraint(
        "ck_handoff_reason",
        "handoff",
        "reason IN ("
        "'CUSTOMER_REQUEST', 'QUOTE_PREPARATION', 'PRICE_NEGOTIATION', "
        "'DISCOUNT_REQUEST', 'PAYMENT_REVIEW', 'RESERVATION_CONFIRMATION', "
        "'CANCELLATION', 'COMPLAINT', 'LOW_CONFIDENCE', 'UNSUPPORTED_REQUEST', "
        "'CAPACITY_REVIEW', 'SPECIAL_EVENT', 'SUPPLIER_CONFIRMATION', "
        "'URGENT_EVENT', 'SYSTEM_ERROR', 'REPEATED_NO_SHOW', 'MANUAL_TAKEOVER', 'OTHER'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_handoff_reason", "handoff", type_="check")
    op.execute("UPDATE handoff SET reason = 'OTHER' WHERE reason = 'MANUAL_TAKEOVER'")
    op.create_check_constraint(
        "ck_handoff_reason",
        "handoff",
        "reason IN ("
        "'CUSTOMER_REQUEST', 'QUOTE_PREPARATION', 'PRICE_NEGOTIATION', "
        "'DISCOUNT_REQUEST', 'PAYMENT_REVIEW', 'RESERVATION_CONFIRMATION', "
        "'CANCELLATION', 'COMPLAINT', 'LOW_CONFIDENCE', 'UNSUPPORTED_REQUEST', "
        "'CAPACITY_REVIEW', 'SPECIAL_EVENT', 'SUPPLIER_CONFIRMATION', "
        "'URGENT_EVENT', 'SYSTEM_ERROR', 'REPEATED_NO_SHOW', 'OTHER'"
        ")",
    )
    op.execute("ALTER TABLE handoff DROP CONSTRAINT IF EXISTS fk_handoff_assigned_agent_id_agent")
    op.execute("ALTER TABLE handoff DROP CONSTRAINT IF EXISTS handoff_assigned_agent_id_fkey")
    op.drop_index(op.f("ix_handoff_assigned_agent_id"), table_name="handoff")
    op.drop_column("handoff", "assigned_agent_id")
    op.execute(
        "ALTER TABLE conversation DROP CONSTRAINT IF EXISTS "
        "fk_conversation_assigned_agent_id_agent"
    )
    op.execute(
        "ALTER TABLE conversation DROP CONSTRAINT IF EXISTS conversation_assigned_agent_id_fkey"
    )
    op.drop_index(op.f("ix_conversation_assigned_agent_id"), table_name="conversation")
    op.drop_column("conversation", "assigned_agent_id")
    op.drop_table("agent")
