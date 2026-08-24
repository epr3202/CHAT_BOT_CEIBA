"""add PR-B.1 capture context columns

Revision ID: 20260824_0023
Revises: 20260821_0022
Create Date: 2026-08-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0023"
down_revision: str | None = "20260821_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("services_failed_understanding_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "event_service_request",
        sa.Column("position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_service_request", "position")
    op.drop_column("conversation", "services_failed_understanding_count")
