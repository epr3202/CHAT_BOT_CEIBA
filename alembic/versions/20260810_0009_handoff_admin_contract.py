"""handoff admin contract

Revision ID: 20260810_0009
Revises: 20260810_0008
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0009"
down_revision: str | None = "20260810_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HANDOFF_REASONS = (
    "CUSTOMER_REQUEST",
    "QUOTE_PREPARATION",
    "PRICE_NEGOTIATION",
    "DISCOUNT_REQUEST",
    "PAYMENT_REVIEW",
    "RESERVATION_CONFIRMATION",
    "CANCELLATION",
    "COMPLAINT",
    "LOW_CONFIDENCE",
    "UNSUPPORTED_REQUEST",
    "CAPACITY_REVIEW",
    "SPECIAL_EVENT",
    "SUPPLIER_CONFIRMATION",
    "URGENT_EVENT",
    "SYSTEM_ERROR",
    "REPEATED_NO_SHOW",
    "OTHER",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("conversation", "bot_enabled", server_default=None)

    op.drop_constraint("ck_handoff_status", "handoff", type_="check")
    op.create_check_constraint(
        "ck_handoff_status",
        "handoff",
        "status IN ('PENDING', 'TAKEN', 'RETURNED', 'RESOLVED')",
    )
    op.create_check_constraint(
        "ck_handoff_reason",
        "handoff",
        f"reason IN ({quoted(HANDOFF_REASONS)})",
    )
    op.add_column("handoff", sa.Column("assigned_to", sa.String(length=255), nullable=True))
    op.add_column("handoff", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("handoff", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE handoff SET summary = 'Resumen no disponible' WHERE summary IS NULL")
    op.alter_column("handoff", "summary", nullable=False)
    op.drop_column("handoff", "source_intent")
    op.drop_column("handoff", "updated_at")


def downgrade() -> None:
    op.alter_column("handoff", "summary", nullable=True)
    op.add_column(
        "handoff",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("handoff", sa.Column("source_intent", sa.String(length=64), nullable=True))
    op.drop_column("handoff", "resolved_at")
    op.drop_column("handoff", "taken_at")
    op.drop_column("handoff", "assigned_to")
    op.drop_constraint("ck_handoff_reason", "handoff", type_="check")
    op.drop_constraint("ck_handoff_status", "handoff", type_="check")
    op.execute("UPDATE handoff SET status = 'IN_PROGRESS' WHERE status = 'TAKEN'")
    op.execute("UPDATE handoff SET status = 'RESOLVED' WHERE status = 'RETURNED'")
    op.create_check_constraint(
        "ck_handoff_status",
        "handoff",
        "status IN ('PENDING', 'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED')",
    )
    op.drop_column("conversation", "bot_enabled")
