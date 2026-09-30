from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.config.database import Base

PLAN_EVENT_TYPES = ("ROMANTIC_DINNER", "PROPOSAL")


class Plan(Base):
    __tablename__ = "plan"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('ROMANTIC_DINNER', 'PROPOSAL')", name="ck_plan_event_type"
        ),
        CheckConstraint("price_cop > 0", name="ck_plan_price_positive"),
        CheckConstraint("duration_minutes > 0", name="ck_plan_duration_positive"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    price_cop: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    exclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    weekend_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @validates("event_type")
    def validate_event_type(self, key: str, value: str) -> str:
        if value not in PLAN_EVENT_TYPES:
            raise ValueError(f"Invalid plan event_type: {value}")
        return value
