"""outbox worker fields

Revision ID: 20260810_0002
Revises: 20260810_0001
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0002"
down_revision: str | None = "20260810_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("outbox", sa.Column("last_error", sa.String(length=1000), nullable=True))
    op.add_column("outbox", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("outbox", "attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("outbox", "sent_at")
    op.drop_column("outbox", "last_error")
    op.drop_column("outbox", "attempts")

