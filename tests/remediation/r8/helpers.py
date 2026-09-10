"""Real admin routes, real login and synthetic persisted cases for R8."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.admin.routes import router
from app.agent.auth import hash_pin
from app.agent.models import Agent
from app.channel.models import Message
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from tests.remediation.test_r1_outbox import db as db


@pytest.fixture
async def api(db: Any) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, Any]]]:
    application = FastAPI()
    application.include_router(router)
    application.state.db_sessionmaker = db
    password_hash = hash_pin("837261")  # Synthetic fixture only; never included in evidence.
    async with db() as session, session.begin():
        for index, label in enumerate(("A", "B", "ADMIN"), 1):
            session.add(Agent(name="R8 " + label, document_id=f"8000000{index}",
                              password_hash=password_hash,
                              role="ADMIN" if label == "ADMIN" else "AGENT", active=True))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://r8.test",
    ) as client:
        actors = {}
        for index, label in enumerate(("A", "B", "ADMIN"), 1):
            response = await client.post("/admin/login", json={
                "document_id": f"8000000{index}", "pin": "837261",
            })
            assert response.status_code == 200, "Real login precondition"
            payload = response.json()
            actor = {"id": payload["agent"]["id"],
                     "headers": {"Authorization": "Bearer " + payload["token"]}}
            identity = await client.get("/admin/me", headers=actor["headers"])
            assert identity.status_code == 200 and identity.json()["id"] == actor["id"]
            actors[label] = actor
        assert len({a["id"] for a in actors.values()}) == 3
        yield client, actors


async def seed_case(db: Any, *, pending: bool = True) -> tuple[int, int | None]:
    async with db() as session, session.begin():
        customer = Customer(phone_number="+57300" + str(uuid4().int)[:7],
                            full_name="Cliente sintetico R8")
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            customer_id=customer.id, channel="WHATSAPP",
            state="WAITING_FOR_HUMAN" if pending else "BOT_ACTIVE",
            bot_enabled=not pending, pending_action="WAIT_FOR_HUMAN" if pending else None,
        )
        session.add(conversation)
        await session.flush()
        session.add(Message(
            external_message_id="r8.seed." + uuid4().hex, conversation_id=conversation.id,
            customer_id=customer.id, channel="WHATSAPP", direction="INBOUND",
            message_type="text", content={"text": {"body": "Consulta sintetica R8"}},
        ))
        handoff = None
        if pending:
            handoff = Handoff(conversation_id=conversation.id, status="PENDING",
                              reason="CUSTOMER_REQUEST", priority="NORMAL",
                              summary="Resumen sintetico conservado")
            session.add(handoff)
            await session.flush()
        return conversation.id, handoff.id if handoff is not None else None


async def take_case(
    db: Any, client: httpx.AsyncClient, actor: dict[str, Any], *, pending: bool = True,
) -> tuple[int, int]:
    conversation_id, handoff_id = await seed_case(db, pending=pending)
    path = f"/admin/handoffs/{handoff_id}/take" if pending else (
        f"/admin/conversations/{conversation_id}/take")
    response = await client.post(path, headers=actor["headers"])
    assert response.status_code == 200, "Real authorized takeover precondition"
    payload = response.json()
    assert payload["assigned_agent"]["id"] == actor["id"]
    rows = await snapshot(db)
    conversation = next(r for r in rows["conversation"] if r["id"] == conversation_id)
    handoff = next(r for r in rows["handoff"] if r["id"] == payload["id"])
    assert conversation["assigned_agent_id"] == handoff["assigned_agent_id"] == actor["id"]
    assert conversation["state"] == "HUMAN_ACTIVE" and not conversation["bot_enabled"]
    assert handoff["status"] == "TAKEN"
    return conversation_id, payload["id"]


async def mutate(
    client: httpx.AsyncClient, action: str, ids: tuple[int, int], headers: dict[str, str],
) -> httpx.Response:
    if action == "reply":
        return await client.post(f"/admin/conversations/{ids[0]}/messages", headers=headers,
                                 json={"text": "Respuesta humana sintetica R8"})
    return await client.post(f"/admin/handoffs/{ids[1]}/return", headers=headers,
                             json={"resolution": "Atencion sintetica finalizada"})


async def snapshot(db: Any) -> dict[str, Any]:
    # Independent session, all commercial columns; no Agent credential or session rows.
    async with db() as session:
        return {
            name: [dict(row) for row in (await session.execute(
                text(f'SELECT * FROM "{name}" ORDER BY to_jsonb("{name}")::text'),
            )).mappings()]
            for name in ("customer", "conversation", "handoff", "message", "outbox",
                         "audit_event", "lead", "event", "event_service_request",
                         "quote_request", "appointment", "payment_evidence", "inbox_job")
        }
