"""Server provenance and brief durable send admission, separate from R1 acquisition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.channel.models import Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence

Eligibility = Literal["ELIGIBLE", "SUPPRESSED", "REVIEW"]
Decision = Literal["ELIGIBLE", "ADMITTED", "SUPPRESSED", "REVIEW", "DISCARDED"]

# Codes alone grant nothing: the producer must also supply the exact newly created case.
TRANSFER_RESPONSE_CODES = frozenset({
    "RESP-HANDOFF-001", "RESP-HANDOFF-002", "RESP-QUOTE-004", "RESP-QUOTE-009",
    "RESP-CATALOG-003", "RESP-FALLBACK-003", "RESP-CALENDAR-ERROR-001",
    "RESP-CALENDAR-ERROR-002", "RESP-CALENDAR-ERROR-003", "RESP-CALENDAR-ERROR-004",
    "RESP-VISIT-CONFIRM-006", "RESP-RESCHEDULE-006", "RESP-CANCEL-VISIT-005",
})


def automatic_context(conversation: Conversation, purpose: Literal["TEMPLATE", "CATALOG"]
                      ) -> dict[str, Any]:
    # New unsaved conversations also need the same identity before their first flush.
    if conversation.automation_epoch is None:
        conversation.automation_epoch = uuid4()
    return {"origin": "AUTO", "purpose": purpose, "epoch": str(conversation.automation_epoch)}


async def handoff_context(session: AsyncSession, conversation: Conversation, case: Handoff
                          ) -> dict[str, Any]:
    await session.flush()
    if case.conversation_id != conversation.id or case.status != "PENDING":
        raise ValueError("Cannot authorize an unrelated or non-pending handoff notice")
    return {"origin": "HANDOFF_NOTICE", "purpose": "TRANSFER", "case_id": case.id,
            "epoch": str(conversation.automation_epoch)}


def human_context(agent_id: int) -> dict[str, Any]:
    return {"origin": "HUMAN_REPLY", "purpose": "REPLY", "agent_id": agent_id}


def payment_review_context(evidence: PaymentEvidence) -> dict[str, Any]:
    return {"origin": "PAYMENT_REVIEW_RESULT", "purpose": "PAYMENT_DECISION",
            "evidence_id": evidence.id, "decision": evidence.review_status,
            "agent_id": evidence.reviewed_by_agent_id}


async def lock_delivery_row(session: AsyncSession, outbox_id: int, *, skip: bool = False
                            ) -> tuple[Conversation, Outbox] | None:
    # Locator values do not authorize. Recheck every relation after canonical locks.
    located = (await session.execute(select(
        Outbox.conversation_id, Conversation.customer_id,
    ).join(Conversation, Conversation.id == Outbox.conversation_id).where(
        Outbox.id == outbox_id,
    ))).first()
    if located is None:
        return None
    conversation_id, customer_id = located
    customer = await session.scalar(select(Customer).where(Customer.id == customer_id)
                                    .with_for_update(skip_locked=skip))
    if customer is None:
        return None
    conversation = await session.get(Conversation, conversation_id, populate_existing=True,
                                     with_for_update={"skip_locked": skip})
    if conversation is None or conversation.customer_id != customer_id:
        return None
    row = await session.get(Outbox, outbox_id, populate_existing=True,
                            with_for_update={"skip_locked": skip})
    if row is None or row.conversation_id != conversation.id:
        return None
    return conversation, row


async def human_proof(session: AsyncSession, row: Outbox) -> int | None:
    if row.message_kind != "TEXT" or row.payload.get("agent") is not True:
        return None
    events = await session.scalars(select(AuditEvent).where(
        AuditEvent.action == "AGENT_MESSAGE_ENQUEUED", AuditEvent.entity == "outbox",
        AuditEvent.new_value["outbox_id"].as_string() == str(row.id),
    ))
    for event in events:
        value = event.new_value
        if (isinstance(value, dict) and type(value.get("outbox_id")) is int
                and type(value.get("conversation_id")) is int
                and value["outbox_id"] == row.id
                and value["conversation_id"] == row.conversation_id):
            return event.id
    return None


async def eligibility(session: AsyncSession, conversation: Conversation, row: Outbox
                      ) -> tuple[Eligibility, str]:
    context = row.delivery_context
    if context is None:
        proof = await human_proof(session, row)
        if proof is None:
            return "REVIEW", "LEGACY_ORIGIN_UNPROVEN"
        context = {"origin": "HUMAN_REPLY", "purpose": "REPLY", "legacy_proof": proof}
        row.delivery_context = context
    if not isinstance(context, dict):
        return "REVIEW", "INVALID_DELIVERY_CONTEXT"
    origin = context.get("origin")
    if not isinstance(origin, str):
        return "REVIEW", "INVALID_DELIVERY_ORIGIN"
    if origin == "HUMAN_REPLY":
        if context.get("purpose") != "REPLY" or await human_proof(session, row) is None:
            return "REVIEW", "HUMAN_ORIGIN_UNPROVEN"
        return "ELIGIBLE", "AUTHORIZED_HUMAN_REPLY"
    if origin == "PAYMENT_REVIEW_RESULT":
        evidence_id = context.get("evidence_id")
        if type(evidence_id) is not int or context.get("purpose") != "PAYMENT_DECISION":
            return "REVIEW", "PAYMENT_DECISION_UNPROVEN"
        evidence = await session.get(PaymentEvidence, evidence_id)
        if (evidence is None or evidence.conversation_id != conversation.id
                or evidence.customer_id != conversation.customer_id
                or evidence.message_id != row.message_id
                or evidence.review_status not in {"ACCEPTED", "REJECTED"}
                or evidence.review_status != context.get("decision")
                or type(context.get("agent_id")) is not int
                or evidence.reviewed_by_agent_id != context["agent_id"]
                or evidence.reviewed_at is None):
            return "REVIEW", "PAYMENT_DECISION_UNPROVEN"
        return "ELIGIBLE", "AUTHORIZED_PAYMENT_DECISION"
    if origin not in {"AUTO", "HANDOFF_NOTICE"}:
        return "REVIEW", "UNKNOWN_DELIVERY_ORIGIN"
    if origin == "HANDOFF_NOTICE":
        case_id = context.get("case_id")
        if type(case_id) is not int or context.get("purpose") != "TRANSFER":
            return "REVIEW", "HANDOFF_NOTICE_UNPROVEN"
        # All runtime status writers hold Conversation before Handoff (R8); R5 only
        # captures summary under NOWAIT. No Outbox -> Handoff lock acquisition here.
        case = await session.get(Handoff, case_id)
        if case is None or case.conversation_id != conversation.id:
            return "REVIEW", "HANDOFF_NOTICE_UNRELATED"
        if case.status != "PENDING" or conversation.state != "WAITING_FOR_HUMAN":
            return "SUPPRESSED", "HANDOFF_WAIT_ENDED"
    elif context.get("purpose") not in ("TEMPLATE", "CATALOG"):
        return "REVIEW", "AUTOMATIC_PURPOSE_UNPROVEN"
    if not isinstance(context.get("epoch"), str):
        return "REVIEW", "AUTOMATION_PERIOD_UNPROVEN"
    if context["epoch"] != str(conversation.automation_epoch):
        return "SUPPRESSED", "AUTOMATION_PERIOD_REVOKED"
    if origin == "AUTO" and (not conversation.bot_enabled or conversation.state in {
        "WAITING_FOR_HUMAN", "HUMAN_ACTIVE", "CLOSED",
    }):
        return "SUPPRESSED", "AUTOMATION_PAUSED"
    return "ELIGIBLE", "CURRENT_AUTOMATION_PERIOD"


def stop_delivery(row: Outbox, result: Eligibility, reason: str, now: datetime) -> None:
    # An earlier admitted call may have effects; never call it "not sent" after a pause.
    admission = row.send_admission
    if isinstance(admission, dict) and admission.get("phase") in {"ADMITTED", "UNKNOWN"}:
        result, reason = "REVIEW", "EXTERNAL_RESULT_UNCERTAIN_" + reason
    row.status = result
    row.delivery_reason, row.delivery_decided_at = reason, now
    row.claim_token, row.claimed_at, row.next_attempt_at = None, None, None


async def _decide(sessionmaker: async_sessionmaker[AsyncSession], outbox_id: int,
                  claim_token: UUID, *, admit: bool) -> Decision:
    async with sessionmaker() as session, session.begin():
        locked = await lock_delivery_row(session, outbox_id)
        if locked is None:
            return "DISCARDED"
        conversation, row = locked
        if not isinstance(claim_token, UUID) or row.status != "SENDING" or (
            row.claim_token != claim_token
        ):
            return "DISCARDED"
        previous = row.send_admission
        if isinstance(previous, dict) and previous.get("phase") == "ADMITTED":
            return "DISCARDED"  # Do not retire an in-flight attempt owned by another caller.
        result, reason = await eligibility(session, conversation, row)
        if result != "ELIGIBLE":
            stop_delivery(row, result, reason, datetime.now(UTC))
            return row.status
        if not admit:
            return "ELIGIBLE"
        row.send_admission = {"id": str(uuid4()), "claim_token": str(claim_token),
                              "at": datetime.now(UTC).isoformat(), "phase": "ADMITTED"}
        return "ADMITTED"  # Context manager commits before the caller receives permission.


async def admit_outbox(sessionmaker: async_sessionmaker[AsyncSession], outbox_id: int,
                       claim_token: UUID) -> Decision:
    return await _decide(sessionmaker, outbox_id, claim_token, admit=True)


async def check_outbox(sessionmaker: async_sessionmaker[AsyncSession], outbox_id: int,
                       claim_token: UUID) -> Decision:
    return await _decide(sessionmaker, outbox_id, claim_token, admit=False)


async def reject_media_admission(sessionmaker: async_sessionmaker[AsyncSession], outbox_id: int,
                                 claim_token: UUID) -> bool:
    async with sessionmaker() as session, session.begin():
        locked = await lock_delivery_row(session, outbox_id)
        if locked is None:
            return False
        _, row = locked
        if row.status != "SENDING" or row.claim_token != claim_token:
            return False
        row.send_admission = {**(row.send_admission or {}), "phase": "REJECTED_MEDIA"}
        return True
