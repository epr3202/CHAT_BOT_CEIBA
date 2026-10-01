"""Post-commit, approved customer notices for human payment decisions."""

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.config.settings import Settings
from app.conversation.knowledge import KnowledgeRenderError
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.service import create_handoff
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.booking import deposit_amount
from app.reservation.models import Reservation

BOGOTA = ZoneInfo("America/Bogota")


def skipped(
    session: AsyncSession, evidence: PaymentEvidence, kind: str, reason: str, request_id: str
) -> None:
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action="NOTIFICATION_SKIPPED",
            entity="conversation",
            old_value=None,
            new_value={
                "evidence_id": evidence.id,
                "conversation_id": evidence.conversation_id,
                "result": kind,
            },
            reason=reason,
            request_id=request_id,
        )
    )


async def notify_booking_payment(
    session: AsyncSession,
    sm: Any,
    *,
    evidence: PaymentEvidence,
    kind: str,
    settings: Settings,
    request_id: str,
) -> str:
    from app.orchestrator import service as core

    row = await session.get(Reservation, evidence.reservation_id)
    if row is None or row.conversation_id is None:
        return "DEFERRED"
    if not settings.self_service_booking_enabled:
        skipped(session, evidence, kind, "Reserva autoservicio deshabilitada", request_id)
        return "DEFERRED"
    if row.conversation_id != evidence.conversation_id or row.customer_id != evidence.customer_id:
        skipped(
            session, evidence, kind, "La evidencia no corresponde a la conversación", request_id
        )
        return "DEFERRED"
    customer = await session.get(Customer, row.customer_id, with_for_update=True)
    conversation = await session.get(Conversation, row.conversation_id, with_for_update=True)
    message = await session.get(Message, evidence.message_id)
    plan = await session.get(Plan, row.plan_id)
    if customer is None or conversation is None or message is None or plan is None:
        skipped(session, evidence, kind, "Referencias de notificación incompletas", request_id)
        return "DEFERRED"
    if kind == "CONFLICT":
        conversation.booking_draft = None
        case, response_code = await create_handoff(
            session,
            conversation,
            customer,
            reason="RESERVATION_CONFIRMATION",
            priority="URGENT",
            settings=settings,
            request_id=request_id,
            detail="franja ya reservada; requiere reprogramación",
        )
        try:
            await core.enqueue_template(
                session,
                sm,
                conversation,
                customer,
                message,
                response_code,
                {},
                notice_case=case,
                strict=True,
            )
        except KnowledgeRenderError as exc:
            skipped(session, evidence, kind, exc.reason.value, request_id)
            return "DEFERRED"
        return "ENQUEUED"
    variables = {}
    if kind == "RESERVED":
        response_code = "RESP-BOOKING-CONFIRMED-001"
        local_start = row.starts_at.astimezone(BOGOTA)
        variables = {
            "plan_name": plan,
            "booking_date": local_start.date(),
            "booking_time": local_start.strftime("%H:%M"),
            "missing_amount": max(0, row.price_cop - row.amount_paid_cop),
            # The copy always includes the fixed-price cutoff, including $0 paid in full.
            "balance_due_date": (row.balance_due_at or row.starts_at - timedelta(days=1))
            .astimezone(BOGOTA)
            .date(),
        }
    elif kind == "PARTIAL":
        response_code = "RESP-BOOKING-PARTIAL-001"
        variables = {"missing_amount": max(0, deposit_amount(row.price_cop) - row.amount_paid_cop)}
    elif kind == "REJECTED":
        response_code = "RESP-BOOKING-REJECTED-001"
    else:
        skipped(session, evidence, kind, "Resultado sin plantilla de reserva", request_id)
        return "DEFERRED"
    try:
        await core.enqueue_template(
            session,
            sm,
            conversation,
            customer,
            message,
            response_code,
            variables,
            payment_decision=evidence,
            strict=True,
        )
    except KnowledgeRenderError as exc:
        skipped(session, evidence, kind, exc.reason.value, request_id)
        return "DEFERRED"
    return "ENQUEUED"
