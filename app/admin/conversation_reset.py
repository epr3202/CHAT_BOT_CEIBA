from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.inbound import normalize_phone_number
from app.channel.inbox import retire
from app.channel.models import InboxJob, Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff

RESET_ACTION = "ADMIN_CONVERSATION_RESET"


@dataclass(frozen=True)
class ResetSummary:
    phone_number: str
    customer_id: int | None
    conversations_found: int = 0
    conversations_closed: int = 0
    handoffs_resolved: int = 0
    inbox_jobs_completed: int = 0
    pending_outbox_suppressed: int = 0
    customer_name_cleared: bool = False
    dry_run: bool = True
    active_lead_links_cleared: int = 0
    audit_events_added: int = 0


async def reset_conversation_by_phone(
    session: AsyncSession,
    *,
    raw_phone_number: str,
    dry_run: bool,
    actor: str,
    reason: str | None,
    request_id: str | None,
) -> ResetSummary:
    """Reset within the caller's transaction; preserve message, audit and outbox history."""
    try:
        phone_number = normalize_phone_number(raw_phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not dry_run and not (reason and reason.strip()):
        raise HTTPException(status_code=422, detail="Reason is required for a reset")

    # Intake and inbox processing also lock Customer before Conversation. Keep
    # that order, then lock Handoff by ID as in the R8 ownership protocol.
    customer = await session.scalar(
        select(Customer).where(Customer.phone_number == phone_number)
        .with_for_update().execution_options(populate_existing=True)
    )
    if customer is None:
        return ResetSummary(phone_number=phone_number, customer_id=None, dry_run=dry_run)
    conversations = list(await session.scalars(
        select(Conversation).where(Conversation.customer_id == customer.id)
        .order_by(Conversation.id).with_for_update().execution_options(populate_existing=True)
    ))
    conversation_ids = [conversation.id for conversation in conversations]
    handoffs = list(await session.scalars(
        select(Handoff).where(
            Handoff.conversation_id.in_(conversation_ids), Handoff.status != "RESOLVED",
        ).order_by(Handoff.id).with_for_update().execution_options(populate_existing=True)
    ))
    jobs = list(await session.scalars(
        select(InboxJob).where(
            InboxJob.conversation_id.in_(conversation_ids), InboxJob.status != "COMPLETED",
        ).order_by(InboxJob.id).with_for_update().execution_options(populate_existing=True)
    ))
    if any(job.status in {"PROCESSING", "EXTERNAL"} for job in jobs):
        raise HTTPException(
            status_code=409, detail="Conversation is being processed; retry shortly",
        )
    # The worker owns delivery decisions. Count these rows without locking or
    # changing them; CLOSED/new epoch fences subsequent send admission.
    outbox_items = list(await session.scalars(
        select(Outbox).where(
            Outbox.conversation_id.in_(conversation_ids),
            Outbox.status.in_(("PENDING", "SENDING")),
        ).order_by(Outbox.id)
    ))
    summary = ResetSummary(
        phone_number=phone_number, customer_id=customer.id,
        conversations_found=len(conversations),
        conversations_closed=sum(conversation.state != "CLOSED" for conversation in conversations),
        handoffs_resolved=len(handoffs), inbox_jobs_completed=len(jobs),
        pending_outbox_suppressed=len(outbox_items),
        customer_name_cleared=customer.full_name is not None, dry_run=dry_run,
        active_lead_links_cleared=sum(c.active_lead_id is not None for c in conversations),
        audit_events_added=0 if dry_run else 1,
    )
    if dry_run:
        return summary

    old_value = reset_snapshot(customer, conversations, handoffs, outbox_items, jobs)
    now = datetime.now(UTC)
    customer.full_name = None
    for conversation in conversations:
        conversation.state = "CLOSED"
        conversation.pending_action = None
        conversation.pending_fields = []
        conversation.pending_confirmation = None
        conversation.visit_draft = None
        conversation.last_question_code = None
        conversation.last_intent = None
        conversation.failed_understanding_count = 0
        conversation.services_failed_understanding_count = 0
        conversation.bot_enabled = True
        conversation.assigned_agent_id = None
        conversation.active_lead_id = None
        conversation.automation_epoch = uuid4()
    for handoff in handoffs:
        handoff.status = "RESOLVED"
        handoff.resolved_at = now
        handoff.assigned_to = None
        handoff.assigned_agent_id = None
    for job in jobs:
        retire(job, "COMPLETED", "RESET_BY_ADMIN")
        job.completed_at = now
    session.add(AuditEvent(
        actor=actor, action=RESET_ACTION, entity="customer", old_value=old_value,
        new_value={
            "phone_number": phone_number, "customer_id": customer.id,
            "conversation_ids": conversation_ids, "conversation_state": "CLOSED",
            "full_name": None, "active_lead_id": None,
            "inbox_jobs_completed": len(jobs),
            "pending_outbox_suppressed": len(outbox_items),
            "automation_epochs": {str(c.id): str(c.automation_epoch) for c in conversations},
            "reason": reason.strip(),
        },
        reason="Admin conversation reset", request_id=request_id,
    ))
    return summary


def reset_snapshot(
    customer: Customer,
    conversations: list[Conversation],
    handoffs: list[Handoff],
    outbox_items: list[Outbox],
    jobs: list[InboxJob],
) -> dict[str, Any]:
    return {
        "customer": {"id": customer.id, "phone_number": customer.phone_number,
                     "full_name": customer.full_name},
        "conversations": [
            {
                "id": c.id, "state": c.state,
                "active_lead_id": str(c.active_lead_id) if c.active_lead_id else None,
                "bot_enabled": c.bot_enabled, "assigned_agent_id": c.assigned_agent_id,
                "automation_epoch": str(c.automation_epoch),
                "pending_action": c.pending_action, "pending_fields": c.pending_fields,
                "pending_confirmation": c.pending_confirmation, "visit_draft": c.visit_draft,
            } for c in conversations
        ],
        "handoffs": [
            {"id": h.id, "conversation_id": h.conversation_id, "status": h.status,
             "assigned_to": h.assigned_to, "assigned_agent_id": h.assigned_agent_id}
            for h in handoffs
        ],
        "outbox": [
            {"id": row.id, "conversation_id": row.conversation_id, "status": row.status}
            for row in outbox_items
        ],
        "inbox_jobs": [
            {"id": job.id, "conversation_id": job.conversation_id, "status": job.status,
             "last_error": job.last_error} for job in jobs
        ],
    }
