"""Append-only transcription results anchored to the original inbound message."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class MessageTranscription(Base):
    __tablename__ = "message_transcription"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCESS', 'UNCLEAR', 'FAILED', 'TOO_LONG', 'INVALID_MEDIA')",
            name="ck_message_transcription_status",
        ),
        CheckConstraint(
            "status != 'SUCCESS' OR (transcript IS NOT NULL AND "
            "length(btrim(transcript)) > 0 AND ai_execution_id IS NOT NULL)",
            name="ck_message_transcription_success",
        ),
        CheckConstraint(
            "status NOT IN ('TOO_LONG', 'INVALID_MEDIA') OR ai_execution_id IS NULL",
            name="ck_message_transcription_media_no_execution",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="ck_message_transcription_size"
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_message_transcription_duration"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("message.id"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_speech: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_execution.id"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
