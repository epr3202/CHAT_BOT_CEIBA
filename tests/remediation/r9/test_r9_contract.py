"""Risk coverage added after the BASE-compatible RED; no retroactive RED claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import respx
from sqlalchemy import select

from app.channel import inbound
from app.channel.delivery import admit_outbox
from app.channel.models import Outbox
from app.channel.worker import (
    claim_due_outbox_batch,
    process_claimed_outbox_item,
    process_outbox_once,
    recover_stale_sending_outbox,
    settle_outbox_failure,
    settle_outbox_success,
)
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.customer.models import Customer
from app.handoff.service import create_handoff
from tests.remediation.r4.helpers import configure, message_payload, prepare
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import snapshot
from tests.remediation.r9.helpers import Sender, enqueue, take
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


async def pause(db: Any, conversation_id: int, mode: str) -> None:
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if mode.startswith("waiting"):
            customer = await session.get(Customer, conversation.customer_id)
            await create_handoff(session, conversation, customer, "CUSTOMER_REQUEST", "NORMAL",
                                 "r9", get_settings())
            if mode == "waiting_disabled":
                conversation.bot_enabled = False
        elif mode == "closed":
            await transition_conversation(session, conversation, "CLOSED", "SYSTEM", "R9 test")
        else:
            # No new endpoint: exercise the model assignment used by real catalog writers.
            conversation.bot_enabled = False


async def run_claim(db: Any, item: Any, sender: Any) -> Any:
    return await process_claimed_outbox_item(db, item, sender, 5, 300)


async def return_case(api: Any, handoff_id: int) -> None:
    client, actors = api
    response = await client.post(f"/admin/handoffs/{handoff_id}/return",
                                 headers=actors["A"]["headers"], json={"resolution": "R9 return"})
    assert response.status_code == 200


@pytest.mark.parametrize("kind", ["TEXT", "DOCUMENT"])
@pytest.mark.parametrize("mode", ["waiting", "waiting_disabled", "disabled", "closed"])
async def test_legitimate_pause_invalidates_period(
    db: Any, request: pytest.FixtureRequest, kind: str, mode: str,
) -> None:
    conversation_id, _ = await enqueue(db, kind)
    before = await snapshot(db)
    await pause(db, conversation_id, mode)
    paused = await snapshot(db)
    sender = Sender()
    with respx.mock:
        await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, before=before, paused=paused, after=after, sends=sender.sends)
    assert paused["conversation"][0]["automation_epoch"] != (
        before["conversation"][0]["automation_epoch"])
    assert sender.sends == sender.uploads == []
    assert after["outbox"][0]["status"] == "SUPPRESSED"
    assert after["outbox"][0]["attempts"] == 0
    assert after["message"] == paused["message"]
    assert after["audit_event"] == paused["audit_event"]


@pytest.mark.parametrize("queued", ["pending", "backoff", "claimed"])
async def test_unobserved_pause_return_never_revives_old_output(
    db: Any, api: Any, request: pytest.FixtureRequest, queued: str,
) -> None:
    conversation_id, outbox_id = await enqueue(db)
    at = datetime.now(UTC)
    before = await snapshot(db)
    claims = []
    if queued == "claimed":
        claims = await claim_due_outbox_batch(db, at, 10)
    elif queued == "backoff":
        async with db() as session, session.begin():
            row = await session.get(Outbox, outbox_id)
            row.attempts, row.next_attempt_at = 1, at + timedelta(seconds=10)
    handoff_id = await take(api, conversation_id)
    await return_case(api, handoff_id)
    # Same externally supplied clock; identity cannot depend on its resolution.
    await enqueue(db, conversation_id=conversation_id)
    sender = Sender()
    with respx.mock:
        for item in claims:
            await run_claim(db, item, sender)
        await process_outbox_once(db, sender, now=at + timedelta(seconds=11))
    after = await snapshot(db)
    evidence(request, before=before, after=after, sends=sender.sends, clock=at)
    assert [row["status"] for row in after["outbox"]] == ["SUPPRESSED", "SENT"]
    assert len(sender.sends) == 1
    assert after["conversation"][0]["state"] == "BOT_ACTIVE"
    assert before["conversation"][0]["automation_epoch"] != (
        after["conversation"][0]["automation_epoch"])


@pytest.mark.parametrize("later", ["pause", "return", "new_owner"])
async def test_human_origin_survives_later_control_changes(
    db: Any, api: Any, request: pytest.FixtureRequest, later: str,
) -> None:
    from tests.remediation.r8.helpers import seed_case

    conversation_id, _ = await seed_case(db, pending=False)
    handoff_id = await take(api, conversation_id)
    client, actors = api
    for _ in range(2):
        response = await client.post(f"/admin/conversations/{conversation_id}/messages",
                                     headers=actors["A"]["headers"],
                                     json={"text": "Mismo texto R9"})
        assert response.status_code == 200
    if later != "pause":
        await return_case(api, handoff_id)
    if later == "new_owner":
        await take(api, conversation_id, "B")
    sender = Sender()
    with respx.mock:
        await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, after=after, sends=sender.sends)
    assert len(sender.sends) == 2  # Intentional equal human texts are not deduplicated.
    assert all(row["status"] == "SENT" for row in after["outbox"])


@pytest.mark.parametrize("later", ["pending", "taken", "returned"])
async def test_r4_notice_is_authorized_only_for_its_pending_wait(
    db: Any, api: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
    later: str,
) -> None:
    configure(monkeypatch)
    event_id = await prepare(db, external_id="r9.r4.notice")
    with respx.mock:
        await inbound.process_webhook_event(event_id, db)
    waiting = await snapshot(db)
    assert waiting["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
    assert waiting["conversation"][0]["bot_enabled"] is True
    assert waiting["handoff"][0]["status"] == "PENDING"
    if later != "pending":
        client, actors = api
        response = await client.post(f'/admin/handoffs/{waiting["handoff"][0]["id"]}/take',
                                     headers=actors["A"]["headers"])
        assert response.status_code == 200
        if later == "returned":
            await return_case(api, waiting["handoff"][0]["id"])
    sender = Sender()
    with respx.mock:
        await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, waiting=waiting, after=after, sends=sender.sends)
    assert len(sender.sends) == int(later == "pending")
    assert after["outbox"][0]["status"] == ("SENT" if later == "pending" else "SUPPRESSED")


@pytest.mark.parametrize("agent_mark", [True, "true", "false", 1])
async def test_payload_cannot_grant_human_origin(
    db: Any, api: Any, request: pytest.FixtureRequest, agent_mark: Any,
) -> None:
    conversation_id, outbox_id = await enqueue(db)
    async with db() as session, session.begin():
        row = await session.get(Outbox, outbox_id)
        row.payload = {**row.payload, "agent": agent_mark}
    await take(api, conversation_id)
    sender = Sender()
    await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, after=after, sends=sender.sends)
    assert sender.sends == [] and after["outbox"][0]["status"] == "SUPPRESSED"


@pytest.mark.parametrize("tamper", ["unknown_origin", "human_without_proof", "wrong_case"])
async def test_unproven_context_never_creates_exception(
    db: Any, request: pytest.FixtureRequest, tamper: str,
) -> None:
    conversation_id, outbox_id = await enqueue(db)
    await pause(db, conversation_id, "waiting")
    async with db() as session, session.begin():
        row = await session.get(Outbox, outbox_id)
        conversation = await session.get(Conversation, conversation_id)
        row.delivery_context = {
            "unknown_origin": {"origin": "SYSTEM"},
            "human_without_proof": {"origin": "HUMAN_REPLY", "agent_id": 1},
            "wrong_case": {"origin": "HANDOFF_NOTICE", "purpose": "TRANSFER",
                           "epoch": str(conversation.automation_epoch), "case_id": 999999},
        }[tamper]
        row.payload = {**row.payload, "agent": True}
    sender = Sender()
    await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, after=after, sends=sender.sends)
    assert sender.sends == [] and after["outbox"][0]["status"] == "REVIEW"


async def test_terminal_suppression_resists_reaper_and_old_callbacks(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    conversation_id, outbox_id = await enqueue(db)
    at = datetime.now(UTC)
    claims = await claim_due_outbox_batch(db, at, 10)
    item = claims[0]
    await take(api, conversation_id)
    sender = Sender()
    await run_claim(db, item, sender)
    before = await snapshot(db)
    for token in [item.claim_token, uuid4()]:
        assert await settle_outbox_success(db, outbox_id, "obsolete", "r9.obsolete", at,
                                           5, 300, claim_token=token) == "DISCARDED"
        assert await settle_outbox_failure(db, outbox_id, TimeoutError("obsolete"), at,
                                           5, 300, claim_token=token) == "DISCARDED"
    assert await recover_stale_sending_outbox(db, at + timedelta(seconds=121), 120, 5, 300) == 0
    assert await claim_due_outbox_batch(db, at + timedelta(seconds=150), 10) == []
    await run_claim(db, item, sender)
    after = await snapshot(db)
    evidence(request, before=before, after=after, sends=sender.sends)
    assert before == after and sender.sends == []


async def test_claiming_batch_is_not_send_admission(db: Any, api: Any) -> None:
    first, _ = await enqueue(db)
    await enqueue(db)
    claims = await claim_due_outbox_batch(db, datetime.now(UTC), 10)
    assert len(claims) == 2
    assert all(r["send_admission"] is None for r in (await snapshot(db))["outbox"])
    await take(api, first)
    sender = Sender()
    for item in claims:
        await run_claim(db, item, sender)
    assert len(sender.sends) == 1
    assert [r["status"] for r in (await snapshot(db))["outbox"]] == ["SUPPRESSED", "SENT"]


async def test_admission_is_persisted_and_cannot_be_reused(db: Any) -> None:
    await enqueue(db)
    item = (await claim_due_outbox_batch(db, datetime.now(UTC), 1))[0]
    assert await admit_outbox(db, item.id, item.claim_token) == "ADMITTED"
    row = (await snapshot(db))["outbox"][0]
    assert row["send_admission"]["claim_token"] == str(item.claim_token)
    assert row["send_admission"]["phase"] == "ADMITTED"
    assert await admit_outbox(db, item.id, item.claim_token) == "DISCARDED"
    sender = Sender()
    await run_claim(db, item, sender)
    assert sender.sends == []


async def test_redelivery_does_not_recreate_suppressed_notice(
    db: Any, api: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    configure(monkeypatch)
    event_id = await prepare(db, external_id="r9.redelivery")
    with respx.mock:
        await inbound.process_webhook_event(event_id, db)
    client, actors = api
    case_id = (await snapshot(db))["handoff"][0]["id"]
    response = await client.post(f"/admin/handoffs/{case_id}/take", headers=actors["A"]["headers"])
    assert response.status_code == 200
    await process_outbox_once(db, Sender())
    before = await snapshot(db)
    duplicate = await inbound.store_webhook_event(message_payload("r9.redelivery"), db, None)
    with respx.mock:
        await inbound.process_webhook_event(duplicate, db)
    after = await snapshot(db)
    evidence(request, before=before, after=after)
    for table in ("outbox", "message", "lead", "handoff", "payment_evidence", "inbox_job"):
        assert after[table] == before[table]
    assert after["inbox_job"][0]["status"] == "COMPLETED"


@pytest.mark.parametrize("code", [
    "RESP-HANDOFF-001", "RESP-CALENDAR-ERROR-001", "RESP-CALENDAR-ERROR-002",
    "RESP-CALENDAR-ERROR-003", "RESP-CALENDAR-ERROR-004", "RESP-FALLBACK-003",
    "RESP-VISIT-CONFIRM-006", "RESP-RESCHEDULE-006", "RESP-CANCEL-VISIT-005",
    "RESP-VISIT-DATA-002", "RESP-RESCHEDULE-002",
])
async def test_transfer_producer_is_narrow_for_approved_override_purpose(
    db: Any, request: pytest.FixtureRequest, code: str,
) -> None:
    from app.ai.schemas import IntentClassification
    from app.channel.models import Message
    from app.orchestrator.service import OrchestrationInput, create_handoff_and_pause

    conversation_id, _ = await enqueue(db)
    classification = IntentClassification(primary_intent="HUMAN_REQUEST", sub_intent=None,
        confidence=1, requested_action=None, needs_confirmation=False, needs_human=True,
        handoff_reason="SYSTEM_ERROR", priority="NORMAL", reasoning_code="R9_SYNTHETIC")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        customer = await session.get(Customer, conversation.customer_id)
        message = await session.scalar(select(Message).where(
            Message.conversation_id == conversation_id))
        await create_handoff_and_pause(session, get_settings(), db,
            OrchestrationInput(conversation, customer, message, "Solicitud R9"),
            classification, "SYSTEM_ERROR", "NORMAL", response_code_override=code)
    waiting = await snapshot(db)
    assert len(waiting["outbox"]) == 2 and len(waiting["handoff"]) == 1
    sender = Sender()
    await process_outbox_once(db, sender)
    after = await snapshot(db)
    is_notice = code not in {"RESP-VISIT-DATA-002", "RESP-RESCHEDULE-002"}
    evidence(request, waiting=waiting, after=after, sends=sender.sends, code=code)
    assert [r["status"] for r in after["outbox"]] == [
        "SUPPRESSED", "SENT" if is_notice else "SUPPRESSED"]
    assert len(sender.sends) == int(is_notice)


async def test_catalog_unavailable_notice_keeps_its_pending_case(db: Any) -> None:
    from app.catalog.service import enqueue_catalog_unavailable_response
    from app.channel.models import Message

    conversation_id, _ = await enqueue(db)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        customer = await session.get(Customer, conversation.customer_id)
        message = await session.scalar(select(Message).where(
            Message.conversation_id == conversation_id))
        await enqueue_catalog_unavailable_response(session, db, conversation, customer, message,
                                                    "r9", event_type="WEDDING")
    before = await snapshot(db)
    assert before["conversation"][0]["bot_enabled"] is False
    sender = Sender()
    await process_outbox_once(db, sender)
    after = await snapshot(db)
    assert [r["status"] for r in after["outbox"]] == ["SUPPRESSED", "SENT"]
    assert len(sender.sends) == 1


async def test_ordinary_output_created_during_wait_cannot_revive_on_return(
    db: Any, api: Any,
) -> None:
    conversation_id, _ = await enqueue(db)
    await pause(db, conversation_id, "waiting")
    await enqueue(db, conversation_id=conversation_id)
    waiting = await snapshot(db)
    client, actors = api
    case_id = waiting["handoff"][0]["id"]
    response = await client.post(f"/admin/handoffs/{case_id}/take", headers=actors["A"]["headers"])
    assert response.status_code == 200
    await return_case(api, case_id)
    await enqueue(db, conversation_id=conversation_id)
    sender = Sender()
    await process_outbox_once(db, sender)
    assert [r["status"] for r in (await snapshot(db))["outbox"]] == [
        "SUPPRESSED", "SUPPRESSED", "SENT"]
    assert len(sender.sends) == 1


@pytest.mark.parametrize("decision", ["accept", "reject"])
async def test_admin_payment_decision_notification_survives_pause(
    db: Any, api: Any, request: pytest.FixtureRequest, decision: str,
) -> None:
    from app.payment.models import PaymentEvidence

    conversation_id, _ = await enqueue(db)
    handoff_id = await take(api, conversation_id)
    before = await snapshot(db)
    async with db() as session, session.begin():
        row = PaymentEvidence(conversation_id=conversation_id,
            customer_id=before["conversation"][0]["customer_id"],
            message_id=before["message"][0]["id"], media_id="r9-synthetic-evidence",
            mime_type="application/pdf", declared_sha256="0" * 64)
        session.add(row)
        await session.flush()
        evidence_id = row.id
    client, actors = api
    client._transport.app.state.settings = get_settings()
    response = await client.post(f"/admin/payment-evidence/{evidence_id}/{decision}",
                                 headers=actors["ADMIN"]["headers"], json={"note": "Revisión R9"})
    assert response.status_code == 200 and response.json()["customer_notification"] == "ENQUEUED"
    await return_case(api, handoff_id)
    await take(api, conversation_id, "B")
    sender = Sender()
    await process_outbox_once(db, sender)
    after = await snapshot(db)
    evidence(request, response=response.json(), after=after, sends=sender.sends)
    assert [r["status"] for r in after["outbox"]] == ["SUPPRESSED", "SENT"]
    assert len(sender.sends) == 1
    assert after["outbox"][1]["delivery_context"]["origin"] == "PAYMENT_REVIEW_RESULT"
