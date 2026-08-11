from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff

HANDOFF_REASONS = (
    "CUSTOMER_REQUEST",
    "QUOTE_PREPARATION",
    "PRICE_NEGOTIATION",
    "DISCOUNT_REQUEST",
    "PAYMENT_REVIEW",
    "RESERVATION_CONFIRMATION",
    "CANCELLATION",
    "COMPLAINT",
    "LOW_CONFIDENCE",
    "UNSUPPORTED_REQUEST",
    "CAPACITY_REVIEW",
    "SPECIAL_EVENT",
    "SUPPLIER_CONFIRMATION",
    "URGENT_EVENT",
    "SYSTEM_ERROR",
    "REPEATED_NO_SHOW",
    "OTHER",
)

HandoffReason = Literal[
    "CUSTOMER_REQUEST",
    "QUOTE_PREPARATION",
    "PRICE_NEGOTIATION",
    "DISCOUNT_REQUEST",
    "PAYMENT_REVIEW",
    "RESERVATION_CONFIRMATION",
    "CANCELLATION",
    "COMPLAINT",
    "LOW_CONFIDENCE",
    "UNSUPPORTED_REQUEST",
    "CAPACITY_REVIEW",
    "SPECIAL_EVENT",
    "SUPPLIER_CONFIRMATION",
    "URGENT_EVENT",
    "SYSTEM_ERROR",
    "REPEATED_NO_SHOW",
    "OTHER",
]


async def create_handoff(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    reason: str,
    priority: str,
    request_id: str | None,
    settings: Settings,
    detail: str | None = None,
    last_messages_limit: int = 5,
) -> tuple[Handoff, str]:
    normalized_reason = normalize_handoff_reason(reason)
    summary = await build_deterministic_summary(
        session,
        conversation,
        customer,
        normalized_reason,
        detail=detail,
        last_messages_limit=last_messages_limit,
    )
    handoff = Handoff(
        conversation_id=conversation.id,
        reason=normalized_reason,
        priority=priority,
        summary=summary,
        status="PENDING",
    )
    session.add(handoff)
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action="HANDOFF_CREATED",
            entity="handoff",
            old_value=None,
            new_value={
                "conversation_id": conversation.id,
                "reason": normalized_reason,
                "detail": detail,
                "priority": priority,
            },
            reason=normalized_reason,
            request_id=request_id,
        )
    )
    conversation.pending_action = "WAIT_FOR_HUMAN"
    if conversation.state != ConversationState.WAITING_FOR_HUMAN.value:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_HUMAN,
            actor="SYSTEM",
            reason=normalized_reason,
        )
    return handoff, handoff_response_code(settings)


async def build_deterministic_summary(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    reason: str,
    detail: str | None,
    last_messages_limit: int,
) -> str:
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(last_messages_limit)
    )
    messages = list(reversed(result.all()))
    lines = [
        f"Cliente: {customer.full_name or 'Sin nombre confirmado'}",
        f"Telefono: {customer.phone_number}",
        f"Conversacion: {conversation.id}",
        f"Motivo: {reason}" + (f" - {detail}" if detail else ""),
        "Ultimos mensajes:",
    ]
    for message in messages:
        lines.append(f"- {message.direction}: {message_text(message.content)}")
    return "\n".join(lines)


def message_text(content: dict[str, Any]) -> str:
    text = content.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return "[mensaje no textual]"


def normalize_handoff_reason(reason: str) -> str:
    if reason in HANDOFF_REASONS:
        return reason
    return "OTHER"


def handoff_response_code(settings: Settings, now: datetime | None = None) -> str:
    if is_human_business_hours(settings, now=now):
        return "RESP-HANDOFF-001"
    return "RESP-HANDOFF-002"


def is_human_business_hours(settings: Settings, now: datetime | None = None) -> bool:
    local_now = now or datetime.now(ZoneInfo("America/Bogota"))
    local_time = local_now.time()
    days = {int(day.strip()) for day in settings.human_hours_days.split(",") if day.strip()}
    start = time.fromisoformat(settings.human_hours_start)
    end = time.fromisoformat(settings.human_hours_end)
    # Slice 1 limitation: Colombian holidays are not evaluated here. Slice 3 moves this
    # rule to Configuration with the holiday provider described in docs/product/scope.md.
    return local_now.weekday() in days and start <= local_time < end
