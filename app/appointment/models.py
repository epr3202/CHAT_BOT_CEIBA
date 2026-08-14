from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Time, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.config.database import Base

APPOINTMENT_TYPES = ("VISIT",)
APPOINTMENT_STATUSES = (
    "PENDING_CONFIRMATION",
    "CONFIRMED",
    "RESCHEDULED",
    "CANCELLED",
    "LATE_CANCEL",
    "COMPLETED",
    "NO_SHOW",
)
ACTIVE_APPOINTMENT_STATUSES = ("PENDING_CONFIRMATION", "CONFIRMED", "RESCHEDULED")
HOLIDAY_SOURCES = ("SEEDED", "MANUAL")
APPOINTMENT_CHANGE_ACTORS = ("SYSTEM", "CUSTOMER", "AGENT", "BUSINESS_MANAGER")
VISIT_TIMEZONE = "America/Bogota"
VISIT_DURATION_MINUTES = 45


def calculate_visit_end_time(start_time: time) -> time:
    anchor = datetime.combine(datetime.min.date(), start_time)
    return (anchor + timedelta(minutes=VISIT_DURATION_MINUTES)).time()


class Appointment(Base):
    __tablename__ = "appointment"
    __table_args__ = (
        CheckConstraint("appointment_type IN ('VISIT')", name="ck_appointment_type"),
        CheckConstraint(
            "appointment_status IN ("
            "'PENDING_CONFIRMATION', "
            "'CONFIRMED', "
            "'RESCHEDULED', "
            "'CANCELLED', "
            "'LATE_CANCEL', "
            "'COMPLETED', "
            "'NO_SHOW'"
            ")",
            name="ck_appointment_status",
        ),
        CheckConstraint(
            "start_time IN ('08:00:00', '09:00:00', '10:00:00', '11:00:00')",
            name="ck_appointment_start_time",
        ),
        CheckConstraint("attendee_count BETWEEN 1 AND 3", name="ck_appointment_attendees"),
        CheckConstraint("reschedule_count >= 0", name="ck_appointment_reschedule_count"),
        CheckConstraint("timezone = 'America/Bogota'", name="ck_appointment_timezone"),
        CheckConstraint(
            "appointment_status != 'CONFIRMED' OR external_calendar_id IS NOT NULL",
            name="ck_appointment_confirmed_external_calendar",
        ),
        Index(
            "uq_appointment_active_slot",
            "appointment_date",
            "start_time",
            unique=True,
            postgresql_where=text(
                "appointment_status IN "
                "('PENDING_CONFIRMATION', 'CONFIRMED', 'RESCHEDULED')"
            ),
        ),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True, nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), index=True, nullable=True
    )
    appointment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="VISIT")
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=VISIT_TIMEZONE)
    attendee_count: Mapped[int] = mapped_column(nullable=False)
    visitor_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    visit_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    appointment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_CONFIRMATION"
    )
    assigned_manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent.id"), index=True, nullable=True
    )
    external_calendar_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    reminder_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reschedule_count: Mapped[int] = mapped_column(nullable=False, default=0)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    no_show_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    internal_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    requires_reconciliation: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __init__(self, **kwargs: Any) -> None:
        if "end_time" not in kwargs and "start_time" in kwargs:
            kwargs["end_time"] = calculate_visit_end_time(kwargs["start_time"])
        if "timezone" not in kwargs:
            kwargs["timezone"] = VISIT_TIMEZONE
        super().__init__(**kwargs)

    @validates("appointment_type")
    def validate_appointment_type(self, key: str, value: str) -> str:
        if value not in APPOINTMENT_TYPES:
            raise ValueError(f"Invalid appointment_type: {value}")
        return value

    @validates("appointment_status")
    def validate_appointment_status(self, key: str, value: str) -> str:
        if value not in APPOINTMENT_STATUSES:
            raise ValueError(f"Invalid appointment_status: {value}")
        return value

    @validates("start_time")
    def validate_start_time(self, key: str, value: time) -> time:
        if value not in {time(8), time(9), time(10), time(11)}:
            raise ValueError(f"Invalid appointment start_time: {value}")
        self.end_time = calculate_visit_end_time(value)
        return value

    @validates("timezone")
    def validate_timezone(self, key: str, value: str) -> str:
        if value != VISIT_TIMEZONE:
            raise ValueError(f"Invalid appointment timezone: {value}")
        return value


class AppointmentChange(Base):
    __tablename__ = "appointment_change"
    __table_args__ = (
        CheckConstraint(
            "changed_by_type IN ('SYSTEM', 'CUSTOMER', 'AGENT', 'BUSINESS_MANAGER')",
            name="ck_appointment_change_actor",
        ),
    )

    appointment_change_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointment.appointment_id"), index=True, nullable=False
    )
    previous_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    new_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_id: Mapped[str] = mapped_column(String(128), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("changed_by_type")
    def validate_changed_by_type(self, key: str, value: str) -> str:
        if value not in APPOINTMENT_CHANGE_ACTORS:
            raise ValueError(f"Invalid appointment change actor: {value}")
        return value


class Holiday(Base):
    __tablename__ = "holiday"
    __table_args__ = (
        CheckConstraint("source IN ('SEEDED', 'MANUAL')", name="ck_holiday_source"),
    )

    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @validates("source")
    def validate_source(self, key: str, value: str) -> str:
        if value not in HOLIDAY_SOURCES:
            raise ValueError(f"Invalid holiday source: {value}")
        return value


class BlockedDate(Base):
    __tablename__ = "blocked_date"

    blocked_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
