from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.channel.states import Channel
from app.config.database import Base

LEAD_STATUSES = ("NEW", "QUALIFYING", "QUALIFIED", "QUOTE_REQUESTED")
BUDGET_RANGES = ("NOT_PROVIDED", "BELOW_REFERENCE", "REFERENCE_RANGE", "PREMIUM", "CUSTOM")
BUDGET_DATA_STATUSES = (
    "NOT_ASKED",
    "ASKED_PENDING",
    "PROVIDED",
    "DECLINED",
    "RANGE_PROVIDED",
    "CORRECTED",
)


class Lead(Base):
    __tablename__ = "lead"
    __table_args__ = (
        CheckConstraint(
            "lead_status IN ('NEW', 'QUALIFYING', 'QUALIFIED', 'QUOTE_REQUESTED')",
            name="ck_lead_status",
        ),
        CheckConstraint("channel IN ('WHATSAPP')", name="ck_lead_channel"),
        CheckConstraint(
            "budget_range IN ("
            "'NOT_PROVIDED', 'BELOW_REFERENCE', 'REFERENCE_RANGE', 'PREMIUM', 'CUSTOM'"
            ")",
            name="ck_lead_budget_range",
        ),
        CheckConstraint(
            "budget_data_status IN ("
            "'NOT_ASKED', 'ASKED_PENDING', 'PROVIDED', 'DECLINED', "
            "'RANGE_PROVIDED', 'CORRECTED'"
            ")",
            name="ck_lead_budget_data_status",
        ),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True, nullable=False)
    lead_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    budget_range: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_PROVIDED")
    budget_data_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_ASKED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @validates("lead_status")
    def validate_lead_status(self, key: str, value: str) -> str:
        if value not in LEAD_STATUSES:
            raise ValueError(f"Invalid lead_status: {value}")
        return value

    @validates("channel")
    def validate_channel(self, key: str, value: str | Channel) -> str:
        return Channel(value).value

    @validates("budget_range")
    def validate_budget_range(self, key: str, value: str) -> str:
        if value not in BUDGET_RANGES:
            raise ValueError(f"Invalid budget_range: {value}")
        return value

    @validates("budget_data_status")
    def validate_budget_data_status(self, key: str, value: str) -> str:
        if value not in BUDGET_DATA_STATUSES:
            raise ValueError(f"Invalid budget_data_status: {value}")
        return value
