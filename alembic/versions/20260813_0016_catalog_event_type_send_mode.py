"""catalog event type send mode

Revision ID: 20260813_0016
Revises: 20260813_0015
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0016"
down_revision: str | None = "20260813_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_event_type_map",
        sa.Column(
            "send_mode",
            sa.String(length=32),
            server_default="ON_REQUEST",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_catalog_event_type_map_send_mode",
        "catalog_event_type_map",
        "send_mode IN ('PROACTIVE', 'ON_REQUEST')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_catalog_event_type_map_send_mode",
        "catalog_event_type_map",
        type_="check",
    )
    op.drop_column("catalog_event_type_map", "send_mode")
