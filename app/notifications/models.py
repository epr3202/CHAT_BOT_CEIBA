from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class NotificationRecipient(Base):
    __tablename__ = "notification_recipient"
    __table_args__ = (
        CheckConstraint(
            "phone_number ~ '^\\+[1-9][0-9]{7,14}$'",
            name="ck_notification_recipient_phone",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    notify_on_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    notify_on_payment_pending: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_message_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StaffOutbox(Base):
    __tablename__ = "staff_outbox"
    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('EVIDENCE_RECEIVED','PAYMENT_PENDING_CREATED',"
            "'TEST','BALANCE_OVERDUE')",
            name="ck_staff_outbox_event_kind",
        ),
        CheckConstraint("message_kind IN ('TEXT','TEMPLATE')", name="ck_staff_outbox_message_kind"),
        CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','DELIVERED','READ',"
            "'FAILED','DEFERRED','EXPIRED')",
            name="ck_staff_outbox_status",
        ),
        UniqueConstraint(
            "recipient_id",
            "event_kind",
            "source_entity",
            "source_id",
            name="uq_staff_outbox_source",
        ),
        Index("ix_staff_outbox_provider_message_id", "provider_message_id"),
        Index(
            "ix_staff_outbox_due",
            "status",
            "next_attempt_at",
            postgresql_where=text("status IN ('PENDING','SENDING')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("notification_recipient.id"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_entity: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    message_kind: Mapped[str | None] = mapped_column(String(16))
    template_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def source(self) -> dict[str, Any]:
        return {"entity": self.source_entity, "id": self.source_id}


class CustomerNotification(Base):
    """Scheduled templates independent of inbound-message and conversation admission."""

    __tablename__ = "customer_notification"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('BALANCE_REMINDER_EARLY','BALANCE_REMINDER_DUE')",
            name="ck_customer_notification_kind",
        ),
        CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','DELIVERED','READ',"
            "'FAILED','DEFERRED','EXPIRED')",
            name="ck_customer_notification_status",
        ),
        UniqueConstraint(
            "reservation_id", "kind", name="uq_customer_notification_reservation_kind"
        ),
        Index("ix_customer_notification_provider_message_id", "provider_message_id"),
        Index(
            "ix_customer_notification_due",
            "status",
            "next_attempt_at",
            postgresql_where=text("status IN ('PENDING','SENDING')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reservation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reservation.reservation_id"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    template_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
