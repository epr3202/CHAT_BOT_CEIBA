"""Track inbox work independently of history; no historical completion backfill."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0026"
down_revision: str | None = "20260908_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("webhook_event", sa.Column("intake_version", sa.Integer(), nullable=True))
    op.add_column(
        "webhook_event",
        sa.Column("ingest_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "webhook_event", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_webhook_event_intake_due",
        "webhook_event",
        ["intake_version", "status", "next_attempt_at", "id"],
    )
    op.create_table(
        "inbox_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("message.id"), nullable=False),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(128), nullable=True),
        sa.Column("completion_reason", sa.String(128), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("external_operation", sa.String(128), nullable=True),
        sa.Column("external_result", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("message_id", name="uq_inbox_job_message"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','EXTERNAL','COMPLETED','FAILED','REVIEW')",
            name="ck_inbox_job_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_inbox_job_attempts"),
        sa.CheckConstraint(
            "(status IN ('PROCESSING','EXTERNAL') AND claim_token IS NOT NULL) OR "
            "(status NOT IN ('PROCESSING','EXTERNAL') AND claim_token IS NULL)",
            name="ck_inbox_job_owner",
        ),
    )
    op.create_index("ix_inbox_job_due", "inbox_job", ["status", "next_attempt_at", "id"])
    op.create_index(
        "ix_inbox_job_conversation_order", "inbox_job", ["conversation_id", "id", "status"]
    )
    op.create_index("ix_inbox_job_stale", "inbox_job", ["status", "claimed_at"])


def downgrade() -> None:
    # Destructive to completion evidence: prefer retaining this data operationally.
    op.drop_table("inbox_job")
    op.drop_index("ix_webhook_event_intake_due", table_name="webhook_event")
    op.drop_column("webhook_event", "next_attempt_at")
    op.drop_column("webhook_event", "ingest_attempts")
    op.drop_column("webhook_event", "intake_version")
