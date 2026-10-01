"""Persist the human-verified amount on each payment evidence.

Revision ID: 20260930_0032
Revises: 20260930_0031
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0032"
down_revision = "20260930_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payment_evidence", sa.Column("amount_cop", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_evidence", "amount_cop")
