from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class AIExecution(Base):
    __tablename__ = "ai_execution"
    __table_args__ = (
        CheckConstraint(
            "task IN ('INTENT_CLASSIFICATION', 'SERVICES_CLASSIFICATION', 'EVENT_TYPE_EXTRACTION')",
            name="ck_ai_execution_task",
        ),
        CheckConstraint(
            "validation_status IN ('VALID', 'NORMALIZED', 'INVALID_SCHEMA', "
            "'DISCARDED', 'HTTP_ERROR')",
            name="ck_ai_execution_validation_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id"),
        index=True,
        nullable=True,
    )
    input_character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
