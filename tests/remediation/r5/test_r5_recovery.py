"""Owned passive effects, real commit rollback, and reproducible phase boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx

from app.channel import inbound, inbox
from app.channel.models import InboxJob
from app.conversation.models import Conversation
from app.handoff.models import Handoff
from app.orchestrator.inbox_effects import AgendaResults
from tests.remediation.r2.test_r2_inbox import (
    claim,
    install_commit_failure,
    remove_commit_failure,
)
from tests.remediation.r3.helpers import MAIN, Provider, valid
from tests.remediation.r4.helpers import configure
from tests.remediation.r5.helpers import assert_passive, media_payload, prepare, snapshot
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


async def test_real_commit_failure_then_recovery(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    event = await prepare(db, caption="Pago", payment="TAKEN")
    current = await claim(db)
    before = await snapshot(db)
    await install_commit_failure(db, current.id)
    try:
        assert await inbox.process_claimed_inbox(db, current) == "FAILED"
        failed = await snapshot(db)
        for table in ("message", "outbox", "handoff", "payment_evidence", "audit_event"):
            assert failed[table] == before[table]
        assert failed["inbox_job"][0]["status"] == "PENDING"
        assert failed["inbox_job"][0]["completed_at"] is None
    finally:
        await remove_commit_failure(db)
    resumed = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
    assert await inbox.process_claimed_inbox(db, resumed) == "COMPLETED"
    final = await snapshot(db)
    assert_passive(before, final, True)
    # Local commit survives a lost WebhookEvent projection; retry only refreshes it.
    await inbox.process_event(event, db)
    repeated = await snapshot(db)
    for table in ("message", "outbox", "handoff", "payment_evidence", "audit_event", "inbox_job"):
        assert repeated[table] == final[table]
    evidence(request, before=before, failed=failed, final=final, repeated=repeated)


async def test_lost_owner_cannot_apply_passive_effects(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    await prepare(db, payment="TAKEN")
    old = await claim(db)
    await inbox.settle_inbox_failure(db, old, RuntimeError("synthetic release"))
    current = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
    before = await snapshot(db)
    assert await inbox.apply_turn(db, old, None, AgendaResults()) == "DISCARDED"
    assert await snapshot(db) == before
    assert await inbox.process_claimed_inbox(db, current) == "COMPLETED"
    final = await snapshot(db)
    assert_passive(before, final, True)
    evidence(request, before=before, final=final)


@pytest.mark.parametrize("change", ["pause", "activate", "close_case"])
async def test_state_and_case_are_rechecked_at_apply(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    configure(monkeypatch)
    await prepare(db, caption="Pago", payment="TAKEN",
                  state="BOT_ACTIVE" if change == "pause" else "HUMAN_ACTIVE",
                  enabled=change == "pause")
    current = await claim(db)
    turn = None
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        if change == "pause":
            turn = await inbound.classify_message(current.persisted, db, None)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        if change != "close_case":
            conversation.state = "HUMAN_ACTIVE" if change == "pause" else "BOT_ACTIVE"
            conversation.bot_enabled = change == "activate"
        else:
            (await session.get(Handoff, 1)).status = "RESOLVED"
    before = await snapshot(db)
    result = await inbox.apply_turn(db, current, turn, AgendaResults())
    final = await snapshot(db)
    evidence(request, before=before, final=final, result=result, calls=provider.calls)
    if change == "activate":
        assert result == "RETRY" and final["payment_evidence"] == []
        assert final["inbox_job"][0]["last_error"] == "CONTEXT_CHANGED_RECLASSIFY"
        with respx.mock as router:
            resumed_provider = Provider(router, {MAIN: [valid()]})
            resumed = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
            assert await inbox.process_claimed_inbox(db, resumed) == "COMPLETED"
            assert resumed_provider.calls == {MAIN: 1}
        recovered = await snapshot(db)
        assert recovered["message"] == before["message"]
        evidence(request, before=before, retry=final, recovered=recovered,
                 calls=resumed_provider.calls)
    else:
        assert result == "COMPLETED"
        assert_passive(before, final, change == "pause")


@pytest.mark.parametrize("mode", ["sequential", "concurrent", "distinct"])
async def test_redelivery_and_distinct_messages(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    configure(monkeypatch)
    event = await prepare(db, payment="TAKEN")
    before = await snapshot(db)
    if mode == "concurrent":
        await asyncio.gather(inbox.process_event(event, db), inbox.process_event(event, db))
        await inbox.process_event(event, db)
    else:
        await inbox.process_event(event, db)
        await inbound.process_whatsapp_webhook(media_payload(
            external_id="r5.distinct" if mode == "distinct" else "r5.synthetic"), db)
    final = await snapshot(db)
    evidence(request, before=before, final=final)
    count = 2 if mode == "distinct" else 1
    assert len(final["message"]) == len(final["payment_evidence"]) == count
    assert all(j["status"] == "COMPLETED" for j in final["inbox_job"])
    assert final["outbox"] == [] and len(final["handoff"]) == 1
    assert sum(a["action"] == "PAYMENT_EVIDENCE_CREATED" for a in final["audit_event"]) == count
    assert sum(a["action"] == "HANDOFF_PRIORITY_RAISED" for a in final["audit_event"]) == 1


@pytest.mark.parametrize("status", ["FAILED", "REVIEW", "EXTERNAL"])
async def test_prior_blocker_is_not_bypassed(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    configure(monkeypatch)
    await prepare(db, payment="TAKEN")
    current = await claim(db)
    async with db() as session, session.begin():
        job = await session.get(InboxJob, current.id)
        if status == "EXTERNAL":
            job.status = status
            job.external_operation = "synthetic_uncertain"
        else:
            inbox.retire(job, status, "synthetic_prior_blocker")
    before = await snapshot(db)
    await inbound.process_whatsapp_webhook(media_payload(external_id="r5.blocked"), db)
    final = await snapshot(db)
    evidence(request, before=before, final=final)
    assert final["inbox_job"][0] == before["inbox_job"][0]
    assert final["inbox_job"][1]["status"] == "PENDING"
    assert final["payment_evidence"] == final["outbox"] == []


async def test_cancel_before_commit_and_reacquire(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    await prepare(db, payment="TAKEN")
    current = await claim(db)
    before = await snapshot(db)
    entered, release = asyncio.Event(), asyncio.Event()
    original = inbound.route_non_text_in_session

    async def barrier(*args: Any, **kwargs: Any) -> bool:
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(inbound, "route_non_text_in_session", barrier)
        task = asyncio.create_task(inbox.process_claimed_inbox(db, current))
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
    cancelled = await snapshot(db)
    for table in ("payment_evidence", "handoff", "audit_event", "outbox"):
        assert cancelled[table] == before[table]
    assert cancelled["inbox_job"][0]["status"] == "PENDING"
    assert await inbox.process_claimed_inbox(db, await claim(db)) == "COMPLETED"
    final = await snapshot(db)
    assert_passive(before, final, True)
    evidence(request, before=before, cancelled=cancelled, final=final)


async def test_busy_handoff_rolls_back_without_waiting_under_conversation_lock(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    await prepare(db, payment="TAKEN")
    current = await claim(db)
    before = await snapshot(db)
    async with db() as admin, admin.begin():
        await admin.get(Handoff, 1, with_for_update=True)
        # The admin owns Handoff first, like /return. A blocking reverse lock would hang.
        result = await asyncio.wait_for(inbox.process_claimed_inbox(db, current), 5)
        assert result == "FAILED"
        await admin.get(Conversation, 1, with_for_update=True)
    failed = await snapshot(db)
    for table in ("payment_evidence", "handoff", "audit_event", "outbox"):
        assert failed[table] == before[table]
    assert await inbox.process_claimed_inbox(
        db, await claim(db, datetime.now(UTC) + timedelta(seconds=5))) == "COMPLETED"
    final = await snapshot(db)
    assert_passive(before, final, True)
    evidence(request, before=before, failed=failed, final=final)


async def test_two_consumers_of_same_claim_commit_only_once(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    await prepare(db, payment="TAKEN")
    current = await claim(db)
    before = await snapshot(db)
    start = asyncio.Event()

    async def consumer() -> str:
        await start.wait()
        return await inbox.process_claimed_inbox(db, current)

    tasks = [asyncio.create_task(consumer()), asyncio.create_task(consumer())]
    start.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    final = await snapshot(db)
    assert sorted(outcomes) == ["COMPLETED", "DISCARDED"]
    assert_passive(before, final, True)
    evidence(request, before=before, final=final, outcomes=outcomes)
