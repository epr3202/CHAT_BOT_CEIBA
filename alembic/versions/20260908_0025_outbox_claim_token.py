"""Add nullable per-acquisition Outbox identity without assigning legacy owners.

Revision ID: 20260908_0025
Revises: 20260825_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0025"
down_revision: str | None = "20260825_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    # Operational rollback requires stopped consumers; removing this field removes fencing.
    op.drop_column("outbox", "claim_token")
