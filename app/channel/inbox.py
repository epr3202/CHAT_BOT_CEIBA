"""Durable per-message processing, with one shared protocol for API, worker and CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channel import inbound
from app.channel.models import InboxJob, Message, WebhookEvent
from app.config.settings import Settings, get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.orchestrator.inbox_effects import AgendaResults, DeferredAgendaCall, agenda_results

logger = structlog.get_logger(__name__)
SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class InboxClaim:
    id: int
    message_id: int
    conversation_id: int
    claim_token: UUID
    persisted: inbound.PersistedInboundMessage
    context_fingerprint: str
    request_id: UUID | None
    silent: bool


def silent_reason(conversation: Conversation) -> str | None:
    if conversation.state in {"HUMAN_ACTIVE", "WAITING_FOR_HUMAN", "CLOSED"}:
        return "SILENT_" + conversation.state
    return "SILENT_BOT_DISABLED" if not conversation.bot_enabled else None


def fingerprint(conversation: Conversation, customer: Customer) -> str:
    # Local processing order plus this check cover relevant concurrent human/context changes.
    values = {
        c.name: getattr(conversation, c.name)
        for c in Conversation.__table__.columns
        if c.name not in {"created_at", "last_message_at"}
    }
    values["customer_full_name"] = customer.full_name
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


async def lock_context(
    session: AsyncSession, conversation_id: int, *, skip: bool = False
) -> tuple[Customer, Conversation] | None:
    customer_id = await session.scalar(
        select(Conversation.customer_id).where(Conversation.id == conversation_id)
    )
    if customer_id is None:
        return None
    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id).with_for_update(skip_locked=skip)
    )
    if customer is None:
        return None
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update(skip_locked=skip)
    )
    return (customer, conversation) if conversation is not None else None


async def owned(
    session: AsyncSession, claim: InboxClaim
) -> tuple[InboxJob, Customer, Conversation] | None:
    context = await lock_context(session, claim.conversation_id)
    job = await session.get(InboxJob, claim.id, with_for_update=True)
    if (
        context is None
        or job is None
        or job.message_id != claim.message_id
        or job.status not in {"PROCESSING", "EXTERNAL"}
        or not isinstance(claim.claim_token, UUID)
        or job.claim_token != claim.claim_token
    ):
        logger.info(
            "inbox_result_discarded",
            job_id=claim.id,
            conversation_id=claim.conversation_id,
            request_id=str(claim.request_id) if claim.request_id else None,
            outcome="DISCARDED",
            reason="not_current_owner",
        )
        return None
    return job, *context


def retire(job: InboxJob, status: str, reason: str | None = None) -> None:
    job.status = status
    job.claim_token = None
    job.claimed_at = None
    job.next_attempt_at = None
    job.last_error = reason


def fail_locked(job: InboxJob, reason: str, now: datetime, settings: Settings) -> None:
    job.attempts += 1
    if job.external_operation is not None:
        retire(job, "REVIEW", "EXTERNAL_OUTCOME_UNCERTAIN")
    elif job.attempts >= settings.inbox_max_attempts:
        retire(job, "FAILED", reason)
    else:
        retire(job, "PENDING", reason)
        job.next_attempt_at = now + timedelta(
            seconds=min(2**job.attempts, settings.inbox_max_backoff_seconds)
        )


async def settle_inbox_failure(
    sm: SessionMaker, claim: InboxClaim, error: Exception, now: datetime | None = None
) -> str:
    async with sm() as session, session.begin():
        result = await owned(session, claim)
        if result is None:
            return "DISCARDED"
        job, _, _ = result
        fail_locked(job, type(error).__name__, now or datetime.now(UTC), get_settings())
        logger.info(
            "inbox_attempt_failed",
            job_id=job.id,
            outcome=job.status,
            reason=job.last_error,
            conversation_id=claim.conversation_id,
            request_id=str(claim.request_id) if claim.request_id else None,
        )
    return "FAILED"


async def recover_stale_inbox(sm: SessionMaker, now: datetime, settings: Settings) -> int:
    cutoff = now - timedelta(seconds=settings.inbox_claim_timeout_seconds)
    async with sm() as session:
        candidates = (
            await session.execute(
                select(InboxJob.id, InboxJob.conversation_id)
                .where(
                    InboxJob.status.in_(("PROCESSING", "EXTERNAL")), InboxJob.claimed_at < cutoff
                )
                .order_by(InboxJob.id)
                .limit(settings.inbox_batch_size)
            )
        ).all()
    recovered = 0
    for job_id, conversation_id in candidates:
        async with sm() as session, session.begin():
            if await lock_context(session, conversation_id, skip=True) is None:
                continue
            job = await session.get(InboxJob, job_id, with_for_update=True)
            if job.status in {"PROCESSING", "EXTERNAL"} and job.claimed_at < cutoff:
                fail_locked(job, "CLAIM_EXPIRED", now, settings)
                recovered += 1
                logger.info(
                    "inbox_claim_recovered",
                    job_id=job.id,
                    outcome=job.status,
                    reason=job.last_error,
                )
    return recovered


async def claim_inbox_batch(
    sm: SessionMaker, now: datetime, batch_size: int, message_ids: list[int] | None = None
) -> list[InboxClaim]:
    # Earliest unfinished local acceptance in each conversation. FAILED/REVIEW blocks that
    # conversation until explicit intervention, but does not block other conversations.
    first = (
        select(func.min(InboxJob.id))
        .where(InboxJob.status != "COMPLETED")
        .group_by(InboxJob.conversation_id)
    )
    statement = select(InboxJob.conversation_id).where(
        InboxJob.id.in_(first),
        InboxJob.status == "PENDING",
        or_(InboxJob.next_attempt_at.is_(None), InboxJob.next_attempt_at <= now),
    )
    if message_ids is not None:
        statement = statement.where(InboxJob.message_id.in_(message_ids))
    async with sm() as session:
        candidates = list(
            (await session.scalars(statement.order_by(InboxJob.id).limit(batch_size))).all()
        )
    claims = []
    for conversation_id in candidates:
        # One context per transaction: no batch can hold locks across different customers.
        async with sm() as session, session.begin():
            context = await lock_context(session, conversation_id, skip=True)
            if context is None:
                continue
            customer, conversation = context
            job = await session.scalar(
                select(InboxJob)
                .where(InboxJob.conversation_id == conversation_id, InboxJob.status != "COMPLETED")
                .order_by(InboxJob.id)
                .limit(1)
                .with_for_update()
            )
            if (
                job is None
                or job.status != "PENDING"
                or (job.next_attempt_at and job.next_attempt_at > now)
                or (message_ids is not None and job.message_id not in message_ids)
            ):
                continue
            message = await session.get(Message, job.message_id)
            job.status, job.claim_token, job.claimed_at = "PROCESSING", uuid4(), now
            claims.append(
                InboxClaim(
                    job.id,
                    job.message_id,
                    conversation_id,
                    job.claim_token,
                    inbound.persisted_message_from_models(message, conversation),
                    fingerprint(conversation, customer),
                    inbound.parse_request_id(job.request_id),
                    bool(silent_reason(conversation)),
                )
            )
    return claims


async def apply_turn(
    sm: SessionMaker, claim: InboxClaim, turn: inbound.ClassifiedTurn | None, results: AgendaResults
) -> str:
    async with sm() as session, session.begin():
        current = await owned(session, claim)
        if current is None:
            return "DISCARDED"
        job, customer, conversation = current
        silent = silent_reason(conversation)
        if fingerprint(conversation, customer) != claim.context_fingerprint:
            if job.external_operation is not None:
                retire(job, "REVIEW", "CONTEXT_CHANGED_AFTER_EXTERNAL")
                return "REVIEW"
            if silent is None:
                fail_locked(job, "CONTEXT_CHANGED_RECLASSIFY", datetime.now(UTC), get_settings())
                return "RETRY"
        message = await session.get(Message, claim.message_id)
        # Multimedia routing retains its existing business behavior (H03 remains separate).
        handled = await inbound.route_non_text_in_session(
            session,
            claim.persisted,
            message,
            conversation,
            customer,
            sm,
            settings=get_settings(),
            request_id=claim.request_id,
        )
        if not handled:
            if turn is None and silent is None:
                raise RuntimeError("Missing classified turn")
            results.position = 0
            token = agenda_results.set(results)
            try:
                await inbound.orchestrate_inbound_message(
                    session,
                    get_settings(),
                    sm,
                    inbound.OrchestrationInput(
                        conversation=conversation,
                        customer=customer,
                        inbound_message=message,
                        message_text=claim.persisted.message_text,
                        request_id=claim.request_id,
                        decision_source=turn.decision_source if turn else "DETERMINISTIC",
                        directed_event_type=turn.directed_event_type if turn else None,
                        services_resolution_failed=turn.services_resolution_failed
                        if turn
                        else False,
                        confidence_entity_rescued=turn.confidence_entity_rescued if turn else False,
                    ),
                    classification=turn.classification if turn else None,
                    ai_error_reason=turn.ai_error_reason if turn else None,
                )
            finally:
                agenda_results.reset(token)
        retire(job, "COMPLETED")
        job.completed_at = datetime.now(UTC)
        job.completion_reason = "ROUTED_NON_TEXT" if handled else silent or "ORCHESTRATED"
    logger.info(
        "inbox_completed",
        job_id=claim.id,
        conversation_id=claim.conversation_id,
        request_id=str(claim.request_id) if claim.request_id else None,
        outcome="COMPLETED",
        reason=job.completion_reason,
    )
    return "COMPLETED"


async def prepare_external(sm: SessionMaker, claim: InboxClaim, call: DeferredAgendaCall) -> bool:
    async with sm() as session, session.begin():
        current = await owned(session, claim)
        if current is None:
            return False
        job, customer, conversation = current
        if fingerprint(conversation, customer) != claim.context_fingerprint:
            fail_locked(job, "CONTEXT_CHANGED_RECLASSIFY", datetime.now(UTC), get_settings())
            return False
        if call.mutating:
            job.status = "EXTERNAL"
            job.external_operation = call.name
    return True


async def record_external_result(sm: SessionMaker, claim: InboxClaim, value: Any) -> bool:
    async with sm() as session, session.begin():
        current = await owned(session, claim)
        if current is None:
            return False
        current[0].external_result = {
            key: str(getattr(value, key))
            for key in ("appointment_id", "external_calendar_id", "response_code")
            if getattr(value, key, None) is not None
        }
    return True


async def process_claimed_inbox(sm: SessionMaker, claim: InboxClaim) -> str:
    try:
        text = claim.persisted.message_text.strip()
        turn = (
            await inbound.classify_message(claim.persisted, sm, claim.request_id) if text else None
        )
        results = AgendaResults()
        for _ in range(12):  # Bound the number of deferred agenda reads/calls in one turn.
            try:
                return await apply_turn(sm, claim, turn, results)
            except DeferredAgendaCall as call:
                # The attempted local transaction rolled back. No context/job locks survive.
                if not await prepare_external(sm, claim, call):
                    return "DISCARDED"
                value = await call.method(*call.args, **call.kwargs)
                if call.mutating and not await record_external_result(sm, claim, value):
                    return "DISCARDED"
                results.results.append((call.name, call.signature, value))
        raise RuntimeError("Agenda operation budget exhausted")
    except asyncio.CancelledError:
        # Graceful cancellation before an external effect can immediately release its own
        # acquisition. Actual process death cannot run this and requires the durable reaper.
        async with sm() as session, session.begin():
            current = await owned(session, claim)
            if current is not None:
                job = current[0]
                retire(
                    job,
                    "REVIEW" if job.external_operation else "PENDING",
                    "EXTERNAL_OUTCOME_UNCERTAIN" if job.external_operation else "CANCELLED",
                )
        raise
    except Exception as error:
        return await settle_inbox_failure(sm, claim, error)


async def expand_event(sm: SessionMaker, event_id: int, now: datetime) -> list[int]:
    settings = get_settings()
    async with sm() as session, session.begin():
        event = await session.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .with_for_update(skip_locked=True)
        )
        if event is None or event.status in {"PROCESSED", "EXHAUSTED", "REVIEW"}:
            return []
        if event.intake_version != 2:
            event.status, event.error = "REVIEW", "LEGACY_EVENT_UNPROVEN"
            return []
        if event.status in {"RECEIVED", "FAILED"}:
            if event.next_attempt_at is not None and event.next_attempt_at > now:
                return []
            try:
                async with session.begin_nested():
                    await inbound.persist_payload_phase_a_in_session(
                        session, event.payload, inbound.parse_request_id(event.request_id)
                    )
                event.status, event.error, event.next_attempt_at = "PREPARED", None, None
            except Exception as error:
                event.ingest_attempts += 1
                event.status = (
                    "EXHAUSTED"
                    if event.ingest_attempts >= settings.inbox_max_attempts
                    else "FAILED"
                )
                event.error = str(error)[:4000]
                event.next_attempt_at = now + timedelta(
                    seconds=min(2**event.ingest_attempts, settings.inbox_max_backoff_seconds)
                )
                logger.info(
                    "inbox_expansion_failed",
                    event_id=event.id,
                    outcome=event.status,
                    reason=type(error).__name__,
                )
                return []
        external_ids = [
            m.external_message_id for m in inbound.extract_inbound_messages(event.payload)
        ]
        return list(
            (
                await session.scalars(
                    select(Message.id).where(Message.external_message_id.in_(external_ids))
                )
            ).all()
        )


async def refresh_event(sm: SessionMaker, event_id: int) -> str:
    async with sm() as session, session.begin():
        event = await session.get(WebhookEvent, event_id, with_for_update=True)
        if event is None:
            return "MISSING"
        if event.status != "PREPARED":
            return event.status
        ids = {m.external_message_id for m in inbound.extract_inbound_messages(event.payload)}
        statuses = list(
            (
                await session.scalars(
                    select(InboxJob.status)
                    .join(Message, Message.id == InboxJob.message_id)
                    .where(Message.external_message_id.in_(ids))
                )
            ).all()
        )
        if len(statuses) != len(ids):
            event.status, event.error = "REVIEW", "MISSING_MESSAGE_CONTROL"
        elif all(s == "COMPLETED" for s in statuses):
            await inbound.mark_webhook_event_processed(event_id, session)
        elif "REVIEW" in statuses:
            event.status, event.error = "REVIEW", "MESSAGE_REQUIRES_REVIEW"
        elif "FAILED" in statuses:
            event.status, event.error = "EXHAUSTED", "MESSAGE_ATTEMPTS_EXHAUSTED"
        if event.status == "PREPARED":
            event.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=get_settings().inbox_poll_interval_seconds
            )
        return event.status


async def process_message_ids(sm: SessionMaker, ids: list[int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for _ in range(len(ids)):
        claims = await claim_inbox_batch(
            sm, datetime.now(UTC), get_settings().inbox_batch_size, ids
        )
        if not claims:
            break
        for claim in claims:
            counts[await process_claimed_inbox(sm, claim)] += 1
    return dict(counts)


async def process_event(event_id: int, sm: SessionMaker) -> dict[str, int]:
    ids = await expand_event(sm, event_id, datetime.now(UTC))
    counts = await process_message_ids(sm, ids)
    status = await refresh_event(sm, event_id)
    counts["EVENT_" + status] = 1
    return counts


async def process_inbox_once(
    sm: SessionMaker, *, settings: Settings | None = None, now: datetime | None = None
) -> dict[str, int]:
    settings, now = settings or get_settings(), now or datetime.now(UTC)
    counts: Counter[str] = Counter()
    counts["RECOVERED"] = await recover_stale_inbox(sm, now, settings)
    async with sm() as session:
        events = list(
            (
                await session.scalars(
                    select(WebhookEvent.id)
                    .where(
                        WebhookEvent.intake_version == 2,
                        WebhookEvent.status.in_(("RECEIVED", "FAILED")),
                        or_(
                            WebhookEvent.next_attempt_at.is_(None),
                            WebhookEvent.next_attempt_at <= now,
                        ),
                    )
                    .order_by(WebhookEvent.id)
                    .limit(settings.inbox_batch_size)
                )
            ).all()
        )
    for event_id in events:
        await expand_event(sm, event_id, now)
    for claim in await claim_inbox_batch(sm, now, settings.inbox_batch_size):
        counts[await process_claimed_inbox(sm, claim)] += 1
    async with sm() as session:
        prepared = list(
            (
                await session.scalars(
                    select(WebhookEvent.id)
                    .where(
                        WebhookEvent.status == "PREPARED",
                        or_(
                            WebhookEvent.next_attempt_at.is_(None),
                            WebhookEvent.next_attempt_at <= now,
                        ),
                    )
                    .order_by(WebhookEvent.next_attempt_at.asc().nulls_first(), WebhookEvent.id)
                    .limit(settings.inbox_batch_size)
                )
            ).all()
        )
    for event_id in prepared:
        counts["EVENT_" + await refresh_event(sm, event_id)] += 1
    return dict(counts)
