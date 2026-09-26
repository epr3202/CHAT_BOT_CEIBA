"""Actual PostgreSQL ordering and rollback; HTTP doubles never hold database locks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.catalog.models import CatalogAsset
from app.channel.delivery import admit_outbox, check_outbox
from app.channel.outbound import WhatsAppInvalidMediaError
from app.channel.worker import claim_due_outbox_batch, recover_stale_sending_outbox
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import snapshot
from tests.remediation.r8.test_r8_races import (
    finish_tasks,
    pause_after_sql,
    wait_for_database_lock,
)
from tests.remediation.r9.helpers import Sender, enqueue, take
from tests.remediation.r9.test_r9_contract import run_claim
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


class SlowSender(Sender):
    def __init__(self, *, fail: bool = False, upload: bool = False) -> None:
        super().__init__()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.fail, self.upload = fail, upload

    async def send_text(self, to: str, body: str) -> str:
        result = await super().send_text(to, body)
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), 15)
        if self.fail:
            raise TimeoutError("R9 synthetic in-flight uncertainty")
        return result

    async def upload_media(self, file_path: Path, mime_type: str) -> str:
        result = await super().upload_media(file_path, mime_type)
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), 15)
        return result


async def claim_one(db: Any) -> Any:
    return (await claim_due_outbox_batch(db, datetime.now(UTC), 1))[0]


async def test_pause_commit_before_admission_blocks_send_under_real_lock(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    sender, tasks = Sender(), []
    try:
        async with pause_after_sql(db, lambda s: s.startswith("update conversation")) as barrier:
            entered, release = barrier
            tasks.append(asyncio.create_task(take(api, conversation_id)))
            await asyncio.wait_for(entered.wait(), 10)
            tasks.append(asyncio.create_task(run_claim(db, item, sender)))
            waits = await wait_for_database_lock(db)
            uncommitted = await snapshot(db)
            assert uncommitted["conversation"][0]["state"] == "BOT_ACTIVE"
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 15)
    finally:
        await finish_tasks(tasks)
    final = await snapshot(db)
    evidence(request, uncommitted=uncommitted, final=final,
             database_waits=waits, sends=sender.sends)
    assert sender.sends == [] and final["outbox"][0]["status"] == "SUPPRESSED"


@pytest.mark.parametrize("fail", [False, True])
async def test_admitted_send_remains_external_truth_after_pause(
    db: Any, api: Any, request: pytest.FixtureRequest, fail: bool,
) -> None:
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    sender = SlowSender(fail=fail)
    task = asyncio.create_task(run_claim(db, item, sender))
    try:
        await asyncio.wait_for(sender.entered.wait(), 10)
        admitted = await snapshot(db)
        assert admitted["outbox"][0]["send_admission"]["phase"] == "ADMITTED"
        # This real endpoint completes while HTTP is blocked: no DB lock spans provider I/O.
        await asyncio.wait_for(take(api, conversation_id), 10)
        paused = await snapshot(db)
        assert paused["outbox"][0]["status"] == "SENDING"
        sender.release.set()
        await asyncio.wait_for(task, 10)
    finally:
        sender.release.set()
        await finish_tasks([task])
    final = await snapshot(db)
    evidence(request, admitted=admitted, paused=paused, final=final, sends=sender.sends)
    assert len(sender.sends) == 1
    assert final["outbox"][0]["status"] == ("REVIEW" if fail else "SENT")
    assert len(final["message"]) == (1 if fail else 2)
    assert await claim_due_outbox_batch(db, datetime.now(UTC) + timedelta(days=1), 10) == []


async def test_admission_commit_can_precede_pause_and_provider_call(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    from app.channel.worker import settle_outbox_success

    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    tasks = []
    try:
        async with pause_after_sql(db, lambda s: s.startswith("update outbox")) as barrier:
            entered, release = barrier
            tasks.append(asyncio.create_task(admit_outbox(db, item.id, item.claim_token)))
            await asyncio.wait_for(entered.wait(), 10)
            tasks.append(asyncio.create_task(take(api, conversation_id)))
            waits = await wait_for_database_lock(db)
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    finally:
        await finish_tasks(tasks)
    assert results[0] == "ADMITTED"
    before_send = await snapshot(db)
    assert before_send["conversation"][0]["state"] == "HUMAN_ACTIVE"
    # Exercise the documented permission-to-HTTP gap: the already committed attempt may call.
    sender = Sender()
    provider_id = await sender.send_text(item.recipient_phone_number, "R9 admitted before pause")
    await settle_outbox_success(db, item.id, "R9 admitted before pause", provider_id,
                                datetime.now(UTC), 5, 300, claim_token=item.claim_token)
    final = await snapshot(db)
    evidence(request, before_send=before_send, final=final,
             database_waits=waits, sends=sender.sends)
    assert final["outbox"][0]["status"] == "SENT" and len(final["message"]) == 2


async def test_slow_media_upload_requires_new_check_before_send(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    conversation_id, _ = await enqueue(db, "DOCUMENT")
    item = await claim_one(db)
    async with db() as session, session.begin():
        asset = await session.get(CatalogAsset, item.catalog_asset_id)
        asset.media_id, asset.media_uploaded_at = None, None
    sender = SlowSender(upload=True)
    task = asyncio.create_task(run_claim(db, item, sender))
    try:
        await asyncio.wait_for(sender.entered.wait(), 10)
        await asyncio.wait_for(take(api, conversation_id), 10)
        sender.release.set()
        await asyncio.wait_for(task, 10)
    finally:
        sender.release.set()
        await finish_tasks([task])
    final = await snapshot(db)
    evidence(request, final=final, sends=sender.sends, uploads=sender.uploads)
    assert len(sender.uploads) == 1 and sender.sends == []
    assert final["outbox"][0]["status"] == "SUPPRESSED"
    assert final["outbox"][0]["send_admission"] is None


async def test_invalid_media_second_send_needs_fresh_admission(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    conversation_id, _ = await enqueue(db, "DOCUMENT")
    item = await claim_one(db)

    class InvalidThenPause(Sender):
        async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
            await super().send_document(to, media_id, filename, caption)
            await take(api, conversation_id)
            raise WhatsAppInvalidMediaError("R9 known rejected media")

    sender = InvalidThenPause()
    await run_claim(db, item, sender)
    final = await snapshot(db)
    evidence(request, final=final, sends=sender.sends, uploads=sender.uploads)
    assert len(sender.sends) == 1 and sender.uploads == []
    assert final["outbox"][0]["status"] == "SUPPRESSED"
    assert final["outbox"][0]["send_admission"]["phase"] == "REJECTED_MEDIA"
    assert len(final["message"]) == 1


@pytest.mark.parametrize("operation", ["pause", "suppression", "admission"])
async def test_deferred_sql_failure_rolls_back_whole_decision(
    db: Any, api: Any, request: pytest.FixtureRequest, operation: str,
) -> None:
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    if operation == "suppression":
        await take(api, conversation_id)
    table = "conversation" if operation == "pause" else "outbox"
    before = await snapshot(db)
    async with db() as session, session.begin():
        await session.execute(text(
            "CREATE FUNCTION r9_fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'R9 deferred decision failure'; END $$",
        ))
        await session.execute(text(
            f"CREATE CONSTRAINT TRIGGER r9_commit_failure AFTER UPDATE ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION r9_fail_commit()",
        ))
    try:
        with pytest.raises(DBAPIError, match="R9 deferred decision failure"):
            if operation == "pause":
                await take(api, conversation_id)
            else:
                await admit_outbox(db, item.id, item.claim_token)
        failed = await snapshot(db)
        assert failed == before
    finally:
        async with db() as session, session.begin():
            await session.execute(text(f"DROP TRIGGER r9_commit_failure ON {table}"))
            await session.execute(text("DROP FUNCTION r9_fail_commit()"))
    sender = Sender()
    await run_claim(db, item, sender)
    final = await snapshot(db)
    evidence(request, before=before, failed=failed, final=final, sends=sender.sends)
    assert len(sender.sends) == int(operation != "suppression")


@pytest.mark.parametrize("operation", ["pause", "admission", "suppression"])
async def test_cancellation_before_commit_preserves_independent_snapshot(
    db: Any, api: Any, request: pytest.FixtureRequest, operation: str,
) -> None:
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    if operation == "suppression":
        await take(api, conversation_id)
    before = await snapshot(db)
    prefix = "update conversation" if operation == "pause" else "update outbox"
    task = None
    try:
        async with pause_after_sql(db, lambda s: s.startswith(prefix)) as (entered, release):
            operation_call = take(api, conversation_id) if operation == "pause" else (
                admit_outbox(db, item.id, item.claim_token))
            task = asyncio.create_task(operation_call)
            await asyncio.wait_for(entered.wait(), 10)
            assert await snapshot(db) == before
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
    finally:
        if task is not None:
            await finish_tasks([task])
    after = await snapshot(db)
    evidence(request, before=before, after=after, cancelled=True)
    assert after == before


async def test_reaper_does_not_retry_revoked_inflight_attempt(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    sender = SlowSender()
    task = asyncio.create_task(run_claim(db, item, sender))
    try:
        await asyncio.wait_for(sender.entered.wait(), 10)
        await take(api, conversation_id)
        assert await recover_stale_sending_outbox(
            db, datetime.now(UTC) + timedelta(seconds=121), 120, 5, 300,
        ) == 1
        before_callback = await snapshot(db)
        sender.release.set()
        assert await asyncio.wait_for(task, 10) == "DISCARDED"
    finally:
        sender.release.set()
        await finish_tasks([task])
    after = await snapshot(db)
    evidence(request, before_callback=before_callback, after=after, sends=sender.sends)
    assert after == before_callback and after["outbox"][0]["status"] == "REVIEW"
    assert len(after["message"]) == 1  # Discarded external success remains explicitly uncertain.


async def test_two_consumers_cannot_admit_same_claim_twice(
    db: Any, request: pytest.FixtureRequest,
) -> None:
    await enqueue(db)
    item = await claim_one(db)
    sender = SlowSender()
    task = asyncio.create_task(run_claim(db, item, sender))
    try:
        await asyncio.wait_for(sender.entered.wait(), 10)
        assert await run_claim(db, item, sender) == "DISCARDED"
        assert await check_outbox(db, item.id, item.claim_token) == "DISCARDED"
        assert len(sender.sends) == 1
    finally:
        sender.release.set()
        await asyncio.wait_for(task, 10)
    evidence(request, after=await snapshot(db), sends=sender.sends)


@pytest.mark.parametrize("operation", ["pause", "admission"])
@pytest.mark.parametrize("boundary", ["before_commit", "after_commit"])
async def test_killed_owned_process_keeps_committed_boundary(
    db: Any, request: pytest.FixtureRequest, operation: str, boundary: str,
) -> None:
    import multiprocessing
    import os

    from tests.remediation.r9.process_probe import checkpoint_process

    assert os.environ.get("QUALITY_STAGE") in {"suite", "regressions"}
    conversation_id, _ = await enqueue(db)
    item = await claim_one(db)
    before = await snapshot(db)
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    # Synthetic job URL only; never include it (or its credentials) in evidence.
    url = db.kw["bind"].url.render_as_string(hide_password=False)
    process = context.Process(target=checkpoint_process, args=(
        url, child, operation, boundary, conversation_id, item.id, item.claim_token,
    ))
    process.start()
    try:
        assert await asyncio.wait_for(asyncio.to_thread(parent.poll, 15), 17)
        checkpoint = parent.recv()
        assert checkpoint == ("COMMITTED" if boundary == "after_commit" else (
            "SQL_EXECUTED_UNCOMMITTED"))
        observed = await snapshot(db)
        if boundary == "before_commit":
            assert observed == before
        process.kill()
        await asyncio.wait_for(asyncio.to_thread(process.join, 10), 12)
        assert not process.is_alive() and process.exitcode == -9
        after_kill = await snapshot(db)
        if operation == "pause" and boundary == "after_commit":
            assert after_kill["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
            assert len(after_kill["handoff"]) == 1
        sender = Sender()
        if operation == "admission" and boundary == "after_commit":
            # A restarted consumer cannot reuse the persisted admission; external result unknown.
            assert await run_claim(db, item, sender) == "DISCARDED"
            assert after_kill["outbox"][0]["send_admission"]["phase"] == "ADMITTED"
        else:
            await run_claim(db, item, sender)
            assert len(sender.sends) == int(boundary == "before_commit")
        final = await snapshot(db)
        evidence(request, before=before, observed=observed, after_kill=after_kill, final=final,
                 checkpoint=checkpoint, own_child_pid=process.pid, exitcode=process.exitcode,
                 sends=sender.sends, providers="SIMULATED", guard="inherited R0, new engine")
    finally:
        if process.is_alive():
            process.kill()
        await asyncio.to_thread(process.join, 10)
        parent.close()
        child.close()


async def wait_for_any_database_lock(db: Any) -> list[dict[str, Any]]:
    async with asyncio.timeout(10):
        while True:
            async with db() as session:
                rows = (await session.execute(text(
                    "SELECT pid, pg_blocking_pids(pid) AS blockers, wait_event "
                    "FROM pg_stat_activity WHERE datname=current_database() "
                    "AND pid != pg_backend_pid() AND wait_event_type='Lock' "
                    "AND cardinality(pg_blocking_pids(pid)) > 0",
                ))).mappings().all()
            if rows:
                return [dict(row) for row in rows]
            await asyncio.sleep(0)


@pytest.mark.parametrize("contender", ["r8_denial", "r5_capture"])
async def test_delivery_locks_preserve_r8_authorization_and_r5_passive_capture(
    db: Any, api: Any, request: pytest.FixtureRequest, contender: str,
) -> None:
    import respx

    from app.channel import inbound, inbox
    from app.config.settings import get_settings
    from app.conversation.models import Conversation
    from app.customer.models import Customer
    from app.handoff.service import create_handoff
    from tests.remediation.r5.helpers import media_payload
    from tests.remediation.r8.helpers import seed_case

    conversation_id, _ = await seed_case(db, pending=False)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        customer = await session.get(Customer, conversation.customer_id)
        case, _ = await create_handoff(session, conversation, customer, "PAYMENT_REVIEW", "NORMAL",
                                       "r9", get_settings())
        await session.flush()
        case_id, phone = case.id, customer.phone_number
    client, actors = api
    response = await client.post(f"/admin/handoffs/{case_id}/take", headers=actors["A"]["headers"])
    assert response.status_code == 200
    path = f"/admin/conversations/{conversation_id}/messages"
    response = await client.post(path, headers=actors["A"]["headers"], json={"text": "R9 humano"})
    assert response.status_code == 200
    event_id = None
    if contender == "r5_capture":
        data = media_payload("image")
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        message["from"], message["id"] = phone.lstrip("+"), "r9.contended.media"
        event_id = await inbound.store_webhook_event(data, db, None)
    item = await claim_one(db)
    before = await snapshot(db)
    tasks, sender = [], Sender()
    try:
        with respx.mock:
            async with pause_after_sql(db, lambda s: s.startswith("update outbox")) as barrier:
                entered, release = barrier
                tasks.append(asyncio.create_task(run_claim(db, item, sender)))
                await asyncio.wait_for(entered.wait(), 10)
                if contender == "r8_denial":
                    action = client.post(path, headers=actors["B"]["headers"],
                                         json={"text": "R9 no autorizado"})
                else:
                    action = inbound.process_webhook_event(event_id, db)
                tasks.append(asyncio.create_task(action))
                waits = await wait_for_any_database_lock(db)
                release.set()
                results = await asyncio.wait_for(asyncio.gather(*tasks), 15)
            contended = await snapshot(db)
            progress = await inbox.process_inbox_once(db) if contender == "r5_capture" else None
    finally:
        await finish_tasks(tasks)
    after = await snapshot(db)
    evidence(request, before=before, contended=contended, after=after, progress=progress,
             database_waits=waits, sends=sender.sends, contender=contender,
             status=results[1].status_code if contender == "r8_denial" else None)
    assert len(sender.sends) == 1
    assert len(after["outbox"]) == 1 and after["outbox"][0]["status"] == "SENT"
    assert after["conversation"][0]["automation_epoch"] == (
        before["conversation"][0]["automation_epoch"])
    if contender == "r8_denial":
        assert results[1].status_code == 403
        assert after["conversation"] == before["conversation"]
        assert after["audit_event"] == before["audit_event"]
    else:
        assert len(after["payment_evidence"]) == 1
        assert after["payment_evidence"][0]["download_status"] == "PENDING"
        assert after["inbox_job"][0]["status"] == "COMPLETED"
        assert after["conversation"][0]["state"] == "HUMAN_ACTIVE"
        async with db() as session:
            assert await session.scalar(text("SELECT count(*) FROM ai_execution")) == 0
