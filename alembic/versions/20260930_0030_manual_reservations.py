"""Allow manual reservations without a conversation.

Revision ID: 20260930_0030
Revises: 20260930_0029
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0030"
down_revision = "20260930_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("reservation", "conversation_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Preserve manual financial records: refuse a lossy downgrade until linked.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM reservation WHERE conversation_id IS NULL) THEN
                RAISE EXCEPTION 'Link manual reservations to conversations before downgrading 0030';
            END IF;
        END $$
    """)
    op.alter_column("reservation", "conversation_id", existing_type=sa.Integer(), nullable=False)
