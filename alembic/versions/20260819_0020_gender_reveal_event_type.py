"""add gender reveal event type

Revision ID: 20260819_0020
Revises: 20260819_0019
Create Date: 2026-08-19 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0020"
down_revision: str | None = "20260819_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES_BEFORE = (
    "WEDDING",
    "CIVIL_WEDDING",
    "PROPOSAL",
    "BIRTHDAY",
    "GRADUATION",
    "ANNIVERSARY",
    "ROMANTIC_DINNER",
    "CORPORATE_EVENT",
    "FAMILY_EVENT",
    "BAPTISM",
    "FIRST_COMMUNION",
    "BABY_SHOWER",
    "WORKSHOP",
    "POOL_DAY",
    "PRIVATE_DINNER",
    "OTHER",
)
EVENT_TYPES_AFTER = (*EVENT_TYPES_BEFORE[:-1], "GENDER_REVEAL", "OTHER")


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def create_constraints(event_types: tuple[str, ...]) -> None:
    op.create_check_constraint(
        "ck_event_type",
        "event",
        f"event_type IS NULL OR event_type IN ({quoted(event_types)})",
    )
    op.create_check_constraint(
        "ck_catalog_event_type_map_event_type",
        "catalog_event_type_map",
        f"event_type IN ({quoted(event_types)})",
    )


def drop_constraints() -> None:
    op.drop_constraint("ck_event_type", "event", type_="check")
    op.drop_constraint(
        "ck_catalog_event_type_map_event_type",
        "catalog_event_type_map",
        type_="check",
    )


def upgrade() -> None:
    drop_constraints()
    create_constraints(EVENT_TYPES_AFTER)


def downgrade() -> None:
    op.execute(
        "UPDATE event SET event_type = 'OTHER' WHERE event_type = 'GENDER_REVEAL'"
    )
    op.execute(
        "DELETE FROM catalog_event_type_map WHERE event_type = 'GENDER_REVEAL'"
    )
    drop_constraints()
    create_constraints(EVENT_TYPES_BEFORE)
