"""Plan notice override and historical commercial details.

Existing plans inherit the configured BOOKING_MIN_LEAD_DAYS until explicitly edited.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261120_0039"
down_revision = "20261114_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("min_lead_days", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_plan_min_lead_days", "plan", "min_lead_days >= 0")
    op.add_column("reservation", sa.Column("commercial_details", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reservation", "commercial_details")
    op.drop_constraint("ck_plan_min_lead_days", "plan", type_="check")
    op.drop_column("plan", "min_lead_days")
