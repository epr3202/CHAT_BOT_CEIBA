"""initial webhook tables

Revision ID: 20260810_0001
Revises:
Create Date: 2026-08-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity", sa.String(length=128), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "customer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )
    op.create_index(op.f("ix_customer_phone_number"), "customer", ["phone_number"], unique=False)
    op.create_table(
        "conversation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_customer_id"),
        "conversation",
        ["customer_id"],
        unique=False,
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_message_id"),
    )
    op.create_index(
        op.f("ix_message_conversation_id"),
        "message",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_message_customer_id"), "message", ["customer_id"], unique=False)
    op.create_table(
        "message_provider_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("recipient_id", sa.String(length=64), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_message_id",
            "status",
            "provider_timestamp",
            name="uq_provider_status",
        ),
    )
    op.create_index(
        op.f("ix_message_provider_status_message_id"),
        "message_provider_status",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_provider_status_provider_message_id"),
        "message_provider_status",
        ["provider_message_id"],
        unique=False,
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("recipient_phone_number", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_conversation_id"), "outbox", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_outbox_message_id"), "outbox", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_outbox_message_id"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_conversation_id"), table_name="outbox")
    op.drop_table("outbox")
    op.drop_index(
        op.f("ix_message_provider_status_provider_message_id"),
        table_name="message_provider_status",
    )
    op.drop_index(
        op.f("ix_message_provider_status_message_id"),
        table_name="message_provider_status",
    )
    op.drop_table("message_provider_status")
    op.drop_index(op.f("ix_message_customer_id"), table_name="message")
    op.drop_index(op.f("ix_message_conversation_id"), table_name="message")
    op.drop_table("message")
    op.drop_index(op.f("ix_conversation_customer_id"), table_name="conversation")
    op.drop_table("conversation")
    op.drop_index(op.f("ix_customer_phone_number"), table_name="customer")
    op.drop_table("customer")
    op.drop_table("audit_event")
