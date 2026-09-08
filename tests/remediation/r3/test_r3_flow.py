"""H04 decisions on real R2 claims, transactions and re-deliveries."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select, text

from app.channel import inbound, inbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.remediation.r2.test_r2_inbox import claim, install_commit_failure, remove_commit_failure
from tests.remediation.r2.test_r2_recovery import payload
from tests.remediation.r3.helpers import EXTRACT, MAIN, SERVICES, Provider, prepare, snapshot, valid
from tests.remediation.r3.test_r3_client import configure
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("case", ["active", "capture", "critical", "human", "waiting", "disabled"])
async def test_state_appropriate_degradation_and_next_turn(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    configure(monkeypatch, 1)
    state = {
        "active": "BOT_ACTIVE",
        "capture": "COLLECTING_EVENT_DATA",
        "critical": "WAITING_FOR_APPOINTMENT_DATE",
        "human": "HUMAN_ACTIVE",
        "waiting": "WAITING_FOR_HUMAN",
        "disabled": "BOT_ACTIVE",
    }[case]
    event_id = await prepare(
        db,
        state=state,
        enabled=case != "disabled",
        pending="COLLECT_EVENT_TYPE" if case == "capture" else None,
    )
    before = await snapshot(db)
    tokens: list[str] = []
    with respx.mock as router:
        provider = Provider(router, {MAIN: [httpx.ConnectError("R3 synthetic") for _ in range(2)]})

        async def observe(request: httpx.Request) -> httpx.Response:
            async with db() as session:
                token = await session.scalar(text("SELECT claim_token FROM inbox_job WHERE id=1"))
            assert token is not None
            tokens.append(str(token))
            return provider.respond(request)

        provider.route.mock(side_effect=observe)
        counts = await inbox.process_inbox_once(db)
        provider.exhausted()
        completed = await snapshot(db)
        await inbound.process_webhook_event(event_id, db)
        assert await snapshot(db) == completed
    assert len(set(tokens)) == 1 and provider.calls == {MAIN: 2}
    assert counts["COMPLETED"] == 1
    job = completed["inbox_job"][0]
    assert job["status"] == "COMPLETED" and job["attempts"] == 0
    assert completed["webhook_event"][0]["status"] == "PROCESSED"
    assert completed["message"] == before["message"]
    assert (
        completed["appointment"]
        == completed["payment_evidence"]
        == completed["quote_request"]
        == []
    )
    if case in {"human", "waiting", "disabled"}:
        assert completed["outbox"] == completed["handoff"] == []
        assert job["completion_reason"].startswith("SILENT_")
    elif case == "critical":
        assert len(completed["handoff"]) == len(completed["outbox"]) == 1
        assert completed["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
        assert (
            completed["conversation"][0]["bot_enabled"] == before["conversation"][0]["bot_enabled"]
        )
    else:
        assert completed["conversation"][0]["last_question_code"] == "RESP-DISCOVERY-002"
        assert len(completed["outbox"]) == 1 and completed["handoff"] == []
    next_final = None
    if case == "critical":
        # Existing handoff pauses through WAITING_FOR_HUMAN, without changing bot_enabled.
        # Verify effective silence on the next real turn instead of inventing a flag policy.
        next_event = await inbound.store_webhook_event(payload("r3.critical.next"), db, None)
        with respx.mock as router:
            next_provider = Provider(
                router, {MAIN: [httpx.ReadError("R3 synthetic") for _ in range(2)]}
            )
            assert (await inbound.process_webhook_event(next_event, db))["COMPLETED"] == 1
            next_provider.exhausted()
        next_final = await snapshot(db)
        assert next_final["outbox"] == completed["outbox"]
        assert next_final["handoff"] == completed["handoff"]
        assert next_final["inbox_job"][-1]["completion_reason"] == "SILENT_WAITING_FOR_HUMAN"
    if case in {"active", "capture"}:
        data = payload("r3.next")
        next_event = await inbound.store_webhook_event(data, db, None)
        outcomes = {MAIN: [valid()]}
        if case == "capture":
            outcomes[EXTRACT] = [{"event_type": "BIRTHDAY"}]
        with respx.mock as router:
            next_provider = Provider(router, outcomes)
            assert (await inbound.process_webhook_event(next_event, db))["COMPLETED"] == 1
            next_provider.exhausted()
        next_final = await snapshot(db)
        assert len(next_final["message"]) == len(next_final["inbox_job"]) == 2
        assert all(
            j["status"] == "COMPLETED" and j["attempts"] == 0 for j in next_final["inbox_job"]
        )
    evidence(
        request,
        before=before,
        completed=completed,
        next_final=next_final,
        calls=provider.calls,
        acquisition_tokens=tokens,
        next_calls=dict(next_provider.calls) if next_final is not None else {},
        counts=counts,
    )


@pytest.mark.parametrize("task", ["EVENT_TYPE_EXTRACTION", "SERVICES_CLASSIFICATION"])
@pytest.mark.parametrize("outcome", ["valid", "unavailable"])
async def test_auxiliary_result_preserves_its_consumer_contract(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
    outcome: str,
) -> None:
    configure(monkeypatch, 1)
    event_id = await prepare(
        db,
        state="COLLECTING_EVENT_DATA",
        pending="COLLECT_SERVICES" if task == SERVICES else "COLLECT_EVENT_TYPE",
    )
    if task == SERVICES:
        # Reach service capture after the other required fields, as in the real flow.
        async with db() as session, session.begin():
            conversation = await session.get(Conversation, 1)
            customer = await session.get(Customer, conversation.customer_id)
            customer.full_name = "R3 Synthetic Customer"
            lead = await session.get(Lead, conversation.active_lead_id)
            lead.lead_status, lead.budget_data_status = "QUALIFYING", "PROVIDED"
            event = await session.scalar(select(Event).where(Event.lead_id == lead.lead_id))
            event.event_date, event.event_date_type = date(2027, 2, 20), "EXACT"
            event.guest_count, event.guest_count_status = 40, "PROVIDED"
            conversation.pending_fields = ["requested_services"]
    current = await claim(db)
    response = {"service_codes": ["VENUE"]} if task == SERVICES else {"event_type": "BIRTHDAY"}
    outcomes = (
        [response] if outcome == "valid" else [httpx.ReadError("R3 synthetic") for _ in range(2)]
    )
    with respx.mock as router:
        provider = Provider(router, {MAIN: [valid()], task: outcomes})
        turn = await inbound.classify_message(current.persisted, db, None)
        provider.exhausted()
        if task == EXTRACT:
            assert turn.classification.primary_intent == "GREETING"
            assert turn.ai_error_reason is None
            assert turn.directed_event_type == ("BIRTHDAY" if outcome == "valid" else None)
        else:
            assert turn.services_resolution_failed == (outcome == "unavailable")
        assert await inbox.apply_turn(db, current, turn, inbox.AgendaResults()) == "COMPLETED"
        assert await inbox.refresh_event(db, event_id) == "PROCESSED"
    final = await snapshot(db)
    evidence(
        request,
        final=final,
        calls=provider.calls,
        primary_intent=turn.classification.primary_intent,
        services_resolution_failed=turn.services_resolution_failed,
        directed_event_type=turn.directed_event_type,
    )
    assert provider.calls == {MAIN: 1, task: 1 if outcome == "valid" else 2}
    assert final["inbox_job"][0]["attempts"] == 0
    if task == SERVICES and outcome == "unavailable":
        assert final["conversation"][0]["last_question_code"] == "RESP-SERVICES-RETRY-001"
        assert final["event_service_request"] == []
    if task == SERVICES and outcome == "valid":
        assert final["event_service_request"]


async def test_human_control_is_reloaded_after_pending_transport(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 0)
    await prepare(db)
    current = await claim(db)
    started, release = asyncio.Event(), asyncio.Event()
    with respx.mock as router:
        provider = Provider(router, {MAIN: [httpx.ReadError("R3 synthetic")]})

        async def blocked(request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.wait_for(release.wait(), 20)
            return provider.respond(request)

        provider.route.mock(side_effect=blocked)
        task = asyncio.create_task(inbox.process_claimed_inbox(db, current))
        try:
            await asyncio.wait_for(started.wait(), 20)
            async with db() as session, session.begin():
                conversation = await session.get(Conversation, 1, with_for_update=True)
                conversation.state, conversation.bot_enabled = "HUMAN_ACTIVE", False
            before = await snapshot(db)
            release.set()
            assert await asyncio.wait_for(task, 20) == "COMPLETED"
            provider.exhausted()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert final["outbox"] == final["handoff"] == []
    assert final["inbox_job"][0]["completion_reason"] == "SILENT_HUMAN_ACTIVE"


@pytest.mark.parametrize("state", ["BOT_ACTIVE", "WAITING_FOR_APPOINTMENT_DATE"])
@pytest.mark.parametrize("boundary", ["reaped", "new_processing", "new_completed"])
async def test_late_unavailable_does_not_apply_stale_effects(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    boundary: str,
) -> None:
    configure(monkeypatch, 0)
    await prepare(db, state=state)
    now = datetime.now(UTC)
    old = await claim(db, now)
    started, release = asyncio.Event(), asyncio.Event()
    errors = [httpx.ReadError("R3 synthetic late")]
    if boundary == "new_completed":
        errors.append(httpx.ConnectError("R3 synthetic current"))
    with respx.mock as router:
        provider = Provider(router, {MAIN: errors})

        async def blocked(request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.wait_for(release.wait(), 20)
            return provider.respond(request)

        provider.route.mock(side_effect=blocked)
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
                    provider.route.mock(side_effect=provider.respond)
                    assert await inbox.process_claimed_inbox(db, current) == "COMPLETED"
            before = await snapshot(db)
            release.set()
            assert await asyncio.wait_for(task, 20) == "DISCARDED"
            provider.exhausted()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    final = await snapshot(db)
    evidence(
        request, before=before, final=final, calls=provider.calls, old_token=str(old.claim_token)
    )
    assert {k: v for k, v in final.items() if k != "ai_execution"} == {
        k: v for k, v in before.items() if k != "ai_execution"
    }


async def test_fallback_commit_failure_rolls_back_then_recovers(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 0)
    event_id = await prepare(db)
    current = await claim(db)
    before = await snapshot(db)
    with respx.mock as router:
        provider = Provider(router, {MAIN: [httpx.ReadError("R3 synthetic") for _ in range(2)]})
        await install_commit_failure(db, current.id)
        try:
            assert await inbox.process_claimed_inbox(db, current) == "FAILED"
            failed = await snapshot(db)
            for table in ("message", "outbox", "audit_event", "conversation", "handoff"):
                assert failed[table] == before[table]
            assert failed["inbox_job"][0]["status"] == "PENDING"
            assert failed["inbox_job"][0]["completed_at"] is None
        finally:
            await remove_commit_failure(db)
        resumed = await claim(db, datetime.now(UTC) + timedelta(seconds=5))
        assert resumed.claim_token != current.claim_token
        assert await inbox.process_claimed_inbox(db, resumed) == "COMPLETED"
        await inbox.refresh_event(db, event_id)
        final = await snapshot(db)
        await inbound.process_webhook_event(event_id, db)
        assert await snapshot(db) == final
        provider.exhausted()
    evidence(request, before=before, failed=failed, final=final, calls=provider.calls)
    assert len(final["outbox"]) == 1 and final["inbox_job"][0]["attempts"] == 1


async def test_task_cancellation_reaches_r2_and_does_not_complete(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 0)
    await prepare(db)
    current = await claim(db)
    started = asyncio.Event()
    with respx.mock as router:
        provider = Provider(router, {MAIN: [valid(), valid()]})

        async def pending(request: httpx.Request) -> httpx.Response:
            response = provider.respond(request)
            started.set()
            await asyncio.Event().wait()
            return response

        provider.route.mock(side_effect=pending)
        task = asyncio.create_task(inbox.process_claimed_inbox(db, current))
        try:
            await asyncio.wait_for(started.wait(), 20)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 20)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        cancelled = await snapshot(db)
        assert cancelled["outbox"] == []
        assert cancelled["inbox_job"][0]["status"] == "PENDING"
        assert cancelled["inbox_job"][0]["completed_at"] is None
        provider.route.mock(side_effect=provider.respond)
        resumed = await claim(db)
        assert resumed.claim_token != current.claim_token
        assert await inbox.process_claimed_inbox(db, resumed) == "COMPLETED"
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, cancelled=cancelled, final=final, calls=provider.calls)
    assert len(final["outbox"]) == 1


async def test_two_conversations_progress_with_one_provider_failure(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 0)
    first = await prepare(db)
    data = payload("r3.other")
    data["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "573009999999"
    second = await inbound.store_webhook_event(data, db, None)
    start = asyncio.Event()

    async def process(event_id: int) -> Any:
        await start.wait()
        return await inbound.process_webhook_event(event_id, db)

    with respx.mock as router:
        provider = Provider(router, {MAIN: [httpx.ReadError("R3 synthetic"), valid()]})
        tasks = [asyncio.create_task(process(event_id)) for event_id in (first, second)]
        start.set()
        counts = await asyncio.wait_for(asyncio.gather(*tasks), 20)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls, counts=counts)
    assert len(final["outbox"]) == len(final["message"]) == 2
    assert all(j["status"] == "COMPLETED" and j["attempts"] == 0 for j in final["inbox_job"])
    assert sorted(e["success"] for e in final["ai_execution"]) == [False, True]
