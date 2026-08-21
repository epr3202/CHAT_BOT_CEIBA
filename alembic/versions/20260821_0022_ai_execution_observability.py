"""evolve legacy ai execution observability

Revision ID: 20260821_0022
Revises: 20260819_0021
Create Date: 2026-08-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_0022"
down_revision: str | None = "20260819_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("ai_execution", "function", new_column_name="task")
    op.create_check_constraint(
        "ck_ai_execution_task",
        "ai_execution",
        "task IN ('INTENT_CLASSIFICATION', 'SERVICES_CLASSIFICATION', 'EVENT_TYPE_EXTRACTION')",
    )
    op.add_column(
        "ai_execution",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ai_execution",
        sa.Column("external_message_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_execution",
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ai_execution",
        sa.Column("raw_output", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_execution",
        sa.Column("parsed_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ai_execution",
        sa.Column("validation_status", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_ai_execution_validation_status",
        "ai_execution",
        "validation_status IN ('VALID', 'NORMALIZED', 'INVALID_SCHEMA', 'DISCARDED', 'HTTP_ERROR')",
    )
    op.add_column(
        "ai_execution",
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_execution_validation_status",
        "ai_execution",
        type_="check",
    )
    op.drop_constraint("ck_ai_execution_task", "ai_execution", type_="check")
    op.drop_column("ai_execution", "error")
    op.drop_column("ai_execution", "validation_status")
    op.drop_column("ai_execution", "parsed_output")
    op.drop_column("ai_execution", "raw_output")
    op.drop_column("ai_execution", "input_payload")
    op.drop_column("ai_execution", "external_message_id")
    op.drop_column("ai_execution", "request_id")
    op.alter_column("ai_execution", "task", new_column_name="function")
