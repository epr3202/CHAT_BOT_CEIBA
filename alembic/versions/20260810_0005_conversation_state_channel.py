"""conversation state and channel constraints

Revision ID: 20260810_0005
Revises: 20260810_0004
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0005"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONVERSATION_STATES = (
    "NEW",
    "BOT_ACTIVE",
    "ANSWERING_INFORMATION",
    "COLLECTING_EVENT_DATA",
    "QUOTE_REQUEST_READY",
    "WAITING_FOR_APPOINTMENT_DATE",
    "WAITING_FOR_APPOINTMENT_SELECTION",
    "APPOINTMENT_PENDING_CONFIRMATION",
    "APPOINTMENT_CONFIRMED",
    "WAITING_FOR_HUMAN",
    "HUMAN_ACTIVE",
    "RETURNED_TO_BOT",
    "RESOLVED",
    "CLOSED",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.alter_column(
        "conversation",
        "status",
        new_column_name="state",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.execute("UPDATE conversation SET channel = 'WHATSAPP' WHERE channel = 'whatsapp'")
    op.execute("UPDATE message SET channel = 'WHATSAPP' WHERE channel = 'whatsapp'")
    op.execute("UPDATE outbox SET channel = 'WHATSAPP' WHERE channel = 'whatsapp'")
    op.create_check_constraint(
        "ck_conversation_state",
        "conversation",
        f"state IN ({quoted(CONVERSATION_STATES)})",
    )
    op.create_check_constraint(
        "ck_conversation_channel",
        "conversation",
        "channel IN ('WHATSAPP')",
    )
    op.create_check_constraint("ck_message_channel", "message", "channel IN ('WHATSAPP')")
    op.create_check_constraint("ck_outbox_channel", "outbox", "channel IN ('WHATSAPP')")


def downgrade() -> None:
    op.drop_constraint("ck_outbox_channel", "outbox", type_="check")
    op.drop_constraint("ck_message_channel", "message", type_="check")
    op.drop_constraint("ck_conversation_channel", "conversation", type_="check")
    op.drop_constraint("ck_conversation_state", "conversation", type_="check")
    op.execute("UPDATE outbox SET channel = 'whatsapp' WHERE channel = 'WHATSAPP'")
    op.execute("UPDATE message SET channel = 'whatsapp' WHERE channel = 'WHATSAPP'")
    op.execute("UPDATE conversation SET channel = 'whatsapp' WHERE channel = 'WHATSAPP'")
    op.alter_column(
        "conversation",
        "state",
        new_column_name="status",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
