"""Link an event to its optional fixed-price plan.

Revision ID: 20260930_0029
Revises: 20260930_0028
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0029"
down_revision = "20260930_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event", sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_event_plan", "event", "plan", ["plan_id"], ["plan_id"])
    op.create_index("ix_event_plan_id", "event", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_event_plan_id", table_name="event")
    op.drop_constraint("fk_event_plan", "event", type_="foreignkey")
    op.drop_column("event", "plan_id")
