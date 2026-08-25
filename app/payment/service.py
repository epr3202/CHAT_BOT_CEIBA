from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence

SYSTEM_ACTOR = "SYSTEM"
PAYMENT_MEDIA_TYPES = frozenset({"image", "document"})


async def open_payment_handoff(
    session: AsyncSession,
    conversation_id: int,
) -> Handoff | None:
    return await session.scalar(
        select(Handoff)
        .where(
            Handoff.conversation_id == conversation_id,
            Handoff.reason == "PAYMENT_REVIEW",
            Handoff.status.in_(("PENDING", "TAKEN")),
        )
        .order_by(Handoff.id.desc())
        .limit(1)
    )


async def create_payment_evidence_for_open_handoff(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    message: Message,
    *,
    request_id: uuid.UUID | str | None,
) -> PaymentEvidence | None:
    handoff = await open_payment_handoff(session, conversation.id)
    if handoff is None:
        return None
    return await create_payment_evidence(
        session,
        conversation,
        customer,
        message,
        handoff,
        request_id=request_id,
    )


async def create_payment_evidence(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    message: Message,
    handoff: Handoff,
    *,
    request_id: uuid.UUID | str | None,
) -> PaymentEvidence | None:
    media = payment_media_fields(message)
    if media is None:
        return None
    existing = await session.scalar(
        select(PaymentEvidence).where(PaymentEvidence.message_id == message.id)
    )
    if existing is not None:
        return existing

    evidence = PaymentEvidence(
        conversation_id=conversation.id,
        customer_id=customer.id,
        message_id=message.id,
        media_id=media["media_id"],
        mime_type=media["mime_type"],
        declared_sha256=media["declared_sha256"],
        lead_id=conversation.active_lead_id,
        download_status="PENDING",
        download_attempts=0,
        review_status="PENDING_REVIEW",
    )
    session.add(evidence)
    await session.flush()

    session.add(
        AuditEvent(
            actor=SYSTEM_ACTOR,
            action="PAYMENT_EVIDENCE_CREATED",
            entity="payment_evidence",
            old_value=None,
            new_value={
                "evidence_id": evidence.id,
                "conversation_id": conversation.id,
                "message_id": message.id,
                "mime_type": evidence.mime_type,
                "download_status": evidence.download_status,
                "review_status": evidence.review_status,
            },
            reason="Inbound payment evidence registered for human review",
            request_id=request_id,
        )
    )
    if handoff.priority != "URGENT":
        old_priority = handoff.priority
        handoff.priority = "URGENT"
        session.add(
            AuditEvent(
                actor=SYSTEM_ACTOR,
                action="HANDOFF_PRIORITY_RAISED",
                entity="handoff",
                old_value={"handoff_id": handoff.id, "priority": old_priority},
                new_value={"handoff_id": handoff.id, "priority": "URGENT"},
                reason="Payment evidence received",
                request_id=request_id,
            )
        )
    summary_line = (
        f"[comprobante recibido: {evidence.mime_type}, evidencia #{evidence.id}]"
    )
    if summary_line not in handoff.summary:
        handoff.summary = f"{handoff.summary.rstrip()}\n{summary_line}"
    return evidence


def payment_media_fields(message: Message) -> dict[str, str] | None:
    if message.message_type not in PAYMENT_MEDIA_TYPES:
        return None
    raw_content = message.content.get(message.message_type)
    if not isinstance(raw_content, dict):
        return None
    media_id = raw_content.get("media_id") or raw_content.get("id")
    mime_type = raw_content.get("mime_type")
    declared_sha256 = raw_content.get("sha256")
    if not all(
        isinstance(value, str) and value
        for value in (media_id, mime_type, declared_sha256)
    ):
        return None
    return {
        "media_id": media_id,
        "mime_type": mime_type,
        "declared_sha256": declared_sha256,
    }
