"""Post-commit, approved customer notices for human payment decisions."""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.config.settings import Settings
from app.conversation.knowledge import (
    KnowledgeRenderError,
    get_latest_response,
    variables_in_template,
)
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.handoff.service import create_handoff
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.booking import deposit_amount
from app.reservation.models import Reservation
from app.reservation.settlement import has_pending_payment_evidence

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
    if row is None:
        return "DEFERRED"
    if row.customer_id != evidence.customer_id:
        skipped(
            session, evidence, kind, "La evidencia no corresponde a la conversación", request_id
        )
        return "DEFERRED"
    customer = await session.get(Customer, row.customer_id, with_for_update=True)
    conversations = list(
        await session.scalars(
            select(Conversation)
            .where(
                Conversation.customer_id == row.customer_id,
                Conversation.id.in_(
                    select(PaymentEvidence.conversation_id).where(
                        PaymentEvidence.reservation_id == row.reservation_id,
                        PaymentEvidence.customer_id == row.customer_id,
                    )
                ),
            )
            .order_by(Conversation.id)
            .with_for_update()
        )
    )
    conversation = next(
        (item for item in conversations if item.id == evidence.conversation_id), None
    )
    message = await session.get(Message, evidence.message_id)
    plan = await session.get(Plan, row.plan_id)
    if customer is None or conversation is None or message is None or plan is None:
        skipped(session, evidence, kind, "Referencias de notificación incompletas", request_id)
        return "DEFERRED"
    if conversation.customer_id != customer.id or message.conversation_id != conversation.id:
        skipped(session, evidence, kind, "Referencias de notificación no relacionadas", request_id)
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
        await resolve_payment_handoffs(session, evidence, row, conversations, request_id=request_id)
        if not settings.self_service_booking_enabled:
            skipped(session, evidence, kind, "Reserva sin notificación conversacional", request_id)
            return "DEFERRED"
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
                request_id=request_id,
            )
        except KnowledgeRenderError as exc:
            skipped(session, evidence, kind, exc.reason.value, request_id)
            return "DEFERRED"
        return "ENQUEUED"
    await resolve_payment_handoffs(session, evidence, row, conversations, request_id=request_id)
    if not settings.self_service_booking_enabled:
        skipped(session, evidence, kind, "Reserva autoservicio deshabilitada", request_id)
        return "DEFERRED"
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
        required_deposit = deposit_amount(row.price_cop)
        candidates = {
            "received_amount": evidence.amount_cop,
            "paid_amount": row.amount_paid_cop,
            "deposit_amount": required_deposit,
            "missing_amount": max(0, required_deposit - row.amount_paid_cop),
            "bank_name": settings,
            "account_type": settings,
            "account_number": settings,
            "account_holder": settings,
            "breb_key": settings,
        }
        latest = await get_latest_response(sm, response_code)
        required_variables = variables_in_template(latest.answer_template) if latest else set()
        # Older versions require only missing_amount; malformed new templates
        # still fail strict rendering for missing or disallowed variables.
        variables = {key: value for key, value in candidates.items() if key in required_variables}
    elif kind == "REJECTED":
        response_code = "RESP-BOOKING-REJECTED-001"
    elif kind == "BALANCE_PAID":
        response_code = "RESP-BOOKING-BALANCE-PAID-001"
        local_start = row.starts_at.astimezone(BOGOTA)
        variables = {
            "plan_name": plan,
            "booking_date": local_start.date(),
            "booking_time": local_start.strftime("%H:%M"),
        }
    elif kind == "BALANCE_PARTIAL":
        response_code = "RESP-BOOKING-BALANCE-PARTIAL-001"
        if row.balance_due_at is None:
            skipped(session, evidence, kind, "Saldo sin fecha de vencimiento", request_id)
            return "DEFERRED"
        variables = {
            "missing_amount": max(0, row.price_cop - row.amount_paid_cop),
            "balance_due_date": row.balance_due_at.astimezone(BOGOTA).date(),
        }
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
            request_id=request_id,
        )
    except KnowledgeRenderError as exc:
        skipped(session, evidence, kind, exc.reason.value, request_id)
        return "DEFERRED"
    return "ENQUEUED"


async def resolve_payment_handoffs(
    session: AsyncSession,
    evidence: PaymentEvidence,
    reservation: Reservation,
    conversations: list[Conversation],
    *,
    request_id: str,
) -> None:
    """End payment review after the last pending evidence without ending another case.

    Caller owns Customer then the evidence-backed conversations in ID order.
    Inbound cannot race the pending checks or transitions back to the bot.
    """
    if await has_pending_payment_evidence(session, reservation.reservation_id):
        return
    for conversation in conversations:
        # A conversation can reuse PAYMENT_REVIEW for another reservation or an
        # unlinked receipt. Finishing this reservation must not finish that work.
        other_pending = await session.scalar(
            select(PaymentEvidence.id)
            .where(
                PaymentEvidence.conversation_id == conversation.id,
                PaymentEvidence.customer_id == reservation.customer_id,
                PaymentEvidence.review_status == "PENDING_REVIEW",
            )
            .limit(1)
        )
        if other_pending is not None:
            continue
        cases = list(
            await session.scalars(
                select(Handoff)
                .where(
                    Handoff.conversation_id == conversation.id,
                    Handoff.status.in_(("PENDING", "TAKEN")),
                )
                .order_by(Handoff.id)
                .with_for_update()
            )
        )
        payment_cases = [case for case in cases if case.reason == "PAYMENT_REVIEW"]
        for case in payment_cases:
            previous = case.status
            case.status = "RESOLVED"
            case.resolved_at = datetime.now(UTC)
            case.assigned_agent_id = None
            case.assigned_to = None
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="HANDOFF_RESOLVED",
                    entity="handoff",
                    old_value={"handoff_id": case.id, "status": previous},
                    new_value={
                        "handoff_id": case.id,
                        "status": "RESOLVED",
                        "evidence_id": evidence.id,
                        "reservation_id": str(reservation.reservation_id),
                        "reviewed_by_agent_id": evidence.reviewed_by_agent_id,
                    },
                    reason="Último comprobante pendiente liquidado por un asesor",
                    request_id=request_id,
                )
            )
        if (
            not payment_cases
            or len(cases) != len(payment_cases)
            or conversation.state not in {"WAITING_FOR_HUMAN", "HUMAN_ACTIVE"}
        ):
            continue
        conversation.bot_enabled = True
        conversation.pending_action = None
        conversation.assigned_agent_id = None
        if conversation.state == "HUMAN_ACTIVE":
            await transition_conversation(
                session,
                conversation,
                ConversationState.RETURNED_TO_BOT,
                actor="SYSTEM",
                reason="Revisión humana de pagos finalizada",
                request_id=request_id,
            )
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor="SYSTEM",
            reason="Comprobantes revisados; retorno al bot sin otros casos abiertos",
            request_id=request_id,
        )
