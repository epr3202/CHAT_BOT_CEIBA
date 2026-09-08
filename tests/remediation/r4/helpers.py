"""Synthetic R4 inputs; real SQL, channel, handoff and authenticated admin reads."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from app.admin.routes import router as admin_router
from app.agent.auth import hash_agent_token
from app.agent.models import Agent, AgentSession
from app.channel import inbound, inbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.handoff import service as handoff_service
from app.lead.models import Lead
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.remediation.r2.test_r2_recovery import payload
from tests.remediation.r3.helpers import snapshot as snapshot

POSITIVE = "Quiero hablar con un asesor"


def configure(monkeypatch: pytest.MonkeyPatch, *, outside: bool = False) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "0.25")
    get_settings.cache_clear()

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            fixed = datetime(2026, 9, 8, 18 if outside else 10, tzinfo=ZoneInfo("America/Bogota"))
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(handoff_service, "datetime", Clock)


def message_payload(external_id: str, body: str = POSITIVE) -> dict[str, Any]:
    value = payload(external_id)
    value["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = body
    return value


async def prepare(
    db: Any,
    *,
    external_id: str = "r4.synthetic",
    body: str = POSITIVE,
    pending: str | None = None,
    state: str = "BOT_ACTIVE",
    enabled: bool = True,
) -> int:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    event_id = await inbound.store_webhook_event(message_payload(external_id, body), db, None)
    await inbox.expand_event(db, event_id, datetime.now(UTC))
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state, conversation.bot_enabled = state, enabled
        conversation.pending_action = pending
        customer = await session.get(Customer, conversation.customer_id)
        customer.full_name = "Cliente Sintetico R4"
        if pending in {"COLLECT_EVENT_TYPE", "COLLECT_SERVICES", "COLLECT_CATALOG_EVENT_TYPE"}:
            lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            session.add(
                Event(
                    lead_id=lead.lead_id,
                    event_type="BIRTHDAY" if pending == "COLLECT_SERVICES" else None,
                    event_date=date(2027, 2, 20),
                    event_date_type="EXACT",
                    guest_count=40,
                    guest_count_status="PROVIDED",
                )
            )
            lead.budget_data_status = "PROVIDED"
            conversation.active_lead_id = lead.lead_id
            conversation.pending_fields = ["requested_services"]
            conversation.last_question_code = {
                "COLLECT_EVENT_TYPE": "RESP-EVENT-DATA-013",
                "COLLECT_SERVICES": "RESP-EVENT-DATA-006",
                "COLLECT_CATALOG_EVENT_TYPE": "RESP-CATALOG-002",
            }[pending]
    return event_id


async def admin_cases(db: Any, status: str = "PENDING") -> dict[str, Any]:
    # A real synthetic session exercises require_session and the existing endpoint.
    # Neither session tokens nor their hashes are included in returned evidence.
    credential = "R4-synthetic-admin-session"
    async with db() as session, session.begin():
        agent = await session.get(Agent, 1)
        if agent is None:
            agent = Agent(name="R4 Synthetic Reader", role="ADMIN", active=True)
            session.add(agent)
            await session.flush()
            session.add(
                AgentSession(
                    agent_id=agent.id,
                    token_hash=hash_agent_token(credential),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
    app = FastAPI()
    app.state.db_sessionmaker = db
    app.include_router(admin_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get(
            "/admin/handoffs",
            params={"status": status},
            headers={"Authorization": "Bearer " + credential},
        )
    return {"status_code": result.status_code, "body": result.json()}
