"""Pending PostgreSQL reproductions. Real transactions/locks; simulated providers only.

Not executed in Phase II: container runner records each assertion and persisted outcome.
This package does not implement every scenario in scenario_matrix_phase2.csv.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import itertools
import uuid
import traceback


async def seed(sessionmaker, *, state="BOT_ACTIVE", media="text", caption=False, payment=False):
    from app.channel.models import Message
    from app.conversation.models import Conversation
    from app.customer.models import Customer
    from app.handoff.models import Handoff
    async with sessionmaker() as session, session.begin():
        customer = Customer(phone_number="+15550100001", full_name="Audit Synthetic")
        session.add(customer)
        await session.flush()
        conversation = Conversation(customer_id=customer.id, channel="WHATSAPP", state=state)
        session.add(conversation)
        await session.flush()
        content = {"text": {"body": "mensaje sintetico"}} if media == "text" else {
            media: {"id": "synthetic-media", "mime_type": "image/jpeg" if media == "image" else "application/pdf"}}
        if caption and media != "text":
            content[media]["caption"] = "comprobante sintetico"
        message = Message(external_message_id="wamid.audit." + uuid.uuid4().hex,
            conversation_id=conversation.id, customer_id=customer.id, channel="WHATSAPP",
            direction="INBOUND", message_type=media, content=content)
        session.add(message)
        if payment:
            session.add(Handoff(conversation_id=conversation.id, reason="PAYMENT_REVIEW", priority="NORMAL",
                status="TAKEN" if state == "HUMAN_ACTIVE" else "PENDING", summary="Synthetic audit case"))
        await session.flush()
        return customer, conversation, message


async def counts(sessionmaker):
    from sqlalchemy import func, select
    from app.channel.models import Message, Outbox
    from app.handoff.models import Handoff
    from app.payment.models import PaymentEvidence
    async with sessionmaker() as session:
        return {m.__tablename__: await session.scalar(select(func.count()).select_from(m))
                for m in (Message, Outbox, Handoff, PaymentEvidence)}


async def inbox_after_message_commit(sessionmaker):
    from app.channel.inbound import persist_payload_phase_a, process_webhook_event, store_webhook_event
    from app.channel.models import WebhookEvent
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "15550100001",
        "id": "wamid.audit.crash", "timestamp": "1788782400", "type": "text", "text": {"body": "Hola"}}]}}]}]}
    event_id = await store_webhook_event(payload, sessionmaker, request_id=None)
    persisted = await persist_payload_phase_a(payload, sessionmaker, request_id=None)
    if len(persisted) != 1:
        raise RuntimeError("Precondition: first message was not persisted")
    # Fault boundary: deliberately omit phase B/C after a real commit; then redeliver.
    await process_webhook_event(event_id, sessionmaker)
    async with sessionmaker() as session:
        event = await session.get(WebhookEvent, event_id)
    observed = {**await counts(sessionmaker), "webhook_status": event.status}
    ok = not (observed["webhook_status"] == "PROCESSED" and observed["outbox"] == 0)
    return "A committed but unprocessed greeting must not be abandoned as PROCESSED", observed, ok


async def outbox_stale_owner(sessionmaker):
    from app.channel.models import Outbox
    from app.channel.worker import claim_due_outbox_batch, process_claimed_outbox_item, recover_stale_sending_outbox
    customer, conversation, message = await seed(sessionmaker)
    t0 = datetime(2026, 9, 7, 12, tzinfo=UTC)
    async with sessionmaker() as session, session.begin():
        item = Outbox(conversation_id=conversation.id, message_id=message.id, channel="WHATSAPP",
            recipient_phone_number=customer.phone_number, payload={"type": "text", "text": {"body": "Audit"}},
            status="PENDING", created_at=t0)
        session.add(item)
    old = (await claim_due_outbox_batch(sessionmaker, t0, 1))[0]
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    class Held:
        async def send_text(self, to, body):
            calls.append("old")
            entered.set()
            await release.wait()
            return "wamid.audit.old"
    class New:
        async def send_text(self, to, body):
            calls.append("new")
            return "wamid.audit.new"
    task = asyncio.create_task(process_claimed_outbox_item(sessionmaker, old, Held(), 5, 300))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        await recover_stale_sending_outbox(sessionmaker, t0 + timedelta(seconds=121), 120, 5, 300)
        new = (await claim_due_outbox_batch(sessionmaker, t0 + timedelta(seconds=130), 1))[0]
        await process_claimed_outbox_item(sessionmaker, new, New(), 5, 300)
    finally:
        release.set()
        await asyncio.wait_for(task, 10)
    observed = {**await counts(sessionmaker), "provider_calls": calls}
    return "Expired owner must not send/settle twice after a newer claim", observed, len(calls) == 1


async def knowledge(sessionmaker):
    from app.conversation.knowledge import render_response
    from data.knowledge_seed import iter_seed_entries
    from scripts.load_knowledge import load_knowledge_entries
    from scripts.sync_knowledge_versions import sync_knowledge_versions
    seed_entry = next(s for s in iter_seed_entries() if s.status == "APPROVED" and not s.allowed_variables)
    original = replace(seed_entry, answer_template="Synthetic version one")
    edited = replace(original, answer_template="Synthetic version two")
    await load_knowledge_entries(sessionmaker, [original])
    inserted = await load_knowledge_entries(sessionmaker, [edited])
    stale = await render_response(sessionmaker, original.code, {})
    plan_text = await sync_knowledge_versions(sessionmaker, [edited], execute=True)
    rendered = await render_response(sessionmaker, original.code, {})
    revoked = replace(edited, status="DRAFT")
    plan_status = await sync_knowledge_versions(sessionmaker, [revoked], execute=True)
    after_revoke = await render_response(sessionmaker, original.code, {})
    observed = dict(reload_inserted=inserted, after_reload=stale, text_plan=plan_text[0].action,
                    after_text_sync=rendered, status_plan=plan_status[0].action, after_revocation=after_revoke)
    return "Text/status publication must agree with the intended published version", observed, after_revoke != rendered


async def append_only(sessionmaker):
    from sqlalchemy import text
    _, _, message = await seed(sessionmaker)
    async with sessionmaker() as session, session.begin():
        role = await session.scalar(text("SELECT current_user"))
        # A no-op UPDATE still tests the database permission/trigger; no history content is changed.
        await session.execute(text("UPDATE message SET content=content WHERE id=:id"), {"id": message.id})
    return "Synthetic owner capability; operational role remains unverified", {"role": role, "update_accepted": True,
        "role_limit": "Fresh database owner only; deployed non-owner role still unverified"}, False


async def media_case(sessionmaker, state, media, caption, payment):
    from unittest.mock import patch
    from app.ai.client import OpenRouterIntentClient
    from app.ai.schemas import IntentClassification
    from app.channel.inbound import classify_and_orchestrate_phase_b_c, persisted_message_from_models
    from data.knowledge_seed import iter_seed_entries
    from scripts.load_knowledge import load_knowledge_entries
    customer, conversation, message = await seed(sessionmaker, state=state, media=media, caption=caption, payment=payment)
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    persisted = persisted_message_from_models(message, conversation)
    async def classifier(*args, **kwargs):
        return IntentClassification(primary_intent="PAYMENT_MESSAGE" if payment else "GENERAL_INFORMATION",
            sub_intent=None, confidence=0.95, requested_action=None, needs_confirmation=False,
            needs_human=False, handoff_reason=None, priority="NORMAL", reasoning_code="AUDIT_PROVIDER_DOUBLE")
    with patch.object(OpenRouterIntentClient, "classify_intent", classifier):
        await classify_and_orchestrate_phase_b_c([persisted], sessionmaker, request_id=None, webhook_event_id=None)
    observed = await counts(sessionmaker)
    should_capture = payment and media in {"image", "document"}
    ok = observed["outbox"] == 0 and (not should_capture or observed["payment_evidence"] == 1)
    return "Human-state silence and passive payment evidence capture", observed, ok


async def run(new_session):
    scenarios = [("H01_after_message_commit", inbox_after_message_commit), ("H02_stale_owner", outbox_stale_owner),
                 ("H16_publication", knowledge), ("H28_owner_update", append_only)]
    for state, media, caption, payment in itertools.product(
            ("WAITING_FOR_HUMAN", "HUMAN_ACTIVE"), ("image", "document", "audio", "video"), (False, True), (False, True)):
        async def fn(sm, state=state, media=media, caption=caption, payment=payment):
            return await media_case(sm, state, media, caption, payment)
        scenarios.append((f"H03_{state}_{media}_caption{int(caption)}_payment{int(payment)}", fn))
    rows = []
    for index, (scenario, fn) in enumerate(scenarios):
        engine = None
        try:
            sessionmaker, engine, database = await new_session("probe" + str(index))
            before = await counts(sessionmaker)
            requirement, observed, ok = await asyncio.wait_for(fn(sessionmaker), 60)
            rows.append(dict(scenario=scenario, schema="ALEMBIC_HEAD", database=database,
                status="OBSERVED_OWNER_ONLY" if scenario == "H28_owner_update" else ("PASS" if ok else "FAIL_REQUIREMENT"), requirement=requirement, persisted_before=before, persisted_effects=observed,
                limits="HTTP/calendar doubled; isolated DB only; not external delivery"))
        except Exception as error:
            rows.append(dict(scenario=scenario, status="HARNESS_ERROR", error_type=type(error).__name__,
                             error=str(error), traceback=traceback.format_exc(), classification="Review traceback; do not automatically call product failure"))
        finally:
            if engine is not None:
                await engine.dispose()
    return rows
