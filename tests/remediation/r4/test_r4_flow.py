"""R4 human requests through real R2 claims, effects and administrative visibility."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.channel import inbound, inbox
from app.channel.models import InboxJob
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.handoff.models import Handoff
from app.orchestrator.inbox_effects import AgendaResults
from tests.remediation.r2.test_r2_inbox import claim, install_commit_failure, remove_commit_failure
from tests.remediation.r3.helpers import EXTRACT, MAIN, SERVICES, Provider, valid
from tests.remediation.r4.helpers import (
    POSITIVE,
    admin_cases,
    configure,
    message_payload,
    prepare,
    snapshot,
)
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


def dormant_provider(router: respx.MockRouter, outcome: Any = None) -> Provider:
    return Provider(
        router,
        {
            MAIN: [outcome if outcome is not None else httpx.ReadError("R4 synthetic unused")],
            EXTRACT: [httpx.ReadError("R4 synthetic unused extractor")],
            SERVICES: [httpx.ReadError("R4 synthetic unused services")],
        },
    )


def assert_handoff(before: dict[str, Any], final: dict[str, Any], code: str) -> None:
    assert final["message"] == before["message"]
    assert final["customer"] == before["customer"]
    for table in [
        "event",
        "lead",
        "event_service_request",
        "appointment",
        "quote_request",
        "payment_evidence",
    ]:
        assert final[table] == before[table]
    assert len(final["handoff"]) == len(final["outbox"]) == 1
    handoff = final["handoff"][0]
    assert handoff["reason"] == "CUSTOMER_REQUEST" and handoff["status"] == "PENDING"
    assert handoff["priority"] == "NORMAL"
    assert "Cliente Sintetico R4" in handoff["summary"] and POSITIVE in handoff["summary"]
    assert final["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
    assert final["conversation"][0]["last_question_code"] == code
    assert final["conversation"][0]["bot_enabled"] == before["conversation"][0]["bot_enabled"]
    assert final["conversation"][0]["pending_confirmation"] is None
    assert final["ai_execution"] == []
    assert sum(a["action"] == "HANDOFF_CREATED" for a in final["audit_event"]) == 1
    assert final["inbox_job"][0]["status"] == "COMPLETED"


def control_fields(snapshot_value: dict[str, Any]) -> dict[str, Any]:
    # Receipt activity may advance; human ownership and all decision context must persist.
    return {
        key: value
        for key, value in snapshot_value["conversation"][0].items()
        if key != "last_message_at"
    }


@pytest.mark.parametrize(
    "context", ["active", "event", "services", "catalog", "name", "quote", "visit"]
)
async def test_context_interrupts_to_visible_case_without_ai(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, context: str
) -> None:
    configure(monkeypatch)
    pending = {
        "event": "COLLECT_EVENT_TYPE",
        "services": "COLLECT_SERVICES",
        "catalog": "COLLECT_CATALOG_EVENT_TYPE",
    }.get(context)
    event_id = await prepare(
        db, pending=pending, state="COLLECTING_EVENT_DATA" if pending else "BOT_ACTIVE"
    )
    if context in {"name", "quote", "visit"}:
        async with db() as session, session.begin():
            conversation = await session.get(Conversation, 1)
            conversation.pending_confirmation = {
                "type": "FULL_NAME_CONFIRMATION" if context == "name" else "AI_CONFIRMATION",
                "full_name": "Propuesta antigua no confirmada",
                "classification": dict(
                    valid(),
                    primary_intent="QUOTE_REQUEST",
                    entities={"full_name": "Nombre antiguo"},
                ),
            }
            conversation.pending_action = {
                "name": "COLLECT_CUSTOMER_NAME",
                "quote": "CONFIRM_QUOTE_REQUEST",
                "visit": "CONFIRM_APPOINTMENT",
            }[context]
            if context == "visit":
                conversation.state = "APPOINTMENT_PENDING_CONFIRMATION"
                conversation.visit_draft = {"visit_date": "2027-02-20", "mode": "SCHEDULE"}
    before = await snapshot(db)
    current = await claim(db)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        decision = await inbound.classify_message(current.persisted, db, current.request_id)
        assert decision.decision_source == "DETERMINISTIC"
        assert decision.classification.primary_intent == "HUMAN_REQUEST"
        assert decision.classification.confidence == 0
        assert await inbox.apply_turn(db, current, decision, AgendaResults()) == "COMPLETED"
        await inbox.refresh_event(db, event_id)
    final = await snapshot(db)
    administrative = await admin_cases(db)
    evidence(
        request,
        before=before,
        final=final,
        calls=provider.calls,
        administrative=administrative,
        decision=decision.classification.model_dump(),
        decision_source=decision.decision_source,
        claim_token=str(current.claim_token),
    )
    assert provider.calls == {}
    assert_handoff(before, final, "RESP-HANDOFF-001")
    assert administrative["status_code"] == 200 and len(administrative["body"]) == 1
    assert administrative["body"][0]["id"] == final["handoff"][0]["id"]
    assert administrative["body"][0]["summary"] == final["handoff"][0]["summary"]


@pytest.mark.parametrize("outcome", ["connect", "timeout", "401", "invalid", "valid"])
async def test_provider_state_never_enters_recognized_turn(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    configure(monkeypatch)
    event_id = await prepare(db)
    before = await snapshot(db)
    response = {
        "connect": httpx.ConnectError("R4 synthetic"),
        "timeout": httpx.ReadTimeout("R4 synthetic"),
        "401": httpx.Response(401),
        "invalid": httpx.Response(200, text="invalid"),
        "valid": valid(),
    }[outcome]
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router, response)
        await inbound.process_webhook_event(event_id, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls, simulated_outcome=outcome)
    assert provider.calls == {}
    assert_handoff(before, final, "RESP-HANDOFF-001")


async def test_outside_hours_uses_existing_approved_template(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, outside=True)
    event_id = await prepare(db)
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        await inbound.process_webhook_event(event_id, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls, local_hour=18)
    assert provider.calls == {}
    assert_handoff(before, final, "RESP-HANDOFF-002")
    assert "horario de atención" in final["outbox"][0]["payload"]["text"]["body"]


async def test_redelivery_and_repeated_request_keep_one_open_case(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    first = await prepare(db)
    second = await inbound.store_webhook_event(message_payload("r4.synthetic"), db, None)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        await asyncio.wait_for(
            asyncio.gather(
                inbound.process_webhook_event(first, db), inbound.process_webhook_event(second, db)
            ),
            20,
        )
        await inbox.process_inbox_once(db)
        completed = await snapshot(db)
        await inbound.process_webhook_event(first, db)
        assert await snapshot(db) == completed
        again = await inbound.store_webhook_event(message_payload("r4.second.request"), db, None)
        await inbound.process_webhook_event(again, db)
        final = await snapshot(db)
    administrative = await admin_cases(db)
    evidence(
        request,
        completed=completed,
        final=final,
        calls=provider.calls,
        administrative=administrative,
    )
    assert provider.calls == {}
    assert final["handoff"] == completed["handoff"] and len(final["handoff"]) == 1
    assert final["outbox"] == completed["outbox"] and len(final["outbox"]) == 1
    assert len(completed["message"]) == 1 and len(final["message"]) == 2
    assert final["inbox_job"][-1]["completion_reason"] == "SILENT_WAITING_FOR_HUMAN"
    assert sum(a["action"] == "HANDOFF_CREATED" for a in final["audit_event"]) == 1
    assert len(administrative["body"]) == 1


@pytest.mark.parametrize("control", ["waiting", "human", "disabled"])
async def test_protected_control_is_silent_without_ai(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, control: str
) -> None:
    configure(monkeypatch)
    event_id = await prepare(
        db,
        state={"waiting": "WAITING_FOR_HUMAN", "human": "HUMAN_ACTIVE", "disabled": "BOT_ACTIVE"}[
            control
        ],
        enabled=control != "disabled",
    )
    await admin_cases(db)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.assigned_agent_id = 1
        conversation.pending_confirmation = {
            "type": "FULL_NAME_CONFIRMATION",
            "full_name": "Pending",
        }
        if control != "disabled":
            session.add(
                Handoff(
                    conversation_id=1,
                    reason="CUSTOMER_REQUEST",
                    status="TAKEN" if control == "human" else "PENDING",
                    priority="NORMAL",
                    summary="R4 prior case",
                    assigned_agent_id=1,
                    assigned_to="R4 Synthetic Reader",
                )
            )
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        await inbound.process_webhook_event(event_id, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert provider.calls == {} and final["ai_execution"] == []
    assert final["handoff"] == before["handoff"] and final["outbox"] == []
    assert control_fields(final) == control_fields(before)
    assert final["inbox_job"][0]["completion_reason"].startswith("SILENT_")


async def test_human_change_after_recognition_respects_fresh_state(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    await prepare(db)
    current = await claim(db)
    ready, release = asyncio.Event(), asyncio.Event()
    original = inbound.classify_message

    async def recognize_then_wait(*args: Any, **kwargs: Any) -> inbound.ClassifiedTurn:
        decision = await original(*args, **kwargs)
        assert decision.decision_source == "DETERMINISTIC"
        ready.set()
        await asyncio.wait_for(release.wait(), 20)
        return decision

    monkeypatch.setattr(inbound, "classify_message", recognize_then_wait)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        task = asyncio.create_task(inbox.process_claimed_inbox(db, current))
        try:
            await asyncio.wait_for(ready.wait(), 20)
            async with db() as session, session.begin():
                conversation = await session.get(Conversation, 1)
                conversation.state = "HUMAN_ACTIVE"
            before = await snapshot(db)
            release.set()
            assert await asyncio.wait_for(task, 20) == "COMPLETED"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert provider.calls == {} and final["handoff"] == final["outbox"] == []
    assert control_fields(final) == control_fields(before)
    assert final["inbox_job"][0]["completion_reason"] == "SILENT_HUMAN_ACTIVE"


@pytest.mark.parametrize("boundary", ["reaped", "new_processing", "new_completed"])
async def test_old_deterministic_result_cannot_apply(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    configure(monkeypatch)
    await prepare(db)
    now = datetime.now(UTC)
    old = await claim(db, now)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        decision = await inbound.classify_message(old.persisted, db, old.request_id)
        assert decision.decision_source == "DETERMINISTIC"
        assert (
            await inbox.recover_stale_inbox(db, now + timedelta(seconds=121), get_settings()) == 1
        )
        if boundary != "reaped":
            current = await claim(db, now + timedelta(seconds=130))
            assert current.claim_token != old.claim_token
            if boundary == "new_completed":
                assert await inbox.process_claimed_inbox(db, current) == "COMPLETED"
        before = await snapshot(db)
        result = await inbox.apply_turn(db, old, decision, AgendaResults())
    final = await snapshot(db)
    evidence(
        request,
        before=before,
        final=final,
        calls=provider.calls,
        result=result,
        old_token=str(old.claim_token),
    )
    assert result == "DISCARDED" and final == before and provider.calls == {}


async def test_commit_failure_rolls_back_all_handoff_effects_and_recovers(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    event_id = await prepare(db)
    current = await claim(db)
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        await install_commit_failure(db, current.id)
        try:
            assert await inbox.process_claimed_inbox(db, current) == "FAILED"
            failed = await snapshot(db)
            for table in ["message", "handoff", "outbox", "audit_event", "conversation"]:
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
    administrative = await admin_cases(db)
    evidence(
        request,
        before=before,
        failed=failed,
        final=final,
        calls=provider.calls,
        administrative=administrative,
    )
    assert_handoff(before, final, "RESP-HANDOFF-001")
    assert provider.calls == {} and final["inbox_job"][0]["attempts"] == 1
    assert len(administrative["body"]) == 1


@pytest.mark.parametrize("blocked", ["FAILED", "REVIEW", "EXTERNAL"])
async def test_request_does_not_skip_prior_blocked_job(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, blocked: str
) -> None:
    configure(monkeypatch)
    await prepare(db, body="consulta anterior", external_id="r4.prior")
    async with db() as session, session.begin():
        job = await session.get(InboxJob, 1)
        job.status = blocked
        if blocked == "EXTERNAL":
            from uuid import uuid4

            job.claim_token, job.claimed_at = uuid4(), datetime.now(UTC)
            job.external_operation = "R4_SYNTHETIC_UNCERTAIN"
    event_id = await inbound.store_webhook_event(message_payload("r4.blocked.request"), db, None)
    with respx.mock(assert_all_called=False) as router:
        provider = dormant_provider(router)
        await inbound.process_webhook_event(event_id, db)
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls, prior_status=blocked)
    assert provider.calls == {} and final["handoff"] == final["outbox"] == []
    assert [j["status"] for j in final["inbox_job"]] == [blocked, "PENDING"]


@pytest.mark.parametrize("kind", ["image", "interactive"])
async def test_non_text_caption_or_title_is_not_a_new_authorization(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    configure(monkeypatch)
    await prepare(db, body="ordinary", external_id="r4.seed")
    # Exercise actual parser/classifier type boundary without rewriting append-only Message.
    data = message_payload("r4.nontext")
    message = data["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = kind
    if kind == "image":
        message["image"] = {"id": "r4-synthetic-media", "caption": POSITIVE}
    else:
        message["interactive"] = {
            "type": "button_reply",
            "button_reply": {"id": "r4-unpublished-id", "title": POSITIVE},
        }
    event_id = await inbound.store_webhook_event(data, db, None)
    await inbox.expand_event(db, event_id, datetime.now(UTC))
    async with db() as session:
        from app.channel.models import Message

        model = await session.get(Message, 2)
        conversation = await session.get(Conversation, 1)
        persisted = inbound.persisted_message_from_models(model, conversation)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        decision = await inbound.classify_message(persisted, db, None)
    final = await snapshot(db)
    evidence(
        request,
        input_type=kind,
        final=final,
        calls=provider.calls,
        decision_source=decision.decision_source,
    )
    assert decision.decision_source == "LLM" and provider.calls == {MAIN: 1}
    assert final["handoff"] == final["outbox"] == []
