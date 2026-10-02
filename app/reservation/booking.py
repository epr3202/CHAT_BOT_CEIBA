"""Pending booking requests and evidence linkage; no calendar effects or payment approval."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.models import Reservation
from app.reservation.service import transition_reservation

BOGOTA = ZoneInfo("America/Bogota")


class InvalidBookingPlan(ValueError):
    """An inactive plan or mismatched event type cannot create a booking request."""


async def create_pending_reservation(
    session: AsyncSession,
    *,
    lead: Lead,
    event: Event,
    plan: Plan,
    conversation: Conversation | None,
    customer: Customer,
    starts_at: datetime,
    actor: str,
    request_id: UUID | str | None,
) -> Reservation:
    """Persist the caller's selected plan/date without checking or holding availability.

    Caller owns transaction and deduplication (inbox message ownership in B1b-2).
    """
    if not plan.active:
        raise InvalidBookingPlan("El plan está inactivo.")
    if plan.event_type != event.event_type:
        raise InvalidBookingPlan("El plan no corresponde al tipo de evento.")
    if starts_at.utcoffset() is None:
        raise ValueError("La fecha requiere zona horaria.")
    if not actor or not actor.strip():
        raise ValueError("El actor es obligatorio.")
    starts_at = starts_at.astimezone(UTC)
    reservation = Reservation(
        reservation_id=uuid4(),
        lead_id=lead.lead_id,
        event_id=event.event_id,
        plan_id=plan.plan_id,
        conversation_id=conversation.id if conversation else None,
        customer_id=customer.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=plan.duration_minutes),
        price_cop=plan.price_cop,
        amount_paid_cop=0,
        status="PAYMENT_PENDING",
        calendar_status="NONE",
        hold_expires_at=None,
    )
    session.add(reservation)
    event.plan_id = plan.plan_id
    local_date = starts_at.astimezone(BOGOTA).date()
    old_date = {
        "event_id": str(event.event_id),
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "event_date_type": event.event_date_type,
        "event_month": event.event_month,
        "event_date_raw": event.event_date_raw,
    }
    date_changed = event.event_date != local_date or event.event_date_type != "EXACT"
    event.event_date = local_date
    event.event_date_type = "EXACT"
    event.event_month = None
    if date_changed:
        event.event_date_raw = None
        session.add(
            AuditEvent(
                actor=actor,
                action="EVENT_DATE_CAPTURED",
                entity="event",
                old_value=old_date,
                new_value={
                    "event_id": str(event.event_id),
                    "event_date": local_date.isoformat(),
                    "event_date_type": "EXACT",
                    "event_month": None,
                    "event_date_raw": None,
                },
                reason="Fecha seleccionada para solicitud de reserva",
                request_id=request_id,
            )
        )
    session.add(
        AuditEvent(
            actor=actor,
            action="RESERVATION_CREATED",
            entity="reservation",
            old_value=None,
            new_value={
                "reservation_id": str(reservation.reservation_id),
                "plan_code": plan.code,
                "starts_at": starts_at.isoformat(),
                "price_cop": plan.price_cop,
            },
            reason="Solicitud pendiente de pago; sin bloqueo de disponibilidad",
            request_id=request_id,
        )
    )
    await session.flush()
    from app.notifications.service import enqueue_for_reservation

    await enqueue_for_reservation(
        session,
        reservation=reservation,
        event_kind="PAYMENT_PENDING_CREATED",
        source_entity="reservation",
        source_id=str(reservation.reservation_id),
        settings=get_settings(),
        request_id=request_id,
    )
    return reservation


def deposit_amount(plan_or_price: Plan | int) -> int:
    price = plan_or_price.price_cop if isinstance(plan_or_price, Plan) else plan_or_price
    if price <= 0:
        raise ValueError("El precio debe ser positivo.")
    # Integer ceiling avoids float rounding, including prices not divisible by 1000.
    numerator = price * get_settings().booking_deposit_percent
    return ((numerator + 100_000 - 1) // 100_000) * 1000


async def attach_payment_evidence(
    session: AsyncSession,
    evidence: PaymentEvidence,
    *,
    request_id: UUID | str | None,
) -> Reservation | None:
    """Link once in the existing payment transaction; preserve human review authority."""
    if evidence.reservation_id is not None:
        return None
    reservation = await payment_reservation_candidate(
        session, evidence.customer_id, now=datetime.now(UTC), lock=True
    )
    if reservation is None:
        return None
    evidence.reservation_id = reservation.reservation_id
    if reservation.status == "PAYMENT_PENDING":
        await transition_reservation(
            session,
            reservation,
            "PAYMENT_REVIEW",
            actor="SYSTEM",
            reason="Comprobante recibido",
            request_id=str(request_id) if request_id is not None else None,
        )
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action="PAYMENT_EVIDENCE_LINKED",
            entity="payment_evidence",
            old_value={"evidence_id": evidence.id, "reservation_id": None},
            new_value={
                "evidence_id": evidence.id,
                "reservation_id": str(reservation.reservation_id),
                "customer_id": evidence.customer_id,
                "reservation_status": reservation.status,
            },
            reason="Comprobante vinculado a la reserva futura del cliente",
            request_id=request_id,
        )
    )
    from app.notifications.service import enqueue_for_reservation

    await enqueue_for_reservation(
        session,
        reservation=reservation,
        event_kind="EVIDENCE_RECEIVED",
        source_entity="payment_evidence",
        source_id=str(evidence.id),
        settings=get_settings(),
        request_id=request_id,
    )
    return reservation


async def payment_reservation_candidate(
    session: AsyncSession,
    customer_id: int,
    *,
    now: datetime,
    lock: bool = False,
) -> Reservation | None:
    """Select the newest future customer booking, with review/pending/balance priority."""
    statement = (
        select(Reservation)
        .where(
            Reservation.customer_id == customer_id,
            Reservation.starts_at > now,
            or_(
                Reservation.status.in_(("PAYMENT_REVIEW", "PAYMENT_PENDING")),
                and_(
                    Reservation.status == "RESERVED",
                    Reservation.amount_paid_cop < Reservation.price_cop,
                ),
            ),
        )
        .order_by(
            case(
                {"PAYMENT_REVIEW": 0, "PAYMENT_PENDING": 1, "RESERVED": 2},
                value=Reservation.status,
            ),
            Reservation.created_at.desc(),
            Reservation.reservation_id.desc(),
        )
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)
