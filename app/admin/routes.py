from __future__ import annotations

import hmac
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.auth import hash_agent_token, require_agent_from_session
from app.agent.models import Agent
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

DIRECT_TAKE_ELIGIBLE_STATES = {
    ConversationState.BOT_ACTIVE.value,
    ConversationState.ANSWERING_INFORMATION.value,
    ConversationState.COLLECTING_EVENT_DATA.value,
    ConversationState.WAITING_FOR_APPOINTMENT_DATE.value,
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION.value,
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION.value,
    ConversationState.APPOINTMENT_CONFIRMED.value,
    ConversationState.RESOLVED.value,
}


class TakeHandoffRequest(BaseModel):
    agent: str | None = Field(default=None, min_length=1, max_length=128)


class ReturnHandoffRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=500)


class AgentMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    document_id: str | None = Field(default=None, min_length=4, max_length=64)


class AgentPayload(BaseModel):
    id: int
    name: str
    active: bool
    created_at: datetime


class CreatedAgentPayload(AgentPayload):
    token: str


class AgentIdentityPayload(BaseModel):
    id: int
    name: str


class AssignmentHistoryPayload(BaseModel):
    actor: str
    action: str
    created_at: datetime


class ConversationMessagePayload(BaseModel):
    id: str
    direction: Literal["INBOUND", "OUTBOUND"]
    body: str
    message_type: str
    status: str | None = None
    created_at: datetime


class ConversationPayload(BaseModel):
    id: int
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
    assigned_agent: AgentIdentityPayload | None
    assignment_history: list[AssignmentHistoryPayload]
    handoff_reason: str | None
    handoff_priority: str | None
    last_message_body: str | None
    last_message_preview: str | None
    last_message_direction: str | None
    last_message_at: datetime | None


async def require_admin_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if is_admin_authorized(request, authorization):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def is_admin_authorized(request: Request, authorization: str | None) -> bool:
    settings: Settings = request.app.state.settings
    expected = settings.admin_api_token.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API token is not configured",
        )
    provided = (authorization or "").removeprefix("Bearer ")
    return hmac.compare_digest(provided, expected)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


AdminAuth = Annotated[None, Depends(require_admin_token)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
HandoffListStatus = Literal["PENDING", "TAKEN", "RETURNED"]


async def require_admin_or_agent(
    request: Request,
    session: AsyncSession,
    authorization: str | None,
) -> Agent | None:
    settings: Settings = request.app.state.settings
    expected = settings.admin_api_token.strip()
    provided = (authorization or "").removeprefix("Bearer ")
    if expected and hmac.compare_digest(provided, expected):
        return None
    return await require_agent_from_session(session, authorization)


@router.post("/agents")
async def create_agent(
    body: CreateAgentRequest,
    _auth: AdminAuth,
    session: DbSession,
) -> CreatedAgentPayload:
    token = body.document_id.strip() if body.document_id is not None else secrets.token_urlsafe(32)
    token_hash = hash_agent_token(token)
    async with session.begin():
        agent = Agent(name=body.name, token_hash=token_hash, active=True)
        session.add(agent)
        await session.flush()
        session.add(
            AuditEvent(
                actor="ADMIN",
                action="AGENT_CREATED",
                entity="agent",
                old_value=None,
                new_value={"agent_id": agent.id, "name": agent.name, "active": agent.active},
                reason="Admin created agent token",
                request_id=None,
            )
        )
    return CreatedAgentPayload(
        id=agent.id,
        name=agent.name,
        active=agent.active,
        created_at=agent.created_at,
        token=token,
    )


@router.get("/agents")
async def list_agents(
    _auth: AdminAuth,
    session: DbSession,
) -> list[AgentPayload]:
    agents = await session.scalars(select(Agent).order_by(Agent.name.asc()))
    return [
        AgentPayload(id=agent.id, name=agent.name, active=agent.active, created_at=agent.created_at)
        for agent in agents.all()
    ]


@router.post("/agents/{agent_id}/deactivate")
async def deactivate_agent(
    agent_id: int,
    _auth: AdminAuth,
    session: DbSession,
) -> dict[str, object]:
    async with session.begin():
        agent = await session.get(Agent, agent_id, with_for_update=True)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        was_active = agent.active
        agent.active = False
        active_conversation_count = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.assigned_agent_id == agent.id,
                Conversation.state == ConversationState.HUMAN_ACTIVE.value,
            )
        )
        session.add(
            AuditEvent(
                actor="ADMIN",
                action="AGENT_DEACTIVATED",
                entity="agent",
                old_value={"agent_id": agent.id, "active": was_active},
                new_value={
                    "agent_id": agent.id,
                    "active": agent.active,
                    "active_conversation_count": active_conversation_count or 0,
                },
                reason="Admin deactivated agent",
                request_id=None,
            )
        )
    return {
        "id": agent.id,
        "name": agent.name,
        "active": agent.active,
        "active_conversation_count": active_conversation_count or 0,
    }


@router.get("/me")
async def read_me(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AgentIdentityPayload:
    agent = await require_agent_from_session(session, authorization)
    if not agent.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is inactive")
    return AgentIdentityPayload(id=agent.id, name=agent.name)


@router.get("/handoffs")
async def list_handoffs(
    request: Request,
    session: DbSession,
    status: HandoffListStatus = "PENDING",
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, object]]:
    await require_admin_or_agent(request, session, authorization)
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
    request: Request,
    session: DbSession,
    state: str | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authorization: Annotated[str | None, Header()] = None,
) -> list[ConversationPayload]:
    agent = await require_admin_or_agent(request, session, authorization)
    if state is not None:
        try:
            ConversationState(state)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid conversation state",
            ) from exc
    if assigned_to_me and agent is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="assigned_to_me requires agent authentication",
        )

    filters = []
    if state is not None:
        filters.append(Conversation.state == state)
    if assigned_to_me and agent is not None:
        filters.append(Conversation.assigned_agent_id == agent.id)

    statement = (
        select(Conversation, Customer, Agent)
        .join(Customer, Conversation.customer_id == Customer.id)
        .outerjoin(Agent, Conversation.assigned_agent_id == Agent.id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        statement = statement.where(*filters)
    result = await session.execute(
        statement
    )
    conversations = result.all()
    payloads: list[ConversationPayload] = []
    for conversation, customer, assigned_agent in conversations:
        handoff = await latest_handoff_for_conversation(session, conversation.id)
        latest_message = await latest_message_for_conversation(session, conversation.id)
        latest_body = message_body(latest_message) if latest_message is not None else None
        assignment_history = await assignment_history_for_conversation(session, conversation.id)
        payloads.append(
            ConversationPayload(
                id=conversation.id,
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
                assigned_agent=agent_identity_payload(assigned_agent),
                assignment_history=assignment_history,
                handoff_reason=handoff.reason if handoff is not None else None,
                handoff_priority=handoff.priority if handoff is not None else None,
                last_message_body=latest_body,
                last_message_preview=truncate_preview(latest_body),
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
    request: Request,
    session: DbSession,
    body: TakeHandoffRequest | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await require_admin_or_agent(request, session, authorization)
    if agent is not None:
        actor = agent.name
        assigned_agent_id = agent.id
        await session.rollback()
    else:
        actor = body.agent if body is not None else None
        assigned_agent_id = None
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="agent is required when using admin authentication",
            )

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
        handoff.assigned_to = actor
        handoff.assigned_agent_id = assigned_agent_id
        handoff.taken_at = now
        conversation.bot_enabled = False
        conversation.assigned_agent_id = assigned_agent_id
        await transition_conversation(
            session,
            conversation,
            ConversationState.HUMAN_ACTIVE,
            actor=actor,
            reason="Handoff taken by human agent",
        )
        session.add(
            AuditEvent(
                actor=actor,
                action="HANDOFF_TAKEN",
                entity="handoff",
                old_value={"status": "PENDING"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "TAKEN",
                    "assigned_to": actor,
                    "assigned_agent_id": assigned_agent_id,
                },
                reason="Human agent took handoff",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/conversations/{conversation_id}/take")
async def take_conversation(
    conversation_id: int,
    request: Request,
    session: DbSession,
    body: TakeHandoffRequest | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await require_admin_or_agent(request, session, authorization)
    agent_id = agent.id if agent is not None else None
    agent_name = agent.name if agent is not None else (body.agent if body is not None else "ADMIN")
    await session.rollback()

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

        if conversation.state == ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation already has an active human agent",
            )
        if conversation.state == ConversationState.CLOSED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Closed conversations require explicit admin reopening",
            )
        if conversation.state == ConversationState.WAITING_FOR_HUMAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation has a handoff pendiente; take the existing handoff",
            )
        if conversation.state not in DIRECT_TAKE_ELIGIBLE_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation state is not eligible for direct takeover",
            )

        now = datetime.now(UTC)
        previous_state = conversation.state
        previous_bot_enabled = conversation.bot_enabled
        previous_assigned_agent_id = conversation.assigned_agent_id

        if conversation.state == ConversationState.RESOLVED.value:
            session.add(
                AuditEvent(
                    actor=agent_name,
                    action="CONVERSATION_REOPENED",
                    entity="conversation",
                    old_value={"conversation_id": conversation.id, "state": conversation.state},
                    new_value={
                        "conversation_id": conversation.id,
                        "state": ConversationState.BOT_ACTIVE.value,
                    },
                    reason="Direct takeover reopened resolved conversation",
                    request_id=None,
                )
            )
            await transition_conversation(
                session,
                conversation,
                ConversationState.BOT_ACTIVE,
                actor=agent_name,
                reason="Direct takeover reopening",
            )

        handoff = Handoff(
            conversation_id=conversation.id,
            reason="MANUAL_TAKEOVER",
            priority="NORMAL",
            summary=await build_manual_takeover_summary(session, conversation, customer),
            status="TAKEN",
            assigned_to=agent_name,
            assigned_agent_id=agent_id,
            taken_at=now,
        )
        session.add(handoff)
        await session.flush()
        session.add(
            AuditEvent(
                actor=agent_name,
                action="HANDOFF_CREATED",
                entity="handoff",
                old_value=None,
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "reason": "MANUAL_TAKEOVER",
                    "priority": "NORMAL",
                    "status": "TAKEN",
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )

        conversation.bot_enabled = False
        conversation.pending_action = "WAIT_FOR_HUMAN"
        conversation.assigned_agent_id = agent_id
        await move_conversation_to_human_active(
            session,
            conversation,
            actor=agent_name,
            reason="Manual direct takeover",
        )
        session.add(
            AuditEvent(
                actor=agent_name,
                action="HANDOFF_TAKEN",
                entity="handoff",
                old_value={"status": "PENDING"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "TAKEN",
                    "assigned_to": agent_name,
                    "assigned_agent_id": agent_id,
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )
        session.add(
            AuditEvent(
                actor=agent_name,
                action="CONVERSATION_MANUAL_TAKEOVER",
                entity="conversation",
                old_value={
                    "conversation_id": conversation.id,
                    "state": previous_state,
                    "bot_enabled": previous_bot_enabled,
                    "assigned_agent_id": previous_assigned_agent_id,
                },
                new_value={
                    "conversation_id": conversation.id,
                    "handoff_id": handoff.id,
                    "state": ConversationState.HUMAN_ACTIVE.value,
                    "bot_enabled": False,
                    "assigned_to": agent_name,
                    "assigned_agent_id": agent_id,
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/handoffs/{handoff_id}/return")
async def return_handoff(
    handoff_id: int,
    body: ReturnHandoffRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await require_admin_or_agent(request, session, authorization)
    if agent is not None:
        actor = agent.name
        await session.rollback()
    else:
        actor = "ADMIN"

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
        handoff.assigned_agent_id = None
        handoff.assigned_to = None
        conversation.bot_enabled = True
        conversation.pending_action = None
        conversation.assigned_agent_id = None
        await transition_conversation(
            session,
            conversation,
            ConversationState.RETURNED_TO_BOT,
            actor=actor,
            reason=body.resolution,
        )
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor=actor,
            reason="Returned to bot after human handling",
        )
        session.add(
            AuditEvent(
                actor=actor,
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
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, int | str]:
    agent = await require_admin_or_agent(request, session, authorization)
    actor = agent.name if agent is not None else "ADMIN"
    if agent is not None:
        await session.rollback()

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
                actor=actor,
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
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[ConversationMessagePayload]:
    await require_admin_or_agent(request, session, authorization)
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


async def assignment_history_for_conversation(
    session: AsyncSession,
    conversation_id: int,
) -> list[AssignmentHistoryPayload]:
    events = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.in_(
                [
                    "HANDOFF_TAKEN",
                    "HANDOFF_RETURNED",
                    "CONVERSATION_MANUAL_TAKEOVER",
                ]
            )
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    history: list[AssignmentHistoryPayload] = []
    for event in events.all():
        new_value = event.new_value or {}
        old_value = event.old_value or {}
        event_conversation_id = new_value.get("conversation_id") or old_value.get(
            "conversation_id"
        )
        if event_conversation_id != conversation_id:
            continue
        if event.action == "CONVERSATION_MANUAL_TAKEOVER":
            continue
        history.append(
            AssignmentHistoryPayload(
                actor=event.actor,
                action=event.action,
                created_at=event.created_at,
            )
        )
    return history


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
        "Motivo: MANUAL_TAKEOVER",
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


def agent_identity_payload(agent: Agent | None) -> AgentIdentityPayload | None:
    if agent is None:
        return None
    return AgentIdentityPayload(id=agent.id, name=agent.name)


def truncate_preview(text: str | None, limit: int = 120) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


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
        "assigned_agent": (
            {"id": handoff.assigned_agent_id, "name": handoff.assigned_to}
            if handoff.assigned_agent_id is not None
            else None
        ),
        "created_at": handoff.created_at,
        "taken_at": handoff.taken_at,
        "resolved_at": handoff.resolved_at,
    }
