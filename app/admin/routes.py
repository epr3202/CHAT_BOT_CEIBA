from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

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
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


AdminAuth = Annotated[None, Depends(require_admin_token)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("/handoffs")
async def list_handoffs(
    _auth: AdminAuth,
    session: DbSession,
    status: str = "PENDING",
) -> list[dict[str, object]]:
    result = await session.scalars(
        select(Handoff).where(Handoff.status == status).order_by(Handoff.created_at.asc())
    )
    return [handoff_payload(handoff) for handoff in result.all()]


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

    return handoff_payload(handoff)


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

    return handoff_payload(handoff)


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


def handoff_payload(handoff: Handoff) -> dict[str, object]:
    return {
        "id": handoff.id,
        "conversation_id": handoff.conversation_id,
        "reason": handoff.reason,
        "priority": handoff.priority,
        "summary": handoff.summary,
        "status": handoff.status,
        "assigned_to": handoff.assigned_to,
        "created_at": handoff.created_at,
        "taken_at": handoff.taken_at,
        "resolved_at": handoff.resolved_at,
    }
