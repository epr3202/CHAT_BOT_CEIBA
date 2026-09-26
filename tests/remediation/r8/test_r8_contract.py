"""Post-RED authorization controls; no retroactive claim of BASE failures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx
from sqlalchemy import select, update

from app.agent.models import Agent, AgentSession
from app.channel import inbound
from app.conversation.models import Conversation
from app.handoff.models import Handoff
from tests.remediation.r4.helpers import configure, prepare
from tests.remediation.r5.helpers import media_payload
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import mutate, seed_case, snapshot, take_case
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("pending", [True, False])
@pytest.mark.parametrize("action", ["reply", "return"])
@pytest.mark.parametrize("policy", ["owner", "other", "admin_owner", "admin_other"])
async def test_role_policy_on_both_entry_paths(
    db: Any, api: Any, request: pytest.FixtureRequest,
    pending: bool, action: str, policy: str,
) -> None:
    client, actors = api
    owner = "ADMIN" if policy == "admin_owner" else "A"
    caller = {"owner": "A", "other": "B", "admin_owner": "ADMIN",
              "admin_other": "ADMIN"}[policy]
    with respx.mock:
        ids = await take_case(db, client, actors[owner], pending=pending)
        before = await snapshot(db)
        response = await mutate(client, action, ids, actors[caller]["headers"])
        after = await snapshot(db)
    evidence(request, before=before, after=after, http_status=response.status_code,
             owner_id=actors[owner]["id"], actor_id=actors[caller]["id"])
    if owner != caller:
        assert response.status_code == 403 and after == before
        assert str(actors[owner]["id"]) not in response.json()["detail"]
    else:
        assert response.status_code == 200
        assert after["message"] == before["message"]
        if action == "reply":
            assert len(after["outbox"]) == len(before["outbox"]) + 1
            assert after["outbox"][-1]["payload"]["agent"] is True
            assert after["conversation"] == before["conversation"]
        else:
            assert after["outbox"] == before["outbox"]
            assert after["conversation"][0]["state"] == "BOT_ACTIVE"
            assert after["handoff"][0]["status"] == "RETURNED"


@pytest.mark.parametrize("action", ["reply", "return"])
@pytest.mark.parametrize("mode", ["absent", "expired", "revoked", "inactive"])
async def test_session_lifecycle_is_enforced_before_mutation(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str, mode: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    headers = actors["A"]["headers"]
    if mode == "absent":
        headers = {}
    elif mode == "revoked":
        response = await client.post("/admin/logout", headers=headers)
        assert response.status_code == 200
    elif mode == "inactive":
        response = await client.post(f'/admin/agents/{actors["A"]["id"]}/deactivate',
                                     headers=actors["ADMIN"]["headers"])
        assert response.status_code == 200
        # Deactivation also revokes sessions. Its real revocation returns 401 here.
    else:
        async with db() as session, session.begin():
            await session.execute(update(AgentSession).where(
                AgentSession.agent_id == actors["A"]["id"],
            ).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    before = await snapshot(db)
    response = await mutate(client, action, ids, headers)
    after = await snapshot(db)
    evidence(request, before=before, after=after, http_status=response.status_code, mode=mode)
    assert response.status_code == 401
    assert after == before


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_inactive_agent_with_unrevoked_session_is_rejected(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    # Persisted legacy inconsistency, not a new deactivation endpoint or auth override.
    async with db() as session, session.begin():
        await session.execute(update(Agent).where(Agent.id == actors["A"]["id"]).values(
            active=False))
    before = await snapshot(db)
    response = await mutate(client, action, ids, actors["A"]["headers"])
    after = await snapshot(db)
    evidence(request, before=before, after=after, http_status=response.status_code)
    assert response.status_code == 403 and after == before


@pytest.mark.parametrize("action", ["reply", "return"])
@pytest.mark.parametrize("defect", [
    "conversation_null", "handoff_null", "different_ids", "no_open_case", "two_taken",
    "extra_pending", "wrong_state", "bot_enabled", "pending_owned", "crossed_relation",
])
async def test_incoherent_assignments_do_not_authorize_or_repair(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str, defect: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    other_id = (await seed_case(db, pending=False))[0] if defect == "crossed_relation" else None
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, ids[0])
        handoff = await session.get(Handoff, ids[1])
        if defect == "conversation_null":
            conversation.assigned_agent_id = None
        elif defect == "handoff_null":
            handoff.assigned_agent_id = None
        elif defect == "different_ids":
            handoff.assigned_agent_id = actors["B"]["id"]
        elif defect == "no_open_case":
            handoff.status = "RESOLVED"
        elif defect in {"two_taken", "extra_pending"}:
            session.add(Handoff(conversation_id=ids[0],
                                status="TAKEN" if defect == "two_taken" else "PENDING",
                                assigned_agent_id=actors["A"]["id"], reason="CUSTOMER_REQUEST",
                                priority="NORMAL", summary="No elegir ultimo arbitrariamente"))
        elif defect == "wrong_state":
            conversation.state = "BOT_ACTIVE"
        elif defect == "bot_enabled":
            conversation.bot_enabled = True
        elif defect == "pending_owned":
            handoff.status = "PENDING"
        else:
            handoff.conversation_id = other_id
    before = await snapshot(db)
    response = await mutate(client, action, ids, actors["A"]["headers"])
    after = await snapshot(db)
    evidence(request, defect=defect, before=before, after=after, http_status=response.status_code)
    assert response.status_code == 409
    assert after == before


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_nonexistent_resources_preserve_existing_cases(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    await take_case(db, client, actors["A"])
    before = await snapshot(db)
    response = await mutate(client, action, (999999, 999999), actors["A"]["headers"])
    after = await snapshot(db)
    evidence(request, before=before, after=after, http_status=response.status_code)
    assert response.status_code == 404 and after == before


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_historical_display_name_and_body_id_do_not_grant_ownership(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    async with db() as session, session.begin():
        await session.execute(update(Agent).where(Agent.id == actors["A"]["id"]).values(
            name="R8 A renamed"))
        await session.execute(update(Agent).where(Agent.id == actors["B"]["id"]).values(
            name="R8 A"))
    before = await snapshot(db)
    assert before["handoff"][0]["assigned_to"] == "R8 A"
    path = f"/admin/conversations/{ids[0]}/messages" if action == "reply" else (
        f"/admin/handoffs/{ids[1]}/return")
    response = await client.post(path, headers=actors["B"]["headers"], json={
        "agent_id": actors["A"]["id"], "agent": "R8 A", "text": "No autorizado",
        "resolution": "No autorizada",
    })
    denied = await snapshot(db)
    assert response.status_code == 403 and denied == before
    owner = await mutate(client, action, ids, actors["A"]["headers"])
    evidence(request, before=before, denied=denied, final=await snapshot(db),
             http_status=response.status_code, owner_status=owner.status_code)
    assert owner.status_code == 200


@pytest.mark.parametrize("mode", [
    "pending_conversation_owner", "pending_handoff_owner", "pending_legacy_label",
    "pending_multiple", "direct_owner", "direct_pending", "direct_taken",
])
async def test_take_does_not_repair_or_steal_inconsistent_cases(
    db: Any, api: Any, request: pytest.FixtureRequest, mode: str,
) -> None:
    client, actors = api
    pending = mode.startswith("pending")
    ids = await seed_case(db, pending=pending)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, ids[0])
        handoff = await session.get(Handoff, ids[1]) if ids[1] is not None else None
        if mode in {"pending_conversation_owner", "direct_owner"}:
            conversation.assigned_agent_id = actors["A"]["id"]
        elif mode == "pending_handoff_owner":
            handoff.assigned_agent_id = actors["A"]["id"]
        elif mode == "pending_legacy_label":
            handoff.assigned_to = "Etiqueta sin identidad"
        else:
            session.add(Handoff(conversation_id=ids[0], reason="CUSTOMER_REQUEST",
                                status="TAKEN" if mode == "direct_taken" else "PENDING",
                                priority="NORMAL", summary="Caso abierto no reparable"))
    before = await snapshot(db)
    path = f"/admin/handoffs/{ids[1]}/take" if pending else (
        f"/admin/conversations/{ids[0]}/take")
    response = await client.post(path, headers=actors["B"]["headers"])
    after = await snapshot(db)
    evidence(request, before=before, after=after, mode=mode, http_status=response.status_code)
    assert response.status_code == 409 and after == before


async def test_shared_reads_and_existing_admin_restrictions_remain(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    before = await snapshot(db)
    for path in ["/admin/conversations", "/admin/handoffs?status=TAKEN",
                 f"/admin/conversations/{ids[0]}/messages",
                 f"/admin/conversations/{ids[0]}/history"]:
        response = await client.get(path, headers=actors["B"]["headers"])
        assert response.status_code == 200
    mine = await client.get("/admin/conversations?assigned_to_me=true",
                            headers=actors["B"]["headers"])
    assert mine.status_code == 200 and mine.json() == []
    denied = await client.post("/admin/agents", headers=actors["B"]["headers"],
                               json={"name": "No autorizado", "role": "AGENT"})
    assert denied.status_code == 403
    after = await snapshot(db)
    evidence(request, before=before, after=after, shared_reads=200, admin_control=403)
    assert after == before


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_r4_case_and_r5_payment_summary_survive_nonowner_denial(
    db: Any, api: Any, request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    client, actors = api
    configure(monkeypatch)
    with respx.mock:
        event_id = await prepare(db)
        await inbound.process_webhook_event(event_id, db)
        async with db() as session:
            case_id = await session.scalar(select(Handoff.id))
        take = await client.post(f"/admin/handoffs/{case_id}/take",
                                 headers=actors["A"]["headers"])
        assert take.status_code == 200
        # Only select payment context for this synthetic case; do not confirm payment.
        async with db() as session, session.begin():
            handoff = await session.get(Handoff, case_id)
            handoff.reason = "PAYMENT_REVIEW"
        await inbound.process_whatsapp_webhook(media_payload(
            caption="Comprobante sintetico", external_id="r8.passive.payment"), db)
        before = await snapshot(db)
        assert len(before["payment_evidence"]) == 1
        assert "evidencia #" in before["handoff"][0]["summary"]
        response = await mutate(client, action, (1, case_id), actors["B"]["headers"])
        after = await snapshot(db)
    evidence(request, before=before, after=after, http_status=response.status_code,
             boundary="Real R4 intake/take; synthetic payment context; real R5 capture")
    assert response.status_code == 403 and after == before
