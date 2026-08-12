from __future__ import annotations

import hashlib
from typing import Annotated

import bcrypt
from fastapi import Header, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, AgentSession

PIN_MIN_LENGTH = 6
SESSION_HOURS = 12
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"000000", bcrypt.gensalt()).decode()


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, password_hash: str) -> bool:
    return bcrypt.checkpw(pin.encode(), password_hash.encode())


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization.removeprefix(prefix).strip()
    return token or None


async def resolve_session_from_authorization(
    session: AsyncSession,
    authorization: str | None,
) -> AgentSession | None:
    token = bearer_token(authorization)
    if token is None:
        return None
    token_hash = hash_agent_token(token)
    return await session.scalar(select(AgentSession).where(AgentSession.token_hash == token_hash))


async def delete_expired_sessions_for_agent(session: AsyncSession, agent_id: int) -> None:
    from datetime import UTC, datetime

    await session.execute(
        delete(AgentSession).where(
            AgentSession.agent_id == agent_id,
            AgentSession.expires_at <= datetime.now(UTC),
        )
    )


async def revoke_sessions_for_agent(session: AsyncSession, agent_id: int) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    rows = await session.scalars(
        select(AgentSession).where(
            AgentSession.agent_id == agent_id,
            AgentSession.revoked_at.is_(None),
        )
    )
    for row in rows.all():
        row.revoked_at = now


async def require_session(
    session: AsyncSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Agent:
    from datetime import UTC, datetime

    agent_session = await resolve_session_from_authorization(session, authorization)
    now = datetime.now(UTC)
    if (
        agent_session is None
        or agent_session.revoked_at is not None
        or agent_session.expires_at <= now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    agent = await session.get(Agent, agent_session.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    if not agent.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is inactive")
    return agent


async def require_agent_from_session(
    session: AsyncSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Agent:
    return await require_session(session, authorization)


def require_admin(agent: Agent) -> None:
    if agent.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
