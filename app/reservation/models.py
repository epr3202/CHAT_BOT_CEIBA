from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.config.database import Base
from app.plan.models import Plan

RESERVATION_STATUSES = ("PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED", "EXPIRED", "CANCELLED")


class Reservation(Base):
    __tablename__ = "reservation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PAYMENT_PENDING', 'PAYMENT_REVIEW', 'RESERVED', 'EXPIRED', 'CANCELLED')",
            name="ck_reservation_status",
        ),
        CheckConstraint(
            "payment_kind IS NULL OR payment_kind IN ('DEPOSIT', 'FULL')",
            name="ck_reservation_payment_kind",
        ),
        CheckConstraint("price_cop > 0", name="ck_reservation_price_positive"),
        CheckConstraint("amount_paid_cop >= 0", name="ck_reservation_paid_nonnegative"),
        CheckConstraint("ends_at > starts_at", name="ck_reservation_time_range"),
        Index("ix_reservation_starts_at_status", "starts_at", "status"),
    )

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan.plan_id"), nullable=False
    )
    plan: Mapped[Plan] = relationship(lazy="raise")
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id"), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PAYMENT_PENDING")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_cop: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid_cop: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    balance_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calendar_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        if value not in RESERVATION_STATUSES:
            raise ValueError(f"Invalid reservation status: {value}")
        return value
