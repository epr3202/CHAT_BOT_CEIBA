"""Human settlement in a local transaction; Calendar effects after its commit."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.audit.models import AuditEvent
from app.calendar.adapter import (
    AlreadyExistsError,
    CalendarAdapter,
    CalendarUnavailableError,
    EventNotFoundError,
)
from app.config.settings import Settings, get_settings
from app.customer.models import Customer
from app.payment.models import PaymentEvidence, PaymentEvidenceReview
from app.plan.models import Plan
from app.reservation.availability import BookingBlocker, evaluate_booking_availability
from app.reservation.booking import deposit_amount
from app.reservation.models import Reservation
from app.reservation.service import transition_reservation

SessionMaker = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class SettlementResult:
    kind: Literal["RESERVED", "PARTIAL", "CONFLICT", "NO_RESERVATION"]
    reservation: Reservation | None
    missing_cop: int = 0
    blockers: list[BookingBlocker] | None = None


async def lock_booking_changes(session: AsyncSession) -> None:
    # Serialize acceptance/rescheduling across different rows. SELECT FOR UPDATE
    # of overlaps alone cannot lock an empty range under READ COMMITTED.
    await session.execute(text("SELECT pg_advisory_xact_lock(20260930, 30)"))


def payment_audit(
    session: AsyncSession,
    evidence: PaymentEvidence,
    *,
    actor: str,
    note: str | None,
    request_id: str,
    amount_cop: int | None = None,
    review: PaymentEvidenceReview | None = None,
) -> None:
    proposal = (
        {}
        if review is None
        else {
            "review_id": str(review.review_id),
            "suggested_amount_cop": review.suggested_amount_cop,
            "amount_differs_from_suggestion": amount_cop != review.suggested_amount_cop,
        }
    )
    reason = (
        ("aceptado con propuesta de IA" if review else "aceptado manual")
        if evidence.review_status == "ACCEPTED"
        else (note or "Comprobante rechazado por asesor")
    )
    if note and evidence.review_status == "ACCEPTED":
        reason = f"{reason}: {note}"[:255]
    session.add(
        AuditEvent(
            actor=actor,
            action=f"PAYMENT_EVIDENCE_{evidence.review_status}",
            entity="payment_evidence",
            old_value={"evidence_id": evidence.id, "review_status": "PENDING_REVIEW"},
            new_value={
                "evidence_id": evidence.id,
                "review_status": evidence.review_status,
                "amount_cop": amount_cop,
                "note": note,
                **proposal,
            },
            reason=reason,
            request_id=request_id,
        )
    )


async def accept_payment(
    session: AsyncSession,
    *,
    evidence: PaymentEvidence,
    amount_cop: int,
    actor: str,
    note: str | None,
    request_id: str,
    calendar_blockers: list[BookingBlocker],
    review: PaymentEvidenceReview | None = None,
) -> SettlementResult:
    if type(amount_cop) is not int or amount_cop <= 0:
        raise ValueError("El monto debe ser un entero positivo.")
    if not actor or not actor.strip():
        raise ValueError("El actor es obligatorio.")
    # The caller locks evidence too; guard repeated direct service calls.
    if evidence.review_status != "PENDING_REVIEW":
        raise ValueError("El comprobante ya fue revisado.")
    if evidence.download_status == "FAILED_PERMANENT":
        raise ValueError("La descarga del comprobante falló. Solicita una nueva imagen.")
    if review is not None and (review.evidence_id != evidence.id or review.status != "COMPLETED"):
        raise ValueError("La propuesta no corresponde a este comprobante.")
    reservation = None
    if evidence.reservation_id is not None:
        await lock_booking_changes(session)
        reservation = await session.scalar(
            select(Reservation)
            .where(
                Reservation.reservation_id == evidence.reservation_id,
            )
            .with_for_update()
        )
        if reservation is None or reservation.status != "PAYMENT_REVIEW":
            raise ValueError("La reserva no está pendiente de revisión de pago.")
    evidence.review_status = "ACCEPTED"
    evidence.amount_cop = amount_cop
    evidence.reviewed_at = datetime.now(UTC)
    evidence.review_note = note
    payment_audit(
        session,
        evidence,
        actor=actor,
        note=note,
        request_id=request_id,
        amount_cop=amount_cop,
        review=review,
    )
    if reservation is None:
        return SettlementResult("NO_RESERVATION", None, blockers=[])
    plan = await session.get(Plan, reservation.plan_id)
    old_paid = reservation.amount_paid_cop
    reservation.amount_paid_cop += amount_cop
    missing = max(0, deposit_amount(reservation.price_cop) - reservation.amount_paid_cop)
    blockers = []
    if missing:
        await transition_reservation(
            session,
            reservation,
            "PAYMENT_PENDING",
            actor=actor,
            reason="Abono parcial registrado",
            request_id=request_id,
        )
        kind = "PARTIAL"
    else:
        fresh = list(
            await session.scalars(
                select(Reservation)
                .options(
                    joinedload(Reservation.plan),
                )
                .where(
                    Reservation.status == "RESERVED",
                    Reservation.starts_at < reservation.ends_at,
                    Reservation.ends_at > reservation.starts_at,
                )
            )
        )
        availability = evaluate_booking_availability(
            plan=plan,
            starts_at=reservation.starts_at,
            ends_at=reservation.ends_at,
            reservations=fresh,
            calendar_events=[],
            exclusivity_keyword=get_settings().booking_exclusivity_keyword,
        )
        blockers = availability.blockers + calendar_blockers
        kind = "CONFLICT" if blockers else "RESERVED"
        if not blockers:
            await transition_reservation(
                session,
                reservation,
                "RESERVED",
                actor=actor,
                reason="Pago humano aceptado; anticipo completo",
                request_id=request_id,
            )
            full = reservation.amount_paid_cop >= reservation.price_cop
            reservation.payment_kind = "FULL" if full else "DEPOSIT"
            reservation.balance_due_at = None if full else reservation.starts_at - timedelta(days=1)
    session.add(
        AuditEvent(
            actor=actor,
            action=f"RESERVATION_PAYMENT_{kind}",
            entity="reservation",
            old_value={
                "reservation_id": str(reservation.reservation_id),
                "amount_paid_cop": old_paid,
            },
            new_value={
                "reservation_id": str(reservation.reservation_id),
                "amount_paid_cop": reservation.amount_paid_cop,
                "missing_cop": missing,
                "blockers": [{"kind": b.kind, "ref": b.ref} for b in blockers],
            },
            reason=note or "Aceptación humana de comprobante",
            request_id=request_id,
        )
    )
    return SettlementResult(kind, reservation, missing, blockers)


async def reject_payment(
    session: AsyncSession,
    *,
    evidence: PaymentEvidence,
    actor: str,
    note: str,
    request_id: str,
) -> Reservation | None:
    if not actor.strip() or not note.strip():
        raise ValueError("El actor y el motivo son obligatorios.")
    if evidence.review_status != "PENDING_REVIEW":
        raise ValueError("El comprobante ya fue revisado.")
    evidence.review_status = "REJECTED"
    evidence.reviewed_at = datetime.now(UTC)
    evidence.review_note = note
    payment_audit(session, evidence, actor=actor, note=note, request_id=request_id)
    reservation = None
    if evidence.reservation_id:
        reservation = await session.get(Reservation, evidence.reservation_id, with_for_update=True)
        if reservation is not None and reservation.status == "PAYMENT_REVIEW":
            await transition_reservation(
                session,
                reservation,
                "PAYMENT_PENDING",
                actor=actor,
                reason=note,
                request_id=request_id,
            )
    return reservation


async def sync_reservation_calendar(
    reservation_id: UUID,
    *,
    calendar: CalendarAdapter,
    sessionmaker: SessionMaker,
    settings: Settings,
) -> None:
    async with sessionmaker() as session, session.begin():
        reservation = await session.get(Reservation, reservation_id)
        if reservation is None or reservation.status != "RESERVED":
            raise ValueError("Solo se sincronizan reservas confirmadas.")
        plan = await session.get(Plan, reservation.plan_id)
        customer = await session.get(Customer, reservation.customer_id)
        start, end = reservation.starts_at, reservation.ends_at
        existing = reservation.external_calendar_id
        summary = f"{plan.name} — {customer.full_name or customer.phone_number}"
        if plan.exclusive:
            summary += f" — {settings.booking_exclusivity_keyword}"
        description = (
            f"Plan: {plan.name}\nPrecio: {reservation.price_cop}\n"
            f"Pagado: {reservation.amount_paid_cop}\nTeléfono: {customer.phone_number}\n"
            f"reservation_id: {reservation_id}"
        )
    event_id = reservation_id.hex
    try:
        if existing:
            try:
                await calendar.update_event(event_id, summary, start, end, description=description)
            except EventNotFoundError:
                await calendar.create_event(event_id, summary, start, end, description=description)
        else:
            try:
                await calendar.create_event(event_id, summary, start, end, description=description)
            except AlreadyExistsError:
                current = await calendar.get_event(event_id)
                if (current.summary, current.start, current.end, current.description) != (
                    summary,
                    start,
                    end,
                    description,
                ):
                    await calendar.update_event(
                        event_id, summary, start, end, description=description
                    )
    except CalendarUnavailableError:
        async with sessionmaker() as session, session.begin():
            row = await session.get(Reservation, reservation_id, with_for_update=True)
            row.calendar_status = "NONE"
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="CALENDAR_EVENT_SYNC_FAILED",
                    entity="reservation",
                    old_value={"reservation_id": str(reservation_id)},
                    new_value={"calendar_status": "NONE"},
                    reason="No se pudo sincronizar Calendar",
                    request_id=str(uuid4()),
                )
            )
        raise
    async with sessionmaker() as session, session.begin():
        row = await session.get(Reservation, reservation_id, with_for_update=True)
        superseded = row.status != "RESERVED" or (row.starts_at, row.ends_at) != (start, end)
        if not superseded:
            row.external_calendar_id = event_id
            row.calendar_status = "CONFIRMED"
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="CALENDAR_EVENT_CREATED",
                    entity="reservation",
                    old_value={
                        "reservation_id": str(reservation_id),
                        "external_calendar_id": existing,
                    },
                    new_value={
                        "reservation_id": str(reservation_id),
                        "external_calendar_id": event_id,
                        "calendar_status": "CONFIRMED",
                    },
                    reason="Evento definitivo de reserva sincronizado",
                    request_id=str(uuid4()),
                )
            )
    if superseded:
        # A concurrent cancellation must not leave an orphan after creation.
        if row.status == "CANCELLED":
            await release_reservation_calendar(
                reservation_id, calendar=calendar, sessionmaker=sessionmaker, settings=settings
            )
        raise CalendarUnavailableError("La reserva cambió durante la sincronización.")


async def release_reservation_calendar(
    reservation_id: UUID,
    *,
    calendar: CalendarAdapter,
    sessionmaker: SessionMaker,
    settings: Settings,
) -> None:
    try:
        await calendar.delete_event(reservation_id.hex)
    except EventNotFoundError:
        pass
    async with sessionmaker() as session, session.begin():
        row = await session.get(Reservation, reservation_id, with_for_update=True)
        old_id = row.external_calendar_id
        row.external_calendar_id = None
        row.calendar_status = "NONE"
        session.add(
            AuditEvent(
                actor="SYSTEM",
                action="CALENDAR_EVENT_DELETED",
                entity="reservation",
                old_value={"reservation_id": str(reservation_id), "external_calendar_id": old_id},
                new_value={
                    "reservation_id": str(reservation_id),
                    "external_calendar_id": None,
                    "calendar_status": "NONE",
                },
                reason="Evento definitivo liberado",
                request_id=str(uuid4()),
            )
        )


async def expire_pending_reservations(sessionmaker: SessionMaker, now: datetime) -> int:
    if now.utcoffset() is None:
        raise ValueError("La fecha requiere zona horaria.")
    async with sessionmaker() as session, session.begin():
        rows = list(
            await session.scalars(
                select(Reservation)
                .where(
                    Reservation.status == "PAYMENT_PENDING",
                    Reservation.starts_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            await transition_reservation(
                session,
                row,
                "EXPIRED",
                actor="SYSTEM",
                reason="Fecha vencida sin pago",
                request_id=str(uuid4()),
            )
    return len(rows)
