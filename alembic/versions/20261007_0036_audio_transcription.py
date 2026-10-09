"""Append-only WhatsApp audio transcriptions and provider telemetry.

Downgrade deliberately fails if AUDIO_TRANSCRIPTION executions exist: append-only
execution history must never be removed to satisfy the restored task constraint.

Revision ID: 20261007_0036
Revises: 20261002_0035
"""

import sqlalchemy as sa

from alembic import op

revision = "20261007_0036"
down_revision = "20261002_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ai_execution_task", "ai_execution", type_="check")
    op.create_check_constraint(
        "ck_ai_execution_task",
        "ai_execution",
        "task IN ('INTENT_CLASSIFICATION', 'SERVICES_CLASSIFICATION', "
        "'EVENT_TYPE_EXTRACTION', 'RECEIPT_EXTRACTION', 'AUDIO_TRANSCRIPTION')",
    )
    op.create_table(
        "message_transcription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("message.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("is_speech", sa.Boolean(), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("ai_execution_id", sa.Integer(), sa.ForeignKey("ai_execution.id"), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("media_sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("message_id"),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'UNCLEAR', 'FAILED', 'TOO_LONG', 'INVALID_MEDIA')",
            name="ck_message_transcription_status",
        ),
        sa.CheckConstraint(
            "status != 'SUCCESS' OR (transcript IS NOT NULL AND "
            "length(btrim(transcript)) > 0 AND ai_execution_id IS NOT NULL)",
            name="ck_message_transcription_success",
        ),
        sa.CheckConstraint(
            "status NOT IN ('TOO_LONG', 'INVALID_MEDIA') OR ai_execution_id IS NULL",
            name="ck_message_transcription_media_no_execution",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_message_transcription_size"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_message_transcription_duration"
        ),
    )
    op.execute("""
        CREATE FUNCTION reject_message_transcription_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'message_transcription is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER message_transcription_append_only BEFORE UPDATE OR DELETE
        ON message_transcription FOR EACH ROW
        EXECUTE FUNCTION reject_message_transcription_mutation()
    """)


def downgrade() -> None:
    # Fail instead of deleting forensic executions when the old CHECK cannot hold.
    op.drop_constraint("ck_ai_execution_task", "ai_execution", type_="check")
    op.create_check_constraint(
        "ck_ai_execution_task",
        "ai_execution",
        "task IN ('INTENT_CLASSIFICATION', 'SERVICES_CLASSIFICATION', "
        "'EVENT_TYPE_EXTRACTION', 'RECEIPT_EXTRACTION')",
    )
    op.execute("DROP TRIGGER message_transcription_append_only ON message_transcription")
    op.drop_table("message_transcription")
    op.execute("DROP FUNCTION reject_message_transcription_mutation()")
