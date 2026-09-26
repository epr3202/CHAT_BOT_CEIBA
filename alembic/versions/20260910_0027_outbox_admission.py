"""Durable automation period and explicit local Outbox admission.

Revision ID: 20260910_0027
Revises: 20260908_0026

No historical Outbox is granted the current period. Unknown provenance is reviewed
by the new consumer; SENT/FAILED and append-only history are unchanged.
Old producers/consumers must be stopped before activation (not performed here).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260910_0027"
down_revision = "20260908_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column(
        "automation_epoch", postgresql.UUID(as_uuid=True), nullable=False,
        server_default=sa.text("gen_random_uuid()"),
    ))
    op.add_column("outbox", sa.Column("delivery_context", postgresql.JSONB(), nullable=True))
    op.add_column("outbox", sa.Column("send_admission", postgresql.JSONB(), nullable=True))
    op.add_column("outbox", sa.Column("delivery_reason", sa.String(128), nullable=True))
    op.add_column("outbox", sa.Column(
        "delivery_decided_at", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    # Only an explicitly selected, stopped-consumer synthetic rehearsal is authorized here.
    op.drop_column("outbox", "delivery_decided_at")
    op.drop_column("outbox", "delivery_reason")
    op.drop_column("outbox", "send_admission")
    op.drop_column("outbox", "delivery_context")
    op.drop_column("conversation", "automation_epoch")
