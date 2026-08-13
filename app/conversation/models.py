from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.channel.states import Channel
from app.config.database import Base
from app.conversation.pending_actions import validate_pending_action
from app.conversation.states import ConversationState

if TYPE_CHECKING:
    from app.channel.models import Message
    from app.customer.models import Customer


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        CheckConstraint(
            "state IN ("
            "'NEW', "
            "'BOT_ACTIVE', "
            "'ANSWERING_INFORMATION', "
            "'COLLECTING_EVENT_DATA', "
            "'QUOTE_REQUEST_READY', "
            "'WAITING_FOR_APPOINTMENT_DATE', "
            "'WAITING_FOR_APPOINTMENT_SELECTION', "
            "'APPOINTMENT_PENDING_CONFIRMATION', "
            "'APPOINTMENT_CONFIRMED', "
            "'WAITING_FOR_HUMAN', "
            "'HUMAN_ACTIVE', "
            "'RETURNED_TO_BOT', "
            "'RESOLVED', "
            "'CLOSED'"
            ")",
            name="ck_conversation_state",
        ),
        CheckConstraint("channel IN ('WHATSAPP')", name="ck_conversation_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    pending_confirmation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_question_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), index=True, nullable=True
    )
    failed_understanding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent.id"), index=True, nullable=True
    )

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")

    @validates("state")
    def validate_state(self, key: str, state: str | ConversationState) -> str:
        return ConversationState(state).value

    @validates("channel")
    def validate_channel(self, key: str, channel: str | Channel) -> str:
        return Channel(channel).value

    @validates("pending_action")
    def validate_pending_action_value(self, key: str, value: str | None) -> str | None:
        return validate_pending_action(value)


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entry"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'INACTIVE')",
            name="ck_knowledge_entry_status",
        ),
        UniqueConstraint("code", "version", name="uq_knowledge_entry_code_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    question_summary: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_template: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_variables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at_version: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("status")
    def validate_status(self, key: str, status: str) -> str:
        if status not in {"DRAFT", "APPROVED", "INACTIVE"}:
            raise ValueError(f"Invalid knowledge status: {status}")
        return status
