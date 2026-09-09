"""Additional matrix after the initial RED criteria were frozen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.admin.routes import router as admin_router
from app.agent.auth import hash_agent_token
from app.agent.models import Agent, AgentSession
from app.channel import inbound
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from tests.remediation.r3.helpers import MAIN, Provider, valid
from tests.remediation.r4.helpers import configure, message_payload
from tests.remediation.r5.helpers import assert_passive, media_payload, prepare, snapshot
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio
STATES = [("WAITING_FOR_HUMAN", True), ("WAITING_FOR_HUMAN", False),
          ("HUMAN_ACTIVE", False), ("BOT_ACTIVE", False)]
MEDIA = [(kind, caption) for kind in ("image", "document", "video")
         for caption in (None, "", "   ", "Comprobante sintetico")]
MEDIA += [("audio", None)]


@pytest.mark.parametrize("state,enabled", STATES)
@pytest.mark.parametrize("kind,caption", MEDIA)
@pytest.mark.parametrize("payment", [None, "TAKEN"])
async def test_paused_media_matrix(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    state: str, enabled: bool, kind: str, caption: str | None, payment: str | None,
) -> None:
    configure(monkeypatch)
    data = media_payload(kind, caption)
    if kind in {"audio", "video"}:
        raw = data["entry"][0]["changes"][0]["value"]["messages"][0][kind]
        raw["mime_type"] = "audio/ogg" if kind == "audio" else "video/mp4"
    event = await prepare(db, kind=kind, caption=caption, state=state,
                          enabled=enabled, payment=payment, data=data)
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert_passive(before, final, payment is not None and kind in {"image", "document"})
    assert provider.calls == {}
    assert final["inbox_job"][0]["completion_reason"].startswith("SILENT_")
    assert final["webhook_event"][0]["status"] == "PROCESSED"
    assert sum(a["action"] == "NON_TEXT_MESSAGE_RECEIVED" for a in final["audit_event"]) == 1


OTHER = {
    "location": {"latitude": 7.1, "longitude": -73.1},
    "contacts": [{"name": {"formatted_name": "Contacto Sintetico"}}],
    "reaction": {"message_id": "synthetic.previous", "emoji": ""},
    "unsupported": {"errors": [{"code": 131051}]},
    "future_type": {"synthetic": True},
    "sticker": {"id": "synthetic.sticker", "mime_type": "image/webp"},
    "interactive": {"type": "button_reply", "button_reply": {"id": "old", "title": "Hola"}},
    "button": {"payload": "old", "text": "Hola"},
}


@pytest.mark.parametrize("kind", list(OTHER))
@pytest.mark.parametrize("state,enabled", STATES)
async def test_other_materialized_types_share_pause(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    kind: str, state: str, enabled: bool,
) -> None:
    configure(monkeypatch)
    data = media_payload(kind)
    data["entry"][0]["changes"][0]["value"]["messages"][0][kind] = OTHER[kind]
    event = await prepare(db, data=data, state=state, enabled=enabled)
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert_passive(before, final, False)
    assert provider.calls == {}
    assert final["message"][0]["message_type"] == ("unknown" if kind == "future_type" else kind)


@pytest.mark.parametrize("case", ["pending", "resolved", "returned", "other_reason",
                                  "other_conversation", "missing_mime", "missing_hash", "closed"])
async def test_evidence_eligibility(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    configure(monkeypatch)
    data = media_payload(caption="Quiero hablar con un asesor")
    raw = data["entry"][0]["changes"][0]["value"]["messages"][0]["image"]
    if case in {"missing_mime", "missing_hash"}:
        raw.pop("mime_type" if case == "missing_mime" else "sha256")
    event = await prepare(db, data=data, payment="PENDING",
                          state="CLOSED" if case == "closed" else "HUMAN_ACTIVE")
    async with db() as session, session.begin():
        handoff = await session.get(Handoff, 1)
        if case in {"resolved", "returned"}:
            handoff.status = case.upper()
        if case == "other_reason":
            handoff.reason = "CUSTOMER_REQUEST"
        if case == "other_conversation":
            customer = Customer(phone_number="+573000000099")
            session.add(customer)
            await session.flush()
            other = Conversation(customer_id=customer.id, channel="WHATSAPP", state="HUMAN_ACTIVE")
            session.add(other)
            await session.flush()
            handoff.conversation_id = other.id
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert_passive(before, final, case == "pending")
    assert provider.calls == {}
    if case.startswith("missing_"):
        assert any(a["new_value"].get("capture_result") == "MISSING_METADATA"
                   for a in final["audit_event"] if isinstance(a["new_value"], dict))


@pytest.mark.parametrize("kind", ["image", "document", "audio", "video"])
async def test_active_no_caption_routes_unchanged(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    configure(monkeypatch)
    data = media_payload(kind)
    if kind in {"audio", "video"}:
        raw = data["entry"][0]["changes"][0]["value"]["messages"][0][kind]
        raw["mime_type"] = "audio/ogg" if kind == "audio" else "video/mp4"
    event = await prepare(db, data=data, state="BOT_ACTIVE", enabled=True, payment="PENDING")
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls)
    assert len(final["outbox"]) == 1
    assert len(final["payment_evidence"]) == int(kind in {"image", "document"})
    assert provider.calls == {}


async def admin_client(db: Any) -> httpx.AsyncClient:
    credential = "R5-synthetic-authorized-session"
    async with db() as session, session.begin():
        agent = Agent(name="Asesor Sintetico R5", role="ADMIN", active=True)
        session.add(agent)
        await session.flush()
        session.add(AgentSession(agent_id=agent.id, token_hash=hash_agent_token(credential),
                                 expires_at=datetime.now(UTC) + timedelta(hours=1)))
    app = FastAPI()
    app.state.db_sessionmaker = db
    app.include_router(admin_router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                            headers={"Authorization": "Bearer " + credential})


@pytest.mark.parametrize("payment", [False, True])
async def test_operational_admin_visibility_and_human_output(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, payment: bool,
) -> None:
    configure(monkeypatch)
    data = media_payload(caption="Pago sintetico") if payment else message_payload("r5.ask")
    event = await prepare(db, data=data, state="BOT_ACTIVE", enabled=True)
    with respx.mock(assert_all_called=False) as router:
        response = valid()
        if payment:
            response.update(primary_intent="PAYMENT_MESSAGE", needs_human=True,
                            handoff_reason="PAYMENT_REVIEW")
        provider = Provider(router, {MAIN: [response]})
        await inbound.process_webhook_event(event, db)
    async with await admin_client(db) as client:
        cases = await client.get("/admin/handoffs", params={"status": "PENDING"})
        assert cases.status_code == 200 and len(cases.json()) == 1
        case_id = cases.json()[0]["id"]
        waiting = await snapshot(db)
        await inbound.process_whatsapp_webhook(media_payload(external_id="r5.while.waiting"), db)
        after_waiting = await snapshot(db)
        assert after_waiting["outbox"] == waiting["outbox"]
        assert after_waiting["ai_execution"] == waiting["ai_execution"]
        assert len(after_waiting["handoff"]) == 1
        assert after_waiting["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
        taken = await client.post(f"/admin/handoffs/{case_id}/take")
        assert taken.status_code == 200
        before = await snapshot(db)
        await inbound.process_whatsapp_webhook(media_payload(external_id="r5.after.take"), db)
        final = await snapshot(db)
        messages = await client.get("/admin/conversations/1/messages")
        files = await client.get("/admin/payment-evidence")
        updated = await client.get("/admin/handoffs", params={"status": "TAKEN"})
        assert messages.status_code == files.status_code == updated.status_code == 200
        assert any(m.get("message_type") == "image" for m in messages.json())
        assert len(files.json()) == (3 if payment else 0)
        if payment:
            assert "evidencia #" in updated.json()[0]["summary"]
        human = await client.post("/admin/conversations/1/messages",
                                  json={"text": "Respuesta humana sintetica"})
        assert human.status_code == 200
    after_human = await snapshot(db)
    evidence(request, before=before, final=final, after_human=after_human,
             waiting=waiting, after_waiting=after_waiting,
             administrative_evidence=files.json(), administrative_cases=updated.json(),
             calls=provider.calls)
    assert final["outbox"] == before["outbox"]  # U12c remains outside R5.
    assert len(final["handoff"]) == 1
    assert final["ai_execution"] == before["ai_execution"]
    for field in ("state", "bot_enabled", "assigned_agent_id"):
        assert final["conversation"][0][field] == before["conversation"][0][field]
    for field in ("status", "assigned_to", "assigned_agent_id"):
        assert final["handoff"][0][field] == before["handoff"][0][field]
    assert len(after_human["outbox"]) == len(final["outbox"]) + 1


@pytest.mark.parametrize("kind", ["image", "document", "audio", "video"])
async def test_missing_provider_media_id_is_rejected(
    request: pytest.FixtureRequest, kind: str,
) -> None:
    data = media_payload(kind)
    data["entry"][0]["changes"][0]["value"]["messages"][0][kind].pop("id")
    parsed = inbound.extract_inbound_messages(data)
    evidence(request, parser_result_count=len(parsed),
             boundary="Parser only; no Message materialized")
    assert parsed == []


async def test_confirmed_context_and_pending_proposals_are_preserved(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    event = await prepare(db, payment="TAKEN", caption="Quiero hablar con un asesor")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        lead = Lead(customer_id=conversation.customer_id, channel="WHATSAPP",
                    lead_status="QUALIFYING")
        session.add(lead)
        await session.flush()
        session.add(Event(lead_id=lead.lead_id, event_type="BIRTHDAY",
                          event_date=date(2027, 2, 20), event_date_type="EXACT",
                          guest_count=40, guest_count_status="PROVIDED"))
        conversation.active_lead_id = lead.lead_id
        conversation.pending_action = "CONFIRM_QUOTE_REQUEST"
        conversation.pending_fields = ["requested_services"]
        conversation.pending_confirmation = {"type": "AI_CONFIRMATION", "classification": valid()}
        conversation.visit_draft = {"visit_date": "2027-02-20", "mode": "SCHEDULE"}
        conversation.last_question_code = "RESP-EVENT-DATA-006"
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert_passive(before, final, True)
    for table in ("lead", "event", "customer", "appointment", "quote_request"):
        assert final[table] == before[table]
    assert final["payment_evidence"][0]["lead_id"] == before["conversation"][0]["active_lead_id"]
    assert provider.calls == {}
