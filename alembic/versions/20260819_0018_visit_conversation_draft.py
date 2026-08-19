"""visit conversation draft

Revision ID: 20260819_0018
Revises: 20260813_0017
Create Date: 2026-08-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260819_0018"
down_revision: str | None = "20260813_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEAD_STATUSES_BEFORE = "'NEW', 'QUALIFYING', 'QUALIFIED', 'QUOTE_REQUESTED'"
LEAD_STATUSES_AFTER = LEAD_STATUSES_BEFORE + ", 'VISIT_SCHEDULED'"
APPOINTMENT_STATUSES_WITH_LATE_CANCEL = (
    "'PENDING_CONFIRMATION', 'CONFIRMED', 'RESCHEDULED', 'CANCELLED', "
    "'LATE_CANCEL', 'COMPLETED', 'NO_SHOW'"
)


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("visit_draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.drop_constraint("ck_lead_status", "lead", type_="check")
    op.create_check_constraint(
        "ck_lead_status",
        "lead",
        f"lead_status IN ({LEAD_STATUSES_AFTER})",
    )

    # 0017 already admitted LATE_CANCEL. Recreate the constraint explicitly so
    # this migration remains the single normative schema change named by A1.
    op.drop_constraint("ck_appointment_status", "appointment", type_="check")
    op.create_check_constraint(
        "ck_appointment_status",
        "appointment",
        f"appointment_status IN ({APPOINTMENT_STATUSES_WITH_LATE_CANCEL})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_appointment_status", "appointment", type_="check")
    op.create_check_constraint(
        "ck_appointment_status",
        "appointment",
        f"appointment_status IN ({APPOINTMENT_STATUSES_WITH_LATE_CANCEL})",
    )

    op.drop_constraint("ck_lead_status", "lead", type_="check")
    op.create_check_constraint(
        "ck_lead_status",
        "lead",
        f"lead_status IN ({LEAD_STATUSES_BEFORE})",
    )

    op.drop_column("conversation", "visit_draft")
