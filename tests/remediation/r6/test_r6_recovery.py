"""Real commit/cancellation boundaries and independent-session ownership races."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx

from app.channel import inbound, inbox
from app.channel.models import InboxJob
from app.conversation.models import Conversation
from app.orchestrator.inbox_effects import AgendaResults
from tests.remediation.r2.test_r2_inbox import claim, install_commit_failure, remove_commit_failure
from tests.remediation.r3.helpers import MAIN, Provider
from tests.remediation.r4.helpers import configure, message_payload
from tests.remediation.r6.helpers import (
    actions,
    completed,
    entity,
    prepare,
    proposal,
    send,
    snapshot,
)
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio
DOMAIN_TABLES = ("customer", "conversation", "lead", "event", "event_service_request",
                 "quote_request", "message", "outbox", "audit_event", "handoff", "appointment")


async def pending_turn(db: Any, family: str = "classification") -> int:
    body = (
        'Mi nombre tal vez sea Nombre Vigente' if family == 'name' else 'Quiero cotizar mi evento'
    )
    event = await prepare(db, body=body, name=None if family == "name" else "Cliente Sintetico R6")
    response = proposal(entities=[entity(
        "full_name", "Nombre Vigente", quality_status="PENDING_CONFIRMATION",
        needs_confirmation=True)]) if family == "name" else proposal(confidence=0.65)
    first = await send(db, body, response, event_id=event)
    completed(first)
    event = await inbound.store_webhook_event(message_payload("r6.confirm", "sí"), db, None)
    await inbox.expand_event(db, event, datetime.now(UTC))
    return event


async def process(db: Any, current: inbox.InboxClaim) -> str:
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [proposal()]})
        result = await inbox.process_claimed_inbox(db, current)
    provider.exhausted()
    return result


def accepted_once(final: dict[str, Any], family: str) -> None:
    assert actions(final, "AI_CONFIRMATION_ACCEPTED") == int(family == "classification")
    assert actions(final, "CUSTOMER_NAME_CONFIRMED") == int(family == "name")
    assert final["conversation"][0]["pending_confirmation"] is None
    assert all(j["status"] == "COMPLETED" for j in final["inbox_job"])
    assert len(final["quote_request"]) == 1
    assert final["quote_request"][0]["request_status"] == "DRAFT"
    assert not final["handoff"] and not final["appointment"]


@pytest.mark.parametrize("family", ["classification", "name"])
async def test_commit_rollback_recovery_and_projection_replay(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    configure(monkeypatch)
    event = await pending_turn(db, family)
    current = await claim(db)
    before = await snapshot(db)
    await install_commit_failure(db, current.id)
    try:
        assert await process(db, current) == "FAILED"
        failed = await snapshot(db)
        for table in DOMAIN_TABLES:
            assert failed[table] == before[table], table
        assert failed["inbox_job"][1]["status"] == "PENDING"
        assert failed["inbox_job"][1]["completed_at"] is None
    finally:
        await remove_commit_failure(db)
    resumed = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
    assert await process(db, resumed) == 'COMPLETED'
    final = await snapshot(db)
    accepted_once(final, family)
    # The commit happened, but the webhook projection has not been refreshed.
    assert next(e for e in final["webhook_event"] if e["id"] == event)["status"] == "PREPARED"
    with respx.mock:
        await inbox.process_event(event, db)
    repeated = await snapshot(db)
    for table in (*DOMAIN_TABLES, "inbox_job"):
        assert repeated[table] == final[table], table
    evidence(request, before=before, failed=failed, final=final, repeated=repeated)


@pytest.mark.parametrize("family", ["classification", "name"])
async def test_cancel_after_real_effects_before_commit(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    configure(monkeypatch)
    await pending_turn(db, family)
    current = await claim(db)
    before = await snapshot(db)
    entered, release = asyncio.Event(), asyncio.Event()
    original = inbound.orchestrate_inbound_message

    async def barrier(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        entered.set()
        await release.wait()

    with monkeypatch.context() as scoped:
        scoped.setattr(inbound, "orchestrate_inbound_message", barrier)
        task = asyncio.create_task(process(db, current))
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
    cancelled = await snapshot(db)
    for table in DOMAIN_TABLES:
        assert cancelled[table] == before[table], table
    assert cancelled["inbox_job"][1]["status"] == "PENDING"
    assert cancelled["inbox_job"][1]["completed_at"] is None
    assert await process(db, await claim(db)) == "COMPLETED"
    final = await snapshot(db)
    accepted_once(final, family)
    evidence(request, before=before, cancelled=cancelled, final=final)


@pytest.mark.parametrize("family", ["classification", "name"])
@pytest.mark.parametrize("mode", ["context_replaced", "ownership_lost"])
async def test_stale_acquisition_cannot_consume_replacement(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    family: str, mode: str
) -> None:
    configure(monkeypatch)
    await pending_turn(db, family)
    old = await claim(db)
    entered, release = asyncio.Event(), asyncio.Event()
    original = inbound.classify_message

    async def barrier(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(inbound, "classify_message", barrier)
        task = asyncio.create_task(process(db, old))
        await asyncio.wait_for(entered.wait(), 10)
        if mode == "ownership_lost":
            await inbox.settle_inbox_failure(db, old, RuntimeError("Synthetic owner released"))
        # Explicit synthetic context replacement at the real B/C boundary, independent session.
        async with db() as session, session.begin():
            conversation = await session.get(Conversation, 1, with_for_update=True)
            replacement = deepcopy(conversation.pending_confirmation)
            if family == "name":
                replacement["full_name"] = "Propuesta Nueva"
            else:
                replacement["classification"]["reasoning_code"] = "R6_REPLACEMENT"
                replacement["classification"]["extracted_entities"] = [
                    entity("guest_count", 50, quality_status="CORRECTED")]
            conversation.pending_confirmation = replacement
        if mode == "ownership_lost":
            new_owner = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
            assert new_owner.claim_token != old.claim_token
        before = await snapshot(db)
        release.set()
        result = await asyncio.wait_for(task, 10)
    final = await snapshot(db)
    assert result == ("RETRY" if mode == "context_replaced" else "DISCARDED")
    for table in DOMAIN_TABLES:
        assert final[table] == before[table], table
    assert final["conversation"][0]["pending_confirmation"] == replacement
    if mode == "ownership_lost":
        assert final["inbox_job"] == before["inbox_job"]
    evidence(request, before=before, final=final, result=result,
             boundary="Real classification finished; replacement fixture committed before apply")


@pytest.mark.parametrize("mode", ["sequential", "concurrent"])
async def test_same_message_redelivery_applies_confirmation_once(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configure(monkeypatch)
    event = await pending_turn(db)
    before = await snapshot(db)
    entered, release = asyncio.Event(), asyncio.Event()
    original = inbound.orchestrate_inbound_message

    async def barrier(*args: Any, **kwargs: Any) -> None:
        entered.set()
        await release.wait()
        await original(*args, **kwargs)

    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [proposal()]})
        if mode == "concurrent":
            with monkeypatch.context() as scoped:
                scoped.setattr(inbound, "orchestrate_inbound_message", barrier)
                first = asyncio.create_task(inbox.process_event(event, db))
                await asyncio.wait_for(entered.wait(), 10)
                second_started = asyncio.Event()

                async def redelivery() -> None:
                    second_started.set()
                    await inbox.process_event(event, db)

                duplicate = asyncio.create_task(redelivery())
                await asyncio.wait_for(second_started.wait(), 10)
                release.set()
                await asyncio.wait_for(asyncio.gather(first, duplicate), 10)
        else:
            await inbox.process_event(event, db)
        await inbound.process_whatsapp_webhook(message_payload("r6.confirm", "sí"), db)
    provider.exhausted()
    final = await snapshot(db)
    accepted_once(final, "classification")
    assert final["message"] == before["message"]
    evidence(request, before=before, final=final, calls=provider.calls)


async def test_two_consumers_cannot_apply_same_acquisition_twice(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    await pending_turn(db)
    current = await claim(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [proposal()]})
        turn = await inbound.classify_message(current.persisted, db, None)
    provider.exhausted()
    start = asyncio.Event()

    async def consumer() -> str:
        await start.wait()
        return await inbox.apply_turn(db, current, turn, AgendaResults())

    tasks = [asyncio.create_task(consumer()), asyncio.create_task(consumer())]
    start.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    final = await snapshot(db)
    assert sorted(outcomes) == ["COMPLETED", "DISCARDED"]
    accepted_once(final, "classification")
    evidence(request, final=final, outcomes=outcomes)


@pytest.mark.parametrize("status", ["FAILED", "REVIEW", "EXTERNAL"])
async def test_previous_blocker_keeps_pending_unauthorized(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    configure(monkeypatch)
    await pending_turn(db)
    current = await claim(db)
    async with db() as session, session.begin():
        job = await session.get(InboxJob, current.id)
        if status == "EXTERNAL":
            job.status = status
            job.external_operation = "synthetic_uncertain"
        else:
            inbox.retire(job, status, "R6_SYNTHETIC_BLOCKER")
    before = await snapshot(db)
    with respx.mock:
        await inbound.process_whatsapp_webhook(message_payload("r6.blocked", "sí"), db)
    final = await snapshot(db)
    assert final["conversation"] == before["conversation"]
    assert final["inbox_job"][1] == before["inbox_job"][1]
    assert final["inbox_job"][2]["status"] == "PENDING"
    assert actions(final, "AI_CONFIRMATION_ACCEPTED") == 0
    assert final["outbox"] == before["outbox"]
    evidence(request, before=before, final=final)
