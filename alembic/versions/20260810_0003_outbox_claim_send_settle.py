"""outbox claim send settle fields

Revision ID: 20260810_0003
Revises: 20260810_0002
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0003"
down_revision: str | None = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_outbox_status_next_attempt_at",
        "outbox",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_next_attempt_at", table_name="outbox")
    op.drop_column("outbox", "claimed_at")
    op.drop_column("outbox", "next_attempt_at")
