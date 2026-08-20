"""add catalog handoff reasons

Revision ID: 20260819_0021
Revises: 20260819_0020
Create Date: 2026-08-19 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0021"
down_revision: str | None = "20260819_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HANDOFF_REASONS_BEFORE = (
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
    "MANUAL_TAKEOVER",
    "OTHER",
)
HANDOFF_REASONS_AFTER = (
    *HANDOFF_REASONS_BEFORE[:-1],
    "TEMPLATE_UNAVAILABLE",
    "CATALOG_NOT_AVAILABLE",
    "OTHER",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def create_constraint(reasons: tuple[str, ...]) -> None:
    op.create_check_constraint(
        "ck_handoff_reason",
        "handoff",
        f"reason IN ({quoted(reasons)})",
    )


def upgrade() -> None:
    op.drop_constraint("ck_handoff_reason", "handoff", type_="check")
    create_constraint(HANDOFF_REASONS_AFTER)


def downgrade() -> None:
    op.execute(
        "UPDATE handoff SET reason = 'OTHER' "
        "WHERE reason IN ('TEMPLATE_UNAVAILABLE', 'CATALOG_NOT_AVAILABLE')"
    )
    op.drop_constraint("ck_handoff_reason", "handoff", type_="check")
    create_constraint(HANDOFF_REASONS_BEFORE)
