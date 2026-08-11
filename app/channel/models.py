from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.channel.states import Channel
from app.config.database import Base

if TYPE_CHECKING:
    from app.conversation.models import Conversation
    from app.customer.models import Customer


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (CheckConstraint("channel IN ('WHATSAPP')", name="ck_message_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), index=True, nullable=False
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provider_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    customer: Mapped[Customer] = relationship(back_populates="messages")
    outbox_items: Mapped[list[Outbox]] = relationship(back_populates="message")

    @validates("channel")
    def validate_channel(self, key: str, channel: str | Channel) -> str:
        return Channel(channel).value


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("channel IN ('WHATSAPP')", name="ck_outbox_channel"),
        Index("ix_outbox_status_next_attempt_at", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), index=True, nullable=False
    )
    message_id: Mapped[int] = mapped_column(ForeignKey("message.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[Message] = relationship(back_populates="outbox_items")

    @validates("channel")
    def validate_channel(self, key: str, channel: str | Channel) -> str:
        return Channel(channel).value


class MessageProviderStatus(Base):
    __tablename__ = "message_provider_status"
    __table_args__ = (
        UniqueConstraint(
            "provider_message_id",
            "status",
            "provider_timestamp",
            name="uq_provider_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("message.id"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_event"
    __table_args__ = (Index("ix_webhook_event_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="META_WHATSAPP"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
