"""Append-only receipt proposals and vision execution telemetry.

The ai_execution task CHECK extension is intentionally irreversible: downgrading
removes the review schema only, preserving append-only RECEIPT_EXTRACTION rows
and the expanded CHECK required to keep those historical executions valid.

Revision ID: 20260930_0033
Revises: 20260930_0032
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0033"
down_revision = "20260930_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ai_execution_task", "ai_execution", type_="check")
    op.create_check_constraint(
        "ck_ai_execution_task",
        "ai_execution",
        "task IN ('INTENT_CLASSIFICATION', 'SERVICES_CLASSIFICATION', "
        "'EVENT_TYPE_EXTRACTION', 'RECEIPT_EXTRACTION')",
    )
    op.create_table(
        "payment_evidence_review",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evidence_id", sa.Integer(), sa.ForeignKey("payment_evidence.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("extracted", postgresql.JSONB(), nullable=True),
        sa.Column("checks", postgresql.JSONB(), nullable=False),
        sa.Column("suggestion", sa.String(16), nullable=False),
        sa.Column("suggested_amount_cop", sa.Integer(), nullable=True),
        sa.Column("ai_execution_id", sa.Integer(), sa.ForeignKey("ai_execution.id"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'FAILED', 'SKIPPED')",
            name="ck_payment_evidence_review_attempt_status",
        ),
        sa.CheckConstraint(
            "suggestion IN ('ACCEPT', 'REVIEW', 'REJECT')",
            name="ck_payment_evidence_review_suggestion",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_payment_evidence_review_attempt_number"),
        sa.CheckConstraint(
            "suggested_amount_cop IS NULL OR suggested_amount_cop > 0",
            name="ck_payment_evidence_review_amount",
        ),
    )
    op.create_index(
        "ix_payment_evidence_review_evidence_id", "payment_evidence_review", ["evidence_id"]
    )
    op.execute("""
        CREATE FUNCTION reject_payment_review_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'payment_evidence_review is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER payment_review_append_only BEFORE UPDATE OR DELETE
        ON payment_evidence_review FOR EACH ROW EXECUTE FUNCTION reject_payment_review_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER payment_review_append_only ON payment_evidence_review")
    op.drop_index("ix_payment_evidence_review_evidence_id", table_name="payment_evidence_review")
    op.drop_table("payment_evidence_review")
    op.execute("DROP FUNCTION reject_payment_review_mutation()")
