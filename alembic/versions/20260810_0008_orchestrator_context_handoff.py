"""orchestrator conversation context and handoff

Revision ID: 20260810_0008
Revises: 20260810_0007
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0008"
down_revision: str | None = "20260810_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("full_name", sa.String(length=255), nullable=True))
    op.add_column("conversation", sa.Column("last_intent", sa.String(length=64), nullable=True))
    op.add_column(
        "conversation",
        sa.Column("pending_action", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation",
        sa.Column("last_question_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation",
        sa.Column(
            "failed_understanding_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("conversation", "failed_understanding_count", server_default=None)

    op.create_table(
        "handoff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("source_intent", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('PENDING', 'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED')",
            name="ck_handoff_status",
        ),
        sa.CheckConstraint(
            "priority IN ('NORMAL', 'URGENT', 'CRITICAL')",
            name="ck_handoff_priority",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_handoff_conversation_id"), "handoff", ["conversation_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_handoff_conversation_id"), table_name="handoff")
    op.drop_table("handoff")
    op.drop_column("conversation", "failed_understanding_count")
    op.drop_column("conversation", "last_question_code")
    op.drop_column("conversation", "pending_action")
    op.drop_column("conversation", "last_intent")
    op.drop_column("customer", "full_name")
