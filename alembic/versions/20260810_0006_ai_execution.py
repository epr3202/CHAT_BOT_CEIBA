"""ai execution telemetry

Revision ID: 20260810_0006
Revises: 20260810_0005
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0006"
down_revision: str | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_execution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("function", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_reason", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("input_character_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_execution_conversation_id",
        "ai_execution",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_execution_conversation_id", table_name="ai_execution")
    op.drop_table("ai_execution")
