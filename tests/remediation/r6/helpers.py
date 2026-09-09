"""Synthetic turns through real channel, provider boundary, R2 and admin endpoints."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import httpx
import respx
from fastapi import FastAPI

from app.admin.routes import router as admin_router
from app.channel import inbound
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.lead.models import Lead
from tests.remediation.r3.helpers import MAIN, Provider, snapshot as snapshot, valid
from tests.remediation.r4.helpers import admin_cases, message_payload, prepare as intake


def proposal(intent: str = "QUOTE_REQUEST", *, confidence: float = 0.99,
             entities: list[dict[str, Any]] | None = None, **fields: Any) -> dict[str, Any]:
    return valid() | dict(primary_intent=intent, confidence=confidence,
                          information_category=None, entities={}, extracted_entities=entities or [],
                          requested_action=None, needs_human=False, handoff_reason=None,
                          reasoning_code="R6_SYNTHETIC") | fields


def entity(name: str, value: Any, **fields: Any) -> dict[str, Any]:
    return dict(entity=name, raw_value=value if isinstance(value, str) else "dato sintetico",
                normalized_value=value, quality_status="PROVIDED", confidence=0.99,
                needs_confirmation=False) | fields


async def prepare(db: Any, *, name: str | None = "Cliente Sintetico R6",
                  body: str = "Quiero cotizar mi evento") -> int:
    event_id = await intake(db, external_id="r6.first", body=body, state="COLLECTING_EVENT_DATA")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        customer = await session.get(Customer, conversation.customer_id)
        customer.full_name = name
        lead = Lead(customer_id=customer.id, channel="WHATSAPP", budget_data_status="DECLINED")
        session.add(lead)
        await session.flush()
        event = Event(lead_id=lead.lead_id, event_type="BIRTHDAY", guest_count=40,
                      guest_count_status="PROVIDED", event_date_type="EXACT",
                      event_date=date(2027, 2, 20))
        session.add(event)
        await session.flush()
        session.add(EventServiceRequest(event_id=event.event_id, service_name="VENUE", position=0))
        conversation.active_lead_id = lead.lead_id
    return event_id


async def send(db: Any, body: str, response: dict[str, Any] | None = None, *,
               event_id: int | None = None, expected_calls: int = 1,
               external_id: str | None = None) -> dict[str, Any]:
    before = await snapshot(db)
    if event_id is None:
        event_id = await inbound.store_webhook_event(
            message_payload(external_id or "r6." + uuid.uuid4().hex, body), db, None)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [response or proposal()] * expected_calls})
        counts = await inbound.process_webhook_event(event_id, db)
    provider.exhausted()
    return dict(input=body, event_id=event_id, before=before, after=await snapshot(db),
                calls=dict(provider.calls), counts=counts)


def completed(step: dict[str, Any]) -> None:
    assert next(e for e in step["after"]["webhook_event"] if e["id"] == step["event_id"])[
        "status"] == "PROCESSED", step["counts"]
    assert all(j["status"] == "COMPLETED" for j in step["after"]["inbox_job"])


def actions(rows: dict[str, Any], action: str) -> int:
    return sum(a["action"] == action for a in rows["audit_event"])


async def human_return(db: Any) -> dict[str, Any]:
    listed = await admin_cases(db)
    assert listed["status_code"] == 200
    handoff_id = (await snapshot(db))["handoff"][0]["id"]
    app = FastAPI()
    app.state.db_sessionmaker = db
    app.include_router(admin_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        headers = {"Authorization": "Bearer R4-synthetic-admin-session"}
        taken = await client.post(f"/admin/handoffs/{handoff_id}/take", headers=headers)
        assert taken.status_code == 200, taken.text
        returned = await client.post(f"/admin/handoffs/{handoff_id}/return", headers=headers,
                                     json={"resolution": "Resolucion sintetica R6"})
        assert returned.status_code == 200, returned.text
    return dict(taken=taken.json(), returned=returned.json(), after=await snapshot(db))
