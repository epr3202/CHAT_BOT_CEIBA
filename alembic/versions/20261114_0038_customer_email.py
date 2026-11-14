"""Optional customer email captured from prefilled website messages.

Revision ID: 20261114_0038
Revises: 20261028_0037
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0038"
down_revision = "20261028_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("email", sa.String(length=254), nullable=True))


def downgrade() -> None:
    op.drop_column("customer", "email")
