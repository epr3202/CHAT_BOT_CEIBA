"""Token contract and transaction boundaries on real PostgreSQL sessions."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import FrozenInstanceError
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from structlog.testing import capture_logs

import app.channel.worker as worker
from app.catalog.models import CatalogAsset
from app.channel.media import PermanentCatalogMediaError
from app.channel.models import Outbox
from app.channel.outbound import WhatsAppInvalidMediaError
from tests.remediation.test_r1_outbox import (
    T0,
    Sender,
    claim,
    evidence,
    process,
    reap,
    seed,
    snapshot,
)
from tests.remediation.test_r1_outbox import (
    db as db,
)

pytestmark = pytest.mark.asyncio


async def success(db: Any, item: Any, provider: str = "r1.owner") -> Any:
    return await worker.settle_outbox_success(
        db, item.id, "synthetic reply", provider, T0, 5, 300, claim_token=item.claim_token
    )


async def failure(db: Any, item: Any, permanent: bool = False) -> Any:
    return await worker.settle_outbox_failure(
        db,
        item.id,
        TimeoutError("synthetic"),
        T0,
        5,
        300,
        permanent=permanent,
        claim_token=item.claim_token,
    )


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("second", ["success", "failure"])
async def test_double_settlement(
    db: Any, request: pytest.FixtureRequest, concurrent: bool, second: str
) -> None:
    await seed(db)
    item = await claim(db)
    start = asyncio.Event()

    async def callback(which: int) -> Any:
        await start.wait()
        if which == 2 and second == "failure":
            return await failure(db, item, permanent=True)
        return await success(db, item, "r1.callback." + str(which))

    if concurrent:
        tasks = [asyncio.create_task(callback(n)) for n in (1, 2)]
        start.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 20)
    else:
        start.set()
        outcomes = [await callback(1), await callback(2)]
    rows = await snapshot(db)
    evidence(request, final=rows, outcomes=outcomes)
    assert sorted(outcomes) == ["APPLIED", "DISCARDED"]
    row = rows["outbox"][0]
    assert row["claim_token"] is None and row["claimed_at"] is None
    if row["status"] == "SENT":
        assert row["attempts"] == 0
        assert len(rows["message"]) == 2 and rows["audit_event"] == []
    else:
        assert concurrent and second == "failure"
        assert row["status"] == "FAILED" and row["attempts"] == 1
        assert len(rows["message"]) == 1 and len(rows["audit_event"]) == 1


async def test_same_clock_new_identity_and_mandatory_immutable_owner(
    db: Any,
    request: pytest.FixtureRequest,
) -> None:
    await seed(db)
    old = await claim(db)
    with pytest.raises(FrozenInstanceError):
        old.claim_token = uuid4()
    assert (
        await worker.settle_outbox_failure(
            db, old.id, TimeoutError("synthetic"), T0, 5, 0, claim_token=old.claim_token
        )
        == "APPLIED"
    )
    current = await claim(db, T0)
    assert current.claim_token != old.claim_token
    before = await snapshot(db)
    assert before["outbox"][0]["claimed_at"] == T0
    assert await success(db, old) == "DISCARDED"
    assert await failure(db, old, permanent=True) == "DISCARDED"
    with pytest.raises(TypeError):
        await worker.settle_outbox_failure(db, old.id, TimeoutError(), T0, 5, 300)
    assert (
        await worker.settle_outbox_failure(db, old.id, TimeoutError(), T0, 5, 300, claim_token=None)
        == "DISCARDED"
    )
    after = await snapshot(db)
    evidence(request, before=before, after=after, old_token=old.claim_token)
    assert after == before
    assert await success(db, current) == "APPLIED"


async def test_claim_competition_and_independent_outputs(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await seed(db)
    start = asyncio.Event()

    async def contender() -> Any:
        await start.wait()
        return await worker.claim_due_outbox_batch(db, T0, 1)

    tasks = [asyncio.create_task(contender()) for _ in range(2)]
    start.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), 20)
    assert sorted(map(len, results)) == [0, 1]
    first = next(items[0] for items in results if items)
    slow = Sender("r1.first", blocked=True)
    task = asyncio.create_task(process(db, first, slow))
    try:
        await asyncio.wait_for(slow.started.wait(), 20)
        # A second valid output for the SAME inbound message, even with identical text.
        async with db() as session, session.begin():
            row = await session.get(Outbox, first.id)
            session.add(
                Outbox(
                    conversation_id=row.conversation_id,
                    message_id=row.message_id,
                    channel=row.channel,
                    recipient_phone_number=row.recipient_phone_number,
                    payload=row.payload,
                    created_at=T0,
                )
            )
        second = await claim(db)
        assert second.id != first.id and second.claim_token != first.claim_token
        assert await process(db, second, Sender("r1.second")) == "APPLIED"
        middle = await snapshot(db)
        assert [r["status"] for r in middle["outbox"]] == ["SENDING", "SENT"]
        slow.release.set()
        assert await asyncio.wait_for(task, 20) == "APPLIED"
        final = await snapshot(db)
        evidence(request, middle=middle, final=final)
        assert [r["status"] for r in final["outbox"]] == ["SENT", "SENT"]
        assert len(final["message"]) == 3 and final["audit_event"] == []
    finally:
        slow.release.set()
        await asyncio.gather(task, return_exceptions=True)


async def install_commit_failure(db: Any) -> None:
    async with db() as session, session.begin():
        await session.execute(
            text("""
            CREATE OR REPLACE FUNCTION r1_reject_message() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'R1 synthetic deferred commit failure'; END $$
        """)
        )
        await session.execute(
            text("""
            CREATE CONSTRAINT TRIGGER r1_deferred_failure AFTER INSERT ON message
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            WHEN (NEW.external_message_id = 'r1.rollback') EXECUTE FUNCTION r1_reject_message()
        """)
        )


async def remove_commit_failure(db: Any) -> None:
    async with db() as session, session.begin():
        await session.execute(text("DROP TRIGGER r1_deferred_failure ON message"))
        await session.execute(text("DROP FUNCTION r1_reject_message()"))


async def test_real_commit_failure_rolls_back_message_and_transition(
    db: Any,
    request: pytest.FixtureRequest,
) -> None:
    await seed(db)
    item = await claim(db)
    before = await snapshot(db)
    await install_commit_failure(db)
    try:
        with pytest.raises(DBAPIError, match="R1 synthetic deferred commit failure"):
            await success(db, item, "r1.rollback")
        after = await snapshot(db)
        evidence(request, before=before, after=after)
        assert after == before
    finally:
        await remove_commit_failure(db)
    assert await success(db, item) == "APPLIED"
    assert len((await snapshot(db))["message"]) == 2


async def test_document_persistence_error_fallback_cannot_settle_new_owner(
    db: Any,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    await seed(db, "DOCUMENT")
    old = await claim(db)
    failed = asyncio.Event()
    release = asyncio.Event()
    real_settle = worker.settle_outbox_success

    async def barrier_after_real_rollback(*args: Any, **kwargs: Any) -> Any:
        try:
            return await real_settle(*args, **kwargs)
        except DBAPIError:
            failed.set()
            await asyncio.wait_for(release.wait(), 20)
            raise

    monkeypatch.setattr(worker, "settle_outbox_success", barrier_after_real_rollback)
    await install_commit_failure(db)
    task = asyncio.create_task(process(db, old, Sender("r1.rollback")))
    try:
        await asyncio.wait_for(failed.wait(), 20)
        rolled_back = await snapshot(db)
        assert rolled_back["outbox"][0]["status"] == "SENDING"
        assert len(rolled_back["message"]) == 1
        await reap(db)
        new = await claim(db, T0 + timedelta(seconds=130))
        await process(db, new, Sender("r1.new"))
        before = await snapshot(db)
        release.set()
        assert await asyncio.wait_for(task, 20) == "DISCARDED"
        after = await snapshot(db)
        evidence(request, rolled_back=rolled_back, before=before, after=after)
        assert after == before
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await remove_commit_failure(db)


@pytest.mark.parametrize(
    "kind,permanent,attempts",
    [
        ("TEXT", False, 4),
        ("DOCUMENT", False, 4),
        ("DOCUMENT", True, 0),
    ],
)
async def test_current_terminal_failure(
    db: Any, request: pytest.FixtureRequest, kind: str, permanent: bool, attempts: int
) -> None:
    await seed(db, kind, attempts=attempts)
    item = await claim(db)
    error = (
        PermanentCatalogMediaError("synthetic permanent")
        if permanent
        else TimeoutError("synthetic retry")
    )
    assert await process(db, item, Sender(error)) == "APPLIED"
    rows = await snapshot(db)
    evidence(request, final=rows)
    assert rows["outbox"][0]["status"] == "FAILED"
    assert rows["outbox"][0]["attempts"] == attempts + 1
    assert rows["outbox"][0]["claim_token"] is None
    assert len(rows["message"]) == 1
    assert len(rows["audit_event"]) == 1
    assert rows["audit_event"][0]["action"] == "WHATSAPP_OUTBOX_SEND_FAILED"


@pytest.mark.parametrize("retry_fails", [False, True])
async def test_invalid_document_media_keeps_real_cache_and_retry_flow(
    db: Any,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    retry_fails: bool,
) -> None:
    await seed(db, "DOCUMENT")
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic R1")
    async with db() as session, session.begin():
        row = await session.get(Outbox, 1)
        asset = await session.get(CatalogAsset, row.catalog_asset_id)
        asset.file_path = str(pdf)
        asset.file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        asset.file_size = pdf.stat().st_size

    class InvalidMediaSender(Sender):
        uploads = 0

        async def upload_media(self, file_path: Path, mime_type: str) -> str:
            assert file_path.read_bytes() == pdf.read_bytes()
            assert mime_type == "application/pdf"
            self.uploads += 1
            return "synthetic-refreshed"

        async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
            self.calls += 1
            if self.calls == 1:
                assert media_id == "synthetic-cache"
                raise WhatsAppInvalidMediaError("synthetic invalid media")
            assert self.calls == 2 and media_id == "synthetic-refreshed"
            if retry_fails:
                raise TimeoutError("synthetic retry timeout")
            return "r1.refreshed"

    sender = InvalidMediaSender("unused")
    assert await process(db, await claim(db), sender) == "APPLIED"
    rows = await snapshot(db)
    evidence(request, final=rows, uploads=sender.uploads, sends=sender.calls)
    assert sender.uploads == 1 and sender.calls == 2
    assert rows["outbox"][0]["status"] == ("PENDING" if retry_fails else "SENT")
    assert rows["outbox"][0]["attempts"] == int(retry_fails)
    assert rows["outbox"][0]["claim_token"] is None
    assert len(rows["message"]) == (1 if retry_fails else 2)
    assert {a["action"] for a in rows["audit_event"]} == {
        "CATALOG_MEDIA_CACHE_INVALIDATED",
        "CATALOG_MEDIA_UPLOADED",
    }


@pytest.mark.parametrize("concurrent", [False, True])
async def test_duplicate_retry_failure_consumes_one_attempt(
    db: Any,
    request: pytest.FixtureRequest,
    concurrent: bool,
) -> None:
    await seed(db)
    item = await claim(db)
    if concurrent:
        outcomes = await asyncio.wait_for(asyncio.gather(failure(db, item), failure(db, item)), 20)
    else:
        outcomes = [await failure(db, item), await failure(db, item)]
    rows = await snapshot(db)
    evidence(request, final=rows, outcomes=outcomes)
    assert sorted(outcomes) == ["APPLIED", "DISCARDED"]
    assert rows["outbox"][0]["attempts"] == 1
    assert rows["outbox"][0]["status"] == "PENDING"
    assert rows["outbox"][0]["claim_token"] is None
    assert len(rows["message"]) == 1 and rows["audit_event"] == []


async def test_discard_observability_and_missing_row(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await seed(db)
    item = await claim(db)
    before = await snapshot(db)
    with capture_logs() as logs:
        assert (
            await worker.settle_outbox_success(
                db,
                item.id,
                "private body must not be logged",
                "r1.foreign",
                T0,
                5,
                300,
                claim_token=uuid4(),
            )
            == "DISCARDED"
        )
        assert (
            await worker.settle_outbox_failure(
                db,
                item.id + 1000,
                TimeoutError("private error must not be logged"),
                T0,
                5,
                300,
                claim_token=item.claim_token,
            )
            == "DISCARDED"
        )
    after = await snapshot(db)
    evidence(request, before=before, after=after, logs=logs)
    assert after == before
    assert [r["reason"] for r in logs] == ["identity_mismatch", "missing"]
    assert all(set(r) == {"event", "log_level", "outbox_id", "outcome", "reason"} for r in logs)
