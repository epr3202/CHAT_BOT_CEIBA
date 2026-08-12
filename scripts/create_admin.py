from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select

import app.models_registry  # noqa: F401
from app.agent.auth import PIN_MIN_LENGTH, hash_pin, revoke_sessions_for_agent
from app.agent.models import Agent
from app.audit.models import AuditEvent
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap an ADMIN user")
    parser.add_argument("--name", required=True)
    parser.add_argument("--document-id", required=True)
    return parser.parse_args()


def prompt_pin() -> str:
    pin = getpass("PIN: ")
    confirmation = getpass("Confirm PIN: ")
    if pin != confirmation:
        raise SystemExit("PIN confirmation does not match")
    if len(pin) < PIN_MIN_LENGTH:
        raise SystemExit(f"PIN must have at least {PIN_MIN_LENGTH} characters")
    return pin


async def main() -> None:
    args = parse_args()
    pin = prompt_pin()
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        async with session.begin():
            agent = await session.scalar(
                select(Agent).where(Agent.document_id == args.document_id.strip())
            )
            old_value = None
            created = agent is None
            if agent is None:
                agent = Agent(
                    name=args.name,
                    document_id=args.document_id.strip(),
                    password_hash=hash_pin(pin),
                    role="ADMIN",
                    active=True,
                )
                session.add(agent)
                await session.flush()
            else:
                old_value = {
                    "agent_id": agent.id,
                    "name": agent.name,
                    "role": agent.role,
                    "active": agent.active,
                }
                agent.name = args.name
                agent.password_hash = hash_pin(pin)
                agent.role = "ADMIN"
                agent.active = True
                await revoke_sessions_for_agent(session, agent.id)

            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="ADMIN_BOOTSTRAP",
                    entity="agent",
                    old_value=old_value,
                    new_value={
                        "agent_id": agent.id,
                        "name": agent.name,
                        "document_id": agent.document_id,
                        "role": agent.role,
                        "active": agent.active,
                        "created": created,
                    },
                    reason="Bootstrap admin user",
                    request_id=None,
                )
            )
    await engine.dispose()
    print(f"Admin user ready: {args.name} ({args.document_id})")


if __name__ == "__main__":
    asyncio.run(main())
