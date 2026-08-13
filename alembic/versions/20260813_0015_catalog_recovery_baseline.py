"""catalog recovery baseline

Revision ID: 20260813_0015
Revises: 20260813_0014
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

revision: str = "20260813_0015"
down_revision: str | None = "20260813_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
