from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.config.database import Base

EVENT_TYPES = (
    "WEDDING",
    "CIVIL_WEDDING",
    "PROPOSAL",
    "BIRTHDAY",
    "GRADUATION",
    "ANNIVERSARY",
    "ROMANTIC_DINNER",
    "CORPORATE_EVENT",
    "FAMILY_EVENT",
    "BAPTISM",
    "FIRST_COMMUNION",
    "BABY_SHOWER",
    "WORKSHOP",
    "POOL_DAY",
    "PRIVATE_DINNER",
    "GENDER_REVEAL",
    "OTHER",
)
EVENT_DATE_TYPES = ("EXACT", "APPROXIMATE", "FLEXIBLE", "UNKNOWN")
GUEST_COUNT_STATUSES = ("PROVIDED", "RANGE", "ESTIMATED")
SERVICE_REQUEST_STATUSES = ("REQUESTED", "REMOVED")


class Event(Base):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint(
            "event_type IS NULL OR event_type IN ("
            "'WEDDING', 'CIVIL_WEDDING', 'PROPOSAL', 'BIRTHDAY', 'GRADUATION', "
            "'ANNIVERSARY', 'ROMANTIC_DINNER', 'CORPORATE_EVENT', 'FAMILY_EVENT', "
            "'BAPTISM', 'FIRST_COMMUNION', 'BABY_SHOWER', 'WORKSHOP', 'POOL_DAY', "
            "'PRIVATE_DINNER', 'GENDER_REVEAL', 'OTHER'"
            ")",
            name="ck_event_type",
        ),
        CheckConstraint(
            "event_date_type IS NULL OR event_date_type IN "
            "('EXACT', 'APPROXIMATE', 'FLEXIBLE', 'UNKNOWN')",
            name="ck_event_date_type",
        ),
        CheckConstraint(
            "guest_count_status IS NULL OR guest_count_status IN "
            "('PROVIDED', 'RANGE', 'ESTIMATED')",
            name="ck_event_guest_count_status",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), index=True, nullable=False
    )
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type_other: Mapped[str | None] = mapped_column(String(150), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    event_date_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_date_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guest_count_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guest_count_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guest_count_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @validates("event_type")
    def validate_event_type(self, key: str, value: str | None) -> str | None:
        if value is not None and value not in EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {value}")
        return value

    @validates("event_date_type")
    def validate_event_date_type(self, key: str, value: str | None) -> str | None:
        if value is not None and value not in EVENT_DATE_TYPES:
            raise ValueError(f"Invalid event_date_type: {value}")
        return value

    @validates("guest_count_status")
    def validate_guest_count_status(self, key: str, value: str | None) -> str | None:
        if value is not None and value not in GUEST_COUNT_STATUSES:
            raise ValueError(f"Invalid guest_count_status: {value}")
        return value


class EventServiceRequest(Base):
    __tablename__ = "event_service_request"
    __table_args__ = (
        CheckConstraint(
            "status IN ('REQUESTED', 'REMOVED')",
            name="ck_event_service_request_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event.event_id"), index=True, nullable=False
    )
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="REQUESTED")
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        if value not in SERVICE_REQUEST_STATUSES:
            raise ValueError(f"Invalid service request status: {value}")
        return value
