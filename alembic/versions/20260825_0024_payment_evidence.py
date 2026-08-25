"""add payment evidence level-one intake

Revision ID: 20260825_0024
Revises: 20260824_0023
Create Date: 2026-08-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260825_0024"
down_revision: str | None = "20260824_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("declared_sha256", sa.String(length=128), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("verified_sha256", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("download_status", sa.String(length=32), nullable=False),
        sa.Column("download_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_by_agent_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "download_status IN ("
            "'PENDING', 'DOWNLOADED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT'"
            ")",
            name="ck_payment_evidence_download_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING_REVIEW', 'ACCEPTED', 'REJECTED')",
            name="ck_payment_evidence_review_status",
        ),
        sa.CheckConstraint(
            "download_attempts >= 0",
            name="ck_payment_evidence_download_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_payment_evidence_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.lead_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_payment_evidence_message_id"),
    )
    op.create_index(
        "ix_payment_evidence_conversation_id",
        "payment_evidence",
        ["conversation_id"],
    )
    op.create_index("ix_payment_evidence_customer_id", "payment_evidence", ["customer_id"])
    op.create_index("ix_payment_evidence_lead_id", "payment_evidence", ["lead_id"])
    op.create_index(
        "ix_payment_evidence_reviewed_by_agent_id",
        "payment_evidence",
        ["reviewed_by_agent_id"],
    )
    op.create_index(
        "ix_payment_evidence_download_due",
        "payment_evidence",
        ["download_status", "next_attempt_at"],
    )
    op.create_index(
        "ix_payment_evidence_review_created",
        "payment_evidence",
        ["review_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_evidence_review_created", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_download_due", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_reviewed_by_agent_id", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_lead_id", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_customer_id", table_name="payment_evidence")
    op.drop_index("ix_payment_evidence_conversation_id", table_name="payment_evidence")
    op.drop_table("payment_evidence")
