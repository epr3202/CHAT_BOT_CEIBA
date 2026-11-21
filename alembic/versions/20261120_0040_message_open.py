"""Track visible inbound messages by operator without modifying message history."""

import sqlalchemy as sa

from alembic import op

revision = "20261120_0040"
down_revision = "20261120_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_message_open",
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agent.id"), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("message.id"), primary_key=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_message_open")
