from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.config.database import Base

DOWNLOAD_STATUSES = (
    "PENDING",
    "DOWNLOADED",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
)
REVIEW_STATUSES = ("PENDING_REVIEW", "ACCEPTED", "REJECTED")


class PaymentEvidence(Base):
    __tablename__ = "payment_evidence"
    __table_args__ = (
        CheckConstraint(
            "download_status IN ("
            "'PENDING', 'DOWNLOADED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT'"
            ")",
            name="ck_payment_evidence_download_status",
        ),
        CheckConstraint(
            "review_status IN ('PENDING_REVIEW', 'ACCEPTED', 'REJECTED')",
            name="ck_payment_evidence_review_status",
        ),
        CheckConstraint(
            "download_attempts >= 0",
            name="ck_payment_evidence_download_attempts_nonnegative",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_payment_evidence_size_nonnegative",
        ),
        Index(
            "ix_payment_evidence_download_due",
            "download_status",
            "next_attempt_at",
        ),
        Index(
            "ix_payment_evidence_review_created",
            "review_status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customer.id"), nullable=False, index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("message.id"), nullable=False, unique=True
    )
    media_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING"
    )
    download_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_REVIEW"
    )
    reviewed_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @validates("download_status")
    def validate_download_status(self, key: str, value: str) -> str:
        del key
        if value not in DOWNLOAD_STATUSES:
            raise ValueError(f"Invalid payment evidence download status: {value}")
        return value

    @validates("review_status")
    def validate_review_status(self, key: str, value: str) -> str:
        del key
        if value not in REVIEW_STATUSES:
            raise ValueError(f"Invalid payment evidence review status: {value}")
        return value
