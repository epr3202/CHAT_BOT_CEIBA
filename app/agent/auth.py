from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization.removeprefix(prefix).strip()
    return token or None


async def resolve_agent_from_authorization(
    session: AsyncSession,
    authorization: str | None,
) -> Agent | None:
    token = bearer_token(authorization)
    if token is None:
        return None
    token_hash = hash_agent_token(token)
    agent = await session.scalar(select(Agent).where(Agent.token_hash == token_hash))
    if agent is None:
        return None
    if not hmac.compare_digest(agent.token_hash, token_hash):
        return None
    return agent


async def require_agent_from_session(
    session: AsyncSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Agent:
    agent = await resolve_agent_from_authorization(session, authorization)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    if not agent.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is inactive")
    return agent
