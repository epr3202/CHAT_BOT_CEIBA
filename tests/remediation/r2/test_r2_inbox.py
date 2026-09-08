"""Real-session H01 ownership, ordering, completion and failure controls."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import respx
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.calendar.adapter import FakeCalendarAdapter
from app.channel import inbound, inbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.orchestrator import service as orchestrator
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from scripts.reprocess_webhook_events import reprocess_events, retry_job
from tests.remediation.r2.test_r2_recovery import greeting_http, payload, rows
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


async def prepare(db: Any, *ids: str) -> int:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    event_id = await inbound.store_webhook_event(payload(*(ids or ("r2.one",))), db, None)
    await inbox.expand_event(db, event_id, datetime.now(UTC))
    return event_id


async def snapshot(db: Any) -> dict[str, Any]:
    result = await rows(db)
    async with db() as session:
        for name in (
            "inbox_job",
            "conversation",
            "customer",
            "lead",
            "event",
            "handoff",
            "payment_evidence",
        ):
            order = name + "_id" if name in {"lead", "event"} else "id"
            result[name] = [
                dict(r)
                for r in (
                    await session.execute(text(f'SELECT * FROM "{name}" ORDER BY {order}'))
                ).mappings()
            ]
    return result


async def claim(db: Any, now: datetime | None = None) -> inbox.InboxClaim:
    result = await inbox.claim_inbox_batch(db, now or datetime.now(UTC), 10)
    assert len(result) == 1
    return result[0]


async def test_event_received_without_background_is_consumed(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    await inbound.store_webhook_event(payload("r2.received"), db, None)
    before = await snapshot(db)
    assert before["message"] == []
    with respx.mock as router:
        greeting_http(router)
        counts = await inbox.process_inbox_once(db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, counts=counts)
    assert counts["COMPLETED"] == 1
    assert len(final["outbox"]) == 1
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["webhook_event"][0]["status"] == "PROCESSED"


@pytest.mark.parametrize(
    "state,enabled", [("HUMAN_ACTIVE", True), ("WAITING_FOR_HUMAN", True), ("BOT_ACTIVE", False)]
)
async def test_silent_turn_has_explicit_completion(
    db: Any, request: pytest.FixtureRequest, state: str, enabled: bool
) -> None:
    event_id = await prepare(db)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state, conversation.bot_enabled = state, enabled
    with respx.mock(assert_all_called=False) as router:
        greeting_http(router)
        await inbound.process_webhook_event(event_id, db)
        before = await snapshot(db)
        await inbound.process_webhook_event(event_id, db)
        after = await snapshot(db)
    evidence(request, before=before, after=after)
    assert after == before and after["outbox"] == []
    job = after["inbox_job"][0]
    assert job["status"] == "COMPLETED" and job["completion_reason"].startswith("SILENT_")
    assert job["claim_token"] is None


async def test_effects_committed_before_event_finalization_do_not_repeat(
    db: Any, request: pytest.FixtureRequest
) -> None:
    event_id = await prepare(db)
    with respx.mock as router:
        route = greeting_http(router)
        assert await inbox.process_claimed_inbox(db, await claim(db)) == "COMPLETED"
        before = await snapshot(db)
        assert before["webhook_event"][0]["status"] == "PREPARED"
        await inbound.process_webhook_event(event_id, db)
        after = await snapshot(db)
        assert route.call_count == 1
    evidence(request, before=before, after=after)
    for table in before.keys() - {"webhook_event"}:
        assert after[table] == before[table]
    assert after["webhook_event"][0]["status"] == "PROCESSED"


@pytest.mark.parametrize("same_event", [False, True])
@pytest.mark.parametrize("concurrent", [False, True])
async def test_duplicate_events_share_one_completed_job(
    db: Any, request: pytest.FixtureRequest, same_event: bool, concurrent: bool
) -> None:
    first = await prepare(db)
    second = first if same_event else await inbound.store_webhook_event(payload("r2.one"), db, None)
    with respx.mock(assert_all_called=False) as router:
        greeting_http(router)
        if concurrent:
            await asyncio.wait_for(
                asyncio.gather(
                    inbound.process_webhook_event(first, db),
                    inbound.process_webhook_event(second, db),
                ),
                20,
            )
        else:
            await inbound.process_webhook_event(first, db)
            await inbound.process_webhook_event(second, db)
        await inbox.process_inbox_once(db, now=datetime.now(UTC) + timedelta(seconds=2))
    final = await snapshot(db)
    evidence(request, final=final)
    assert len(final["message"]) == len(final["outbox"]) == len(final["inbox_job"]) == 1
    assert all(e["status"] == "PROCESSED" for e in final["webhook_event"])


@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("boundary", ["reaped", "new_processing", "new_completed"])
async def test_old_acquisition_cannot_apply_result(
    db: Any, request: pytest.FixtureRequest, late_failure: bool, boundary: str
) -> None:
    await prepare(db)
    now = datetime.now(UTC)
    old = await claim(db, now)
    with pytest.raises(FrozenInstanceError):
        old.claim_token = uuid4()
    started, release = asyncio.Event(), asyncio.Event()
    with respx.mock(assert_all_called=False) as router:
        route = greeting_http(router)
        # Provider barrier, while the real classification and telemetry paths execute.
        response = route.side_effect

        async def blocked(request: Any) -> Any:
            started.set()
            await asyncio.wait_for(release.wait(), 20)
            return response(request)

        route.mock(side_effect=blocked)
        task = asyncio.create_task(inbox.process_claimed_inbox(db, old))
        try:
            await asyncio.wait_for(started.wait(), 20)
            assert (
                await inbox.recover_stale_inbox(db, now + timedelta(seconds=121), get_settings())
                == 1
            )
            if boundary != "reaped":
                current = await claim(db, now + timedelta(seconds=130))
                assert current.claim_token != old.claim_token
                if boundary == "new_completed":
                    route.mock(side_effect=response)
                    assert await inbox.process_claimed_inbox(db, current) == "COMPLETED"
            before = await snapshot(db)
            if late_failure:
                assert (
                    await inbox.settle_inbox_failure(db, old, RuntimeError("synthetic old failure"))
                    == "DISCARDED"
                )
            release.set()
            assert await asyncio.wait_for(task, 20) == "DISCARDED"
            after = await snapshot(db)
            evidence(request, before=before, after=after)
            assert after == before
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_competing_claims_and_context_order(db: Any, request: pytest.FixtureRequest) -> None:
    await prepare(db, "r2.first", "r2.second")
    start = asyncio.Event()

    async def contender() -> Any:
        await start.wait()
        return await inbox.claim_inbox_batch(db, datetime.now(UTC), 10)

    tasks = [asyncio.create_task(contender()) for _ in range(2)]
    start.set()
    claims = await asyncio.wait_for(asyncio.gather(*tasks), 20)
    assert sorted(map(len, claims)) == [0, 1]
    owner = next(items[0] for items in claims if items)
    assert owner.message_id == 1
    assert await inbox.claim_inbox_batch(db, datetime.now(UTC), 10) == []
    with respx.mock as router:
        greeting_http(router)
        assert await inbox.process_claimed_inbox(db, owner) == "COMPLETED"
        second = await claim(db)
        assert second.message_id == 2
        assert second.persisted.context["last_question_code"] == "RESP-GREETING-001"
        assert await inbox.process_claimed_inbox(db, second) == "COMPLETED"
    final = await snapshot(db)
    evidence(request, final=final)
    assert len(final["outbox"]) == 2


async def test_same_clock_reacquisition_and_duplicate_callback(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    await prepare(db)
    monkeypatch.setenv("INBOX_MAX_BACKOFF_SECONDS", "0")
    get_settings.cache_clear()
    now = datetime.now(UTC)
    old = await claim(db, now)
    await inbox.settle_inbox_failure(db, old, RuntimeError("synthetic"), now)
    current = await claim(db, now)
    assert current.claim_token != old.claim_token
    with respx.mock as router:
        greeting_http(router)
        turn = await inbound.classify_message(current.persisted, db, None)
    before = await snapshot(db)
    results = await asyncio.wait_for(
        asyncio.gather(
            inbox.apply_turn(db, current, turn, inbox.AgendaResults()),
            inbox.apply_turn(db, current, turn, inbox.AgendaResults()),
        ),
        20,
    )
    assert sorted(results) == ["COMPLETED", "DISCARDED"]
    final = await snapshot(db)
    assert await inbox.apply_turn(db, old, turn, inbox.AgendaResults()) == "DISCARDED"
    assert await snapshot(db) == final
    evidence(request, before=before, final=final, results=results)
    assert len(final["outbox"]) == 1


async def test_expansion_failure_has_bounded_durable_retry(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INBOX_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    event_id = await inbound.store_webhook_event(payload("r2.reject"), db, None)
    async with db() as session, session.begin():
        await session.execute(
            text(
                "ALTER TABLE message ADD CONSTRAINT r2_reject_input "
                "CHECK (external_message_id <> 'r2.reject')"
            )
        )
    try:
        now = datetime.now(UTC)
        await inbox.expand_event(db, event_id, now)
        before = await snapshot(db)
        assert before["webhook_event"][0]["ingest_attempts"] == 1
        await inbox.expand_event(db, event_id, now + timedelta(seconds=1))
        assert await snapshot(db) == before
        await inbox.expand_event(db, event_id, now + timedelta(seconds=2))
        final = await snapshot(db)
        assert final["webhook_event"][0]["status"] == "EXHAUSTED"
        assert final["webhook_event"][0]["ingest_attempts"] == 2
        await inbox.process_inbox_once(db, now=now + timedelta(days=1))
        assert await snapshot(db) == final
        evidence(request, before=before, final=final)
        assert final["message"] == final["inbox_job"] == final["outbox"] == []
    finally:
        async with db() as session, session.begin():
            await session.execute(text("ALTER TABLE message DROP CONSTRAINT r2_reject_input"))


async def test_context_change_reclassifies_and_human_change_is_reloaded(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await prepare(db)
    old = await claim(db)
    with respx.mock as router:
        greeting_http(router)
        turn = await inbound.classify_message(old.persisted, db, None)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_action = "COLLECT_EVENT_TYPE"
    assert await inbox.apply_turn(db, old, turn, inbox.AgendaResults()) == "RETRY"
    intermediate = await snapshot(db)
    assert intermediate["outbox"] == []
    current = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
    assert current.persisted.context["pending_action"] == "COLLECT_EVENT_TYPE"
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state = "HUMAN_ACTIVE"
    assert await inbox.apply_turn(db, current, turn, inbox.AgendaResults()) == "COMPLETED"
    final = await snapshot(db)
    evidence(request, intermediate=intermediate, final=final)
    assert (
        final["outbox"] == []
        and final["inbox_job"][0]["completion_reason"] == "SILENT_HUMAN_ACTIVE"
    )


async def install_commit_failure(db: Any, job_id: int) -> None:
    async with db() as session, session.begin():
        await session.execute(
            text(
                "CREATE FUNCTION r2_reject_completion() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'R2 deferred SQL failure'; END $$"
            )
        )
        await session.execute(
            text(
                "CREATE CONSTRAINT TRIGGER r2_completion_failure AFTER UPDATE ON inbox_job "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                f"WHEN (NEW.id = {job_id} AND NEW.status = 'COMPLETED') "
                "EXECUTE FUNCTION r2_reject_completion()"
            )
        )


async def remove_commit_failure(db: Any) -> None:
    async with db() as session, session.begin():
        await session.execute(text("DROP TRIGGER r2_completion_failure ON inbox_job"))
        await session.execute(text("DROP FUNCTION r2_reject_completion()"))


async def test_real_commit_rollback_and_partial_event_recovery(
    db: Any, request: pytest.FixtureRequest
) -> None:
    event_id = await prepare(db, "r2.first", "r2.second")
    with respx.mock as router:
        greeting_http(router)
        assert await inbox.process_claimed_inbox(db, await claim(db)) == "COMPLETED"
        current = await claim(db)
        before = await snapshot(db)
        await install_commit_failure(db, current.id)
        try:
            assert await inbox.process_claimed_inbox(db, current) == "FAILED"
            failed = await snapshot(db)
            for table in ("message", "outbox", "audit_event", "conversation"):
                assert failed[table] == before[table]
            assert failed["inbox_job"][1]["status"] == "PENDING"
            assert failed["inbox_job"][1]["completed_at"] is None
        finally:
            await remove_commit_failure(db)
        resumed = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
        assert resumed.message_id == current.message_id
        assert await inbox.process_claimed_inbox(db, resumed) == "COMPLETED"
        await inbox.refresh_event(db, event_id)
    final = await snapshot(db)
    evidence(request, before=before, failed=failed, final=final)
    assert len(final["outbox"]) == 2
    assert all(e["status"] == "PROCESSED" for e in final["webhook_event"])
    assert final["inbox_job"][0] == before["inbox_job"][0]


async def test_exhaustion_backoff_manual_retry_and_other_conversation(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = await prepare(db)
    monkeypatch.setenv("INBOX_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    first = await claim(db)
    now = datetime.now(UTC)
    await inbox.settle_inbox_failure(db, first, RuntimeError("synthetic"), now)
    assert await inbox.claim_inbox_batch(db, now + timedelta(seconds=1), 10) == []
    second = await claim(db, now + timedelta(seconds=2))
    await inbox.settle_inbox_failure(
        db, second, RuntimeError("synthetic"), now + timedelta(seconds=2)
    )
    assert await inbox.claim_inbox_batch(db, now + timedelta(days=1), 10) == []
    await inbox.refresh_event(db, event_id)
    other = payload("r2.other")
    other["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "573009999999"
    other_id = await inbound.store_webhook_event(other, db, None)
    with respx.mock as router:
        greeting_http(router)
        assert (await inbound.process_webhook_event(other_id, db))["COMPLETED"] == 1
        exhausted = await snapshot(db)
        assert exhausted["inbox_job"][0]["status"] == "FAILED"
        assert await retry_job(db, first.id, "synthetic fault removed")
        counts = await reprocess_events(db, [other_id])
        assert counts == {"SKIPPED_MISSING_OR_COMPLETED": 1}
        assert (await inbox.process_inbox_once(db))["COMPLETED"] == 1
    final = await snapshot(db)
    evidence(request, exhausted=exhausted, final=final, counters=counts)
    assert len(final["outbox"]) == 2
    assert all(e["status"] == "PROCESSED" for e in final["webhook_event"])


async def test_unrelated_integrity_error_is_not_duplicate(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    async with db() as session, session.begin():
        await session.execute(
            text(
                "ALTER TABLE message ADD CONSTRAINT r2_reject_input "
                "CHECK (external_message_id <> 'r2.rejected')"
            )
        )
    try:
        with pytest.raises(IntegrityError):
            await inbound.persist_payload_phase_a(payload("r2.rejected"), db, None)
        final = await snapshot(db)
        evidence(request, final=final)
        assert final["message"] == final["inbox_job"] == []
        assert final["customer"] == final["conversation"] == []
    finally:
        async with db() as session, session.begin():
            await session.execute(text("ALTER TABLE message DROP CONSTRAINT r2_reject_input"))


async def test_two_first_messages_same_customer_no_creation_loss(
    db: Any, request: pytest.FixtureRequest
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    events = [
        await inbound.store_webhook_event(payload(name), db, None) for name in ("r2.a", "r2.b")
    ]
    await asyncio.wait_for(
        asyncio.gather(
            *(inbox.expand_event(db, event_id, datetime.now(UTC)) for event_id in events)
        ),
        20,
    )
    before = await snapshot(db)
    assert len(before["customer"]) == len(before["conversation"]) == 1
    assert len(before["message"]) == len(before["inbox_job"]) == 2
    with respx.mock as router:
        greeting_http(router)
        await inbox.process_inbox_once(db)
        await inbox.process_inbox_once(db, now=datetime.now(UTC) + timedelta(seconds=2))
    final = await snapshot(db)
    evidence(request, before=before, final=final)
    assert len(final["outbox"]) == 2


@pytest.mark.parametrize("kind", ["ignored", "status"])
async def test_non_message_events_complete_without_spurious_jobs(
    db: Any, request: pytest.FixtureRequest, kind: str
) -> None:
    data = (
        {"object": "unrelated"}
        if kind == "ignored"
        else {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "statuses": [{"id": "no-local-message", "status": "delivered"}]
                            },
                        }
                    ]
                }
            ],
        }
    )
    await inbound.store_webhook_event(data, db, None)
    with respx.mock(assert_all_called=False):
        await inbox.process_inbox_once(db)
    final = await snapshot(db)
    evidence(request, final=final)
    assert final["inbox_job"] == final["message"] == final["outbox"] == []
    assert final["webhook_event"][0]["status"] == "PROCESSED"


@pytest.mark.parametrize("uncertain", [False, True])
async def test_agenda_runs_outside_locks_and_uncertainty_is_not_retried(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    uncertain: bool,
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    data = payload("r2.visit")
    data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "si"
    event_id = await inbound.store_webhook_event(data, db, None)
    await inbox.expand_event(db, event_id, datetime.now(UTC))
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        customer = await session.get(Customer, 1)
        customer.full_name = "Synthetic Customer"
        lead = Lead(customer_id=customer.id, channel="WHATSAPP")
        session.add(lead)
        await session.flush()
        session.add(Event(lead_id=lead.lead_id))
        conversation.active_lead_id = lead.lead_id
        conversation.state = "APPOINTMENT_PENDING_CONFIRMATION"
        conversation.pending_action = "CONFIRM_APPOINTMENT"
        conversation.last_question_code = "RESP-VISIT-CONFIRM-001"
        conversation.visit_draft = {
            "mode": "SCHEDULE",
            "visit_date": "2026-09-12",
            "visit_time": "08:00:00",
            "attendee_count": 2,
            "visit_reason": "synthetic",
            "resume": {},
        }

    class Calendar(FakeCalendarAdapter):
        async def create_event(self, *args: Any, **kwargs: Any) -> Any:
            # Independent transactions can take every claim lock while provider I/O runs.
            async with db() as session, session.begin():
                for table in ("customer", "conversation", "inbox_job"):
                    await session.execute(text(f'SELECT id FROM "{table}" FOR UPDATE NOWAIT'))
            result = await super().create_event(*args, **kwargs)
            if uncertain:
                raise RuntimeError("synthetic transport lost after provider acceptance")
            return result

    calendar = Calendar()
    monkeypatch.setattr(orchestrator, "get_calendar_adapter", lambda settings: calendar)
    monkeypatch.setattr(
        orchestrator, "current_bogota_datetime", lambda: datetime(2026, 9, 8, 8, tzinfo=UTC)
    )
    with respx.mock(assert_all_called=False):
        await inbound.process_webhook_event(event_id, db)
        before = await snapshot(db)
        await inbox.process_inbox_once(db, now=datetime.now(UTC) + timedelta(days=1))
        await inbound.process_webhook_event(event_id, db)
        after = await snapshot(db)
    async with db() as session:
        appointments = [
            dict(r) for r in (await session.execute(text("SELECT * FROM appointment"))).mappings()
        ]
    evidence(
        request,
        before=before,
        after=after,
        appointments=appointments,
        external_ids=calendar.created_event_ids,
        external_calls=calendar.create_call_count,
    )
    assert before == after
    assert len(appointments) == calendar.create_call_count == 1
    assert after["inbox_job"][0]["external_operation"] == "confirm_appointment"
    if uncertain:
        assert after["inbox_job"][0]["status"] == "REVIEW"
        assert after["inbox_job"][0]["last_error"] == "EXTERNAL_OUTCOME_UNCERTAIN"
        assert after["outbox"] == []
        with pytest.raises(ValueError, match="REVIEW"):
            await retry_job(db, 1, "cannot blindly retry")
    else:
        assert after["inbox_job"][0]["status"] == "COMPLETED"
        assert appointments[0]["appointment_status"] == "CONFIRMED"
        assert len(after["outbox"]) >= 2  # Confirmation plus the next legitimate capture question.
