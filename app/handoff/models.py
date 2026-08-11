from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class Handoff(Base):
    __tablename__ = "handoff"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'TAKEN', 'RETURNED', 'RESOLVED')",
            name="ck_handoff_status",
        ),
        CheckConstraint(
            "reason IN ("
            "'CUSTOMER_REQUEST', 'QUOTE_PREPARATION', 'PRICE_NEGOTIATION', "
            "'DISCOUNT_REQUEST', 'PAYMENT_REVIEW', 'RESERVATION_CONFIRMATION', "
            "'CANCELLATION', 'COMPLAINT', 'LOW_CONFIDENCE', 'UNSUPPORTED_REQUEST', "
            "'CAPACITY_REVIEW', 'SPECIAL_EVENT', 'SUPPLIER_CONFIRMATION', "
            "'URGENT_EVENT', 'SYSTEM_ERROR', 'REPEATED_NO_SHOW', 'OTHER'"
            ")",
            name="ck_handoff_reason",
        ),
        CheckConstraint(
            "priority IN ('NORMAL', 'URGENT', 'CRITICAL')",
            name="ck_handoff_priority",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
