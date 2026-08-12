from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff

router = APIRouter(prefix="/admin", tags=["admin"])


class TakeHandoffRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=128)


class ReturnHandoffRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=500)


class AgentMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ConversationMessagePayload(BaseModel):
    id: str
    direction: Literal["INBOUND", "OUTBOUND"]
    body: str
    message_type: str
    status: str | None = None
    created_at: datetime


class ConversationPayload(BaseModel):
    conversation_id: int
    customer_name: str | None
    customer_phone: str | None
    state: str
    last_intent: str | None
    pending_action: str | None
    bot_enabled: bool
    handoff_id: int | None
    handoff_status: str | None
    assigned_to: str | None
    handoff_reason: str | None
    handoff_priority: str | None
    last_message_body: str | None
    last_message_direction: str | None
    last_message_at: datetime | None


async def require_admin_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings: Settings = request.app.state.settings
    expected = settings.admin_api_token.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API token is not configured",
        )
    provided = (authorization or "").removeprefix("Bearer ")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


AdminAuth = Annotated[None, Depends(require_admin_token)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
HandoffListStatus = Literal["PENDING", "TAKEN", "RETURNED"]


@router.get("/handoffs")
async def list_handoffs(
    _auth: AdminAuth,
    session: DbSession,
    status: HandoffListStatus = "PENDING",
) -> list[dict[str, object]]:
    result = await session.execute(
        select(Handoff, Customer)
        .join(Conversation, Handoff.conversation_id == Conversation.id)
        .join(Customer, Conversation.customer_id == Customer.id)
        .where(Handoff.status == status)
        .order_by(Handoff.created_at.asc())
    )
    return [handoff_payload(handoff, customer) for handoff, customer in result.all()]


@router.get("/conversations")
async def list_conversations(
    _auth: AdminAuth,
    session: DbSession,
) -> list[ConversationPayload]:
    result = await session.execute(
        select(Conversation, Customer)
        .join(Customer, Conversation.customer_id == Customer.id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
    )
    conversations = result.all()
    payloads: list[ConversationPayload] = []
    for conversation, customer in conversations:
        handoff = await latest_handoff_for_conversation(session, conversation.id)
        latest_message = await latest_message_for_conversation(session, conversation.id)
        payloads.append(
            ConversationPayload(
                conversation_id=conversation.id,
                customer_name=customer.full_name,
                customer_phone=customer.phone_number,
                state=conversation.state,
                last_intent=conversation.last_intent,
                pending_action=conversation.pending_action,
                bot_enabled=conversation.bot_enabled,
                handoff_id=handoff.id if handoff is not None else None,
                handoff_status=handoff.status if handoff is not None else None,
                assigned_to=handoff.assigned_to if handoff is not None else None,
                handoff_reason=handoff.reason if handoff is not None else None,
                handoff_priority=handoff.priority if handoff is not None else None,
                last_message_body=message_body(latest_message)
                if latest_message is not None
                else None,
                last_message_direction=latest_message.direction
                if latest_message is not None
                else None,
                last_message_at=conversation.last_message_at,
            )
        )
    return payloads


@router.post("/handoffs/{handoff_id}/take")
async def take_handoff(
    handoff_id: int,
    body: TakeHandoffRequest,
    _auth: AdminAuth,
    session: DbSession,
) -> dict[str, object]:
    async with session.begin():
        handoff = await session.get(Handoff, handoff_id, with_for_update=True)
        if handoff is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
        if handoff.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Handoff is not pending",
            )

        conversation = await session.get(
            Conversation,
            handoff.conversation_id,
            with_for_update=True,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.WAITING_FOR_HUMAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not waiting for human",
            )
        customer = await session.get(Customer, conversation.customer_id)

        now = datetime.now(UTC)
        handoff.status = "TAKEN"
        handoff.assigned_to = body.agent
        handoff.taken_at = now
        conversation.bot_enabled = False
        await transition_conversation(
            session,
            conversation,
            ConversationState.HUMAN_ACTIVE,
            actor=body.agent,
            reason="Handoff taken by human agent",
        )
        session.add(
            AuditEvent(
                actor=body.agent,
                action="HANDOFF_TAKEN",
                entity="handoff",
                old_value={"status": "PENDING"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "TAKEN",
                    "assigned_to": body.agent,
                },
                reason="Human agent took handoff",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/conversations/{conversation_id}/take")
async def take_conversation(
    conversation_id: int,
    body: TakeHandoffRequest,
    _auth: AdminAuth,
    session: DbSession,
) -> dict[str, object]:
    async with session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        customer = await session.get(Customer, conversation.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation has no customer",
            )

        now = datetime.now(UTC)
        handoff = await latest_handoff_for_conversation(session, conversation.id, locked=True)
        old_value = takeover_old_value(conversation, handoff)
        if handoff is None or handoff.status in {"RETURNED", "RESOLVED"}:
            handoff = Handoff(
                conversation_id=conversation.id,
                reason="OTHER",
                priority="NORMAL",
                summary=await build_manual_takeover_summary(session, conversation, customer),
                status="TAKEN",
                assigned_to=body.agent,
                taken_at=now,
            )
            session.add(handoff)
        else:
            handoff.status = "TAKEN"
            handoff.assigned_to = body.agent
            handoff.taken_at = handoff.taken_at or now

        conversation.bot_enabled = False
        conversation.pending_action = "WAIT_FOR_HUMAN"
        await move_conversation_to_human_active(
            session,
            conversation,
            actor=body.agent,
            reason="Manual admin takeover",
        )
        await session.flush()
        session.add(
            AuditEvent(
                actor=body.agent,
                action="CONVERSATION_MANUAL_TAKEOVER",
                entity="conversation",
                old_value=old_value,
                new_value={
                    "conversation_id": conversation.id,
                    "handoff_id": handoff.id,
                    "state": ConversationState.HUMAN_ACTIVE.value,
                    "bot_enabled": False,
                    "assigned_to": body.agent,
                },
                reason="Admin manually took conversation",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/handoffs/{handoff_id}/return")
async def return_handoff(
    handoff_id: int,
    body: ReturnHandoffRequest,
    _auth: AdminAuth,
    session: DbSession,
) -> dict[str, object]:
    async with session.begin():
        handoff = await session.get(Handoff, handoff_id, with_for_update=True)
        if handoff is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
        if handoff.status != "TAKEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Handoff is not taken",
            )

        conversation = await session.get(
            Conversation,
            handoff.conversation_id,
            with_for_update=True,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not human active",
            )
        customer = await session.get(Customer, conversation.customer_id)

        handoff.status = "RETURNED"
        handoff.resolved_at = datetime.now(UTC)
        conversation.bot_enabled = True
        conversation.pending_action = None
        await transition_conversation(
            session,
            conversation,
            ConversationState.RETURNED_TO_BOT,
            actor=handoff.assigned_to or "ADMIN",
            reason=body.resolution,
        )
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor=handoff.assigned_to or "ADMIN",
            reason="Returned to bot after human handling",
        )
        session.add(
            AuditEvent(
                actor=handoff.assigned_to or "ADMIN",
                action="HANDOFF_RETURNED",
                entity="handoff",
                old_value={"status": "TAKEN"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "RETURNED",
                },
                reason=body.resolution,
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/conversations/{conversation_id}/messages")
async def create_agent_message(
    conversation_id: int,
    body: AgentMessageRequest,
    _auth: AdminAuth,
    session: DbSession,
) -> dict[str, int | str]:
    async with session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not human active",
            )

        customer = await session.get(Customer, conversation.customer_id)
        latest_message = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        if customer is None or latest_message is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation cannot receive agent messages",
            )

        outbox = Outbox(
            conversation_id=conversation.id,
            message_id=latest_message.id,
            channel=Channel.WHATSAPP,
            recipient_phone_number=customer.phone_number,
            payload={
                "type": "text",
                "text": {"body": body.text},
                "agent": True,
            },
            status="PENDING",
        )
        session.add(outbox)
        active_handoff = await session.scalar(
            select(Handoff)
            .where(
                Handoff.conversation_id == conversation.id,
                Handoff.status == "TAKEN",
            )
            .order_by(Handoff.id.desc())
            .limit(1)
        )
        if active_handoff is not None:
            active_handoff.summary = append_handoff_summary_line(
                active_handoff.summary,
                "OUTBOUND",
                body.text,
            )
        await session.flush()
        session.add(
            AuditEvent(
                actor="ADMIN",
                action="AGENT_MESSAGE_ENQUEUED",
                entity="outbox",
                old_value=None,
                new_value={
                    "conversation_id": conversation.id,
                    "outbox_id": outbox.id,
                },
                reason="Human agent message queued through admin API",
                request_id=None,
            )
        )

    return {"outbox_id": outbox.id, "status": outbox.status}


@router.get("/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    conversation_id: int,
    _auth: AdminAuth,
    session: DbSession,
) -> list[ConversationMessagePayload]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    message_rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    messages = [
        ConversationMessagePayload(
            id=f"message-{message.id}",
            direction=message_direction(message),
            body=message_body(message),
            message_type=message.message_type,
            status=None,
            created_at=message.created_at,
        )
        for message in message_rows.all()
    ]

    pending_outbox_rows = await session.scalars(
        select(Outbox)
        .where(
            Outbox.conversation_id == conversation_id,
            Outbox.status != "SENT",
        )
        .order_by(Outbox.created_at.asc(), Outbox.id.asc())
    )
    messages.extend(
        ConversationMessagePayload(
            id=f"outbox-{outbox.id}",
            direction="OUTBOUND",
            body=outbox_body(outbox),
            message_type=str(outbox.payload.get("type", "text")),
            status=outbox.status,
            created_at=outbox.created_at,
        )
        for outbox in pending_outbox_rows.all()
    )
    return sorted(messages, key=lambda message: (message.created_at, message.id))


async def latest_handoff_for_conversation(
    session: AsyncSession,
    conversation_id: int,
    *,
    locked: bool = False,
) -> Handoff | None:
    statement = (
        select(Handoff)
        .where(Handoff.conversation_id == conversation_id)
        .order_by(Handoff.id.desc())
        .limit(1)
    )
    if locked:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def latest_message_for_conversation(
    session: AsyncSession,
    conversation_id: int,
) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(1)
    )


async def build_manual_takeover_summary(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    last_messages_limit: int = 5,
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
        "Motivo: OTHER - MANUAL_TAKEOVER",
        "Ultimos mensajes:",
    ]
    for message in messages:
        lines.append(f"- {message.direction}: {message_body(message)}")
    return "\n".join(lines)


async def move_conversation_to_human_active(
    session: AsyncSession,
    conversation: Conversation,
    actor: str,
    reason: str,
) -> None:
    current_state = ConversationState(conversation.state)
    if current_state == ConversationState.HUMAN_ACTIVE:
        return
    if current_state != ConversationState.WAITING_FOR_HUMAN:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_HUMAN,
            actor=actor,
            reason=reason,
        )
    await transition_conversation(
        session,
        conversation,
        ConversationState.HUMAN_ACTIVE,
        actor=actor,
        reason=reason,
    )


def takeover_old_value(conversation: Conversation, handoff: Handoff | None) -> dict[str, object]:
    return {
        "conversation_id": conversation.id,
        "state": conversation.state,
        "bot_enabled": conversation.bot_enabled,
        "handoff_id": handoff.id if handoff is not None else None,
        "handoff_status": handoff.status if handoff is not None else None,
        "assigned_to": handoff.assigned_to if handoff is not None else None,
    }


def append_handoff_summary_line(summary: str, direction: str, text: str) -> str:
    clean_text = " ".join(text.split())
    if not clean_text:
        return summary
    return f"{summary.rstrip()}\n- {direction}: {clean_text}"


def message_direction(message: Message) -> Literal["INBOUND", "OUTBOUND"]:
    if message.direction not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation message has invalid direction",
        )
    return message.direction


def message_body(message: Message) -> str:
    text = message.content.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return "[mensaje no textual]"


def outbox_body(outbox: Outbox) -> str:
    text = outbox.payload.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return "[mensaje saliente no textual]"


def handoff_payload(handoff: Handoff, customer: Customer | None = None) -> dict[str, object]:
    return {
        "id": handoff.id,
        "conversation_id": handoff.conversation_id,
        "customer_name": customer.full_name if customer is not None else None,
        "customer_phone": customer.phone_number if customer is not None else None,
        "reason": handoff.reason,
        "priority": handoff.priority,
        "summary": handoff.summary,
        "status": handoff.status,
        "assigned_to": handoff.assigned_to,
        "created_at": handoff.created_at,
        "taken_at": handoff.taken_at,
        "resolved_at": handoff.resolved_at,
    }
