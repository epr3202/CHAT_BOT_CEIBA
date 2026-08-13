from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.config.database import Base

QUOTE_REQUEST_STATUSES = ("DRAFT", "READY")


class QuoteRequest(Base):
    __tablename__ = "quote_request"
    __table_args__ = (
        CheckConstraint(
            "request_status IN ('DRAFT', 'READY')",
            name="ck_quote_request_status",
        ),
    )

    quote_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), index=True, nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), index=True, nullable=False
    )
    request_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    minimum_data_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    date_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("request_status")
    def validate_request_status(self, key: str, value: str) -> str:
        if value not in QUOTE_REQUEST_STATUSES:
            raise ValueError(f"Invalid request_status: {value}")
        return value
