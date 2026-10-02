"""Deterministic balance reminders and overdue marking; no provider I/O."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.config.settings import Settings
from app.conversation.presentation import _present_cop
from app.customer.models import Customer
from app.notifications.models import CustomerNotification
from app.notifications.service import enqueue_for_reservation
from app.notifications.staff_texts import present_start, sanitize_param
from app.plan.models import Plan
from app.reservation.models import Reservation

BOGOTA = ZoneInfo("America/Bogota")


async def audit_once(
    session: AsyncSession,
    action: str,
    reservation: Reservation,
    kind: str,
    reason: str,
    now: datetime,
    request_id: str,
) -> None:
    # The scheduler owns the reservation row lock: concurrent scans cannot duplicate skips.
    existing = await session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.action == action,
            AuditEvent.entity == "reservation",
            AuditEvent.new_value["reservation_id"].as_string() == str(reservation.reservation_id),
            AuditEvent.new_value["kind"].as_string() == kind,
        )
    )
    if existing is not None:
        return
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action=action,
            entity="reservation",
            old_value=None,
            new_value={"reservation_id": str(reservation.reservation_id), "kind": kind},
            reason=reason,
            request_id=request_id,
            created_at=now,
        )
    )


async def reserved_at(session: AsyncSession, reservation: Reservation) -> datetime:
    confirmed = await session.scalar(
        select(AuditEvent.created_at)
        .where(
            AuditEvent.action == "RESERVATION_STATUS_CHANGED",
            AuditEvent.entity == "reservation",
            AuditEvent.new_value["reservation_id"].as_string() == str(reservation.reservation_id),
            AuditEvent.new_value["status"].as_string() == "RESERVED",
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    # Imported/manual historical reservations without transition history were born reserved.
    return confirmed if confirmed is not None else reservation.created_at


async def enqueue_balance_reminders(
    sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> int:
    if not settings.balance_reminders_enabled:
        return 0
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("La fecha del programador debe incluir zona horaria")
    now = now.astimezone(UTC)
    clock = time.fromisoformat(settings.booking_reminder_time)
    request_id = str(uuid4())
    enqueued = 0
    async with sm() as session, session.begin():
        candidates = (
            await session.execute(
                select(Reservation.customer_id, Reservation.reservation_id)
                .where(
                    Reservation.status == "RESERVED",
                    Reservation.amount_paid_cop < Reservation.price_cop,
                    Reservation.starts_at > now,
                )
                .order_by(Reservation.customer_id, Reservation.reservation_id)
            )
        ).all()
        for customer_id, reservation_id in candidates:
            # Inbound locks Customer before attaching an evidence to Reservation.
            # Match that order so the notification FK cannot invert the locks.
            customer = await session.scalar(
                select(Customer).where(Customer.id == customer_id).with_for_update(skip_locked=True)
            )
            if customer is None:
                continue
            reservation = await session.scalar(
                select(Reservation)
                .where(Reservation.reservation_id == reservation_id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if (
                reservation is None
                or reservation.customer_id != customer.id
                or reservation.status != "RESERVED"
                or reservation.amount_paid_cop >= reservation.price_cop
                or reservation.starts_at <= now
            ):
                continue
            due_at = reservation.balance_due_at
            if due_at is None:
                continue
            confirmed_at = await reserved_at(session, reservation)
            schedule = (
                (
                    "BALANCE_REMINDER_EARLY",
                    reservation.starts_at.astimezone(BOGOTA).date()
                    - timedelta(days=settings.booking_reminder_days_before),
                ),
                ("BALANCE_REMINDER_DUE", due_at.astimezone(BOGOTA).date()),
            )
            for kind, day in schedule:
                scheduled_at = datetime.combine(day, clock, tzinfo=BOGOTA).astimezone(UTC)
                if now < scheduled_at:
                    continue
                if confirmed_at >= scheduled_at:
                    await audit_once(
                        session,
                        "BALANCE_REMINDER_SKIPPED_LATE",
                        reservation,
                        kind,
                        "La reserva quedó confirmada después de la hora del recordatorio",
                        now,
                        request_id,
                    )
                    continue
                if now >= due_at:
                    continue
                template = settings.customer_template_balance_reminder_name.strip()
                if not template:
                    await audit_once(
                        session,
                        "BALANCE_REMINDER_NO_TEMPLATE",
                        reservation,
                        kind,
                        "Plantilla de recordatorio al cliente sin configurar",
                        now,
                        request_id,
                    )
                    continue
                plan = await session.get(Plan, reservation.plan_id)
                first_name = (
                    customer.full_name.split()[0]
                    if customer.full_name and customer.full_name.strip()
                    else "cliente"
                )
                params = [
                    sanitize_param(value)
                    for value in (
                        first_name,
                        plan.name,
                        present_start(reservation.starts_at),
                        _present_cop(reservation.price_cop - reservation.amount_paid_cop),
                        present_start(due_at),
                    )
                ]
                notification_id = await session.scalar(
                    insert(CustomerNotification)
                    .values(
                        reservation_id=reservation.reservation_id,
                        customer_id=reservation.customer_id,
                        kind=kind,
                        phone_number=customer.phone_number,
                        params=params,
                        template_name=template,
                        next_attempt_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(constraint="uq_customer_notification_reservation_kind")
                    .returning(CustomerNotification.id)
                )
                if notification_id is not None:
                    from app.notifications.customer_worker import customer_audit

                    notification = await session.get(CustomerNotification, notification_id)
                    customer_audit(
                        session,
                        "CUSTOMER_NOTIFICATION_ENQUEUED",
                        notification,
                        request_id=request_id,
                        now=now,
                    )
                    enqueued += 1
            if now >= due_at and reservation.balance_overdue_at is None:
                reservation.balance_overdue_at = now
                session.add(
                    AuditEvent(
                        actor="SYSTEM",
                        action="RESERVATION_BALANCE_OVERDUE",
                        entity="reservation",
                        old_value={"balance_overdue_at": None},
                        new_value={
                            "reservation_id": str(reservation.reservation_id),
                            "balance_overdue_at": now.isoformat(),
                            "balance_cop": reservation.price_cop - reservation.amount_paid_cop,
                        },
                        reason="Saldo pendiente al vencer el plazo de pago",
                        request_id=request_id,
                        created_at=now,
                    )
                )
                await enqueue_for_reservation(
                    session,
                    reservation=reservation,
                    event_kind="BALANCE_OVERDUE",
                    source_entity="reservation",
                    source_id=str(reservation.reservation_id),
                    settings=settings,
                    request_id=request_id,
                )
    return enqueued
