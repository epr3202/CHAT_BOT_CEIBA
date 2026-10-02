from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.config.settings import Settings
from app.customer.models import Customer
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.notifications.staff_texts import build_params
from app.plan.models import Plan
from app.reservation.models import Reservation


def staff_audit(
    session: AsyncSession,
    action: str,
    row: StaffOutbox,
    *,
    old_status: str | None = None,
    request_id: UUID | str | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action=action,
            entity="staff_outbox",
            old_value={"status": old_status} if old_status else None,
            new_value={
                "staff_outbox_id": row.id,
                "recipient_id": row.recipient_id,
                "event_kind": row.event_kind,
                "source": row.source(),
                "status": row.status,
            },
            reason="Aviso interno a asesor",
            request_id=request_id,
        )
    )


async def enqueue_staff_notification(
    session: AsyncSession,
    *,
    recipient_id: int,
    event_kind: str,
    source_entity: str,
    source_id: str,
    params: list[str],
    request_id: UUID | str | None,
) -> int | None:
    result = await session.scalar(
        insert(StaffOutbox)
        .values(
            recipient_id=recipient_id,
            event_kind=event_kind,
            source_entity=source_entity,
            source_id=source_id,
            params=params,
        )
        .on_conflict_do_nothing(constraint="uq_staff_outbox_source")
        .returning(StaffOutbox.id)
    )
    if result is not None:
        row = await session.get(StaffOutbox, result)
        staff_audit(session, "STAFF_NOTIFICATION_ENQUEUED", row, request_id=request_id)
    return result


async def enqueue_for_reservation(
    session: AsyncSession,
    *,
    reservation: Reservation,
    event_kind: str,
    source_entity: str,
    source_id: str,
    settings: Settings,
    request_id: UUID | str | None,
) -> None:
    if not settings.staff_notifications_enabled:
        return
    from app.reservation.booking import deposit_amount

    toggle = (
        NotificationRecipient.notify_on_evidence
        if event_kind == "EVIDENCE_RECEIVED"
        else NotificationRecipient.notify_on_payment_pending
    )
    recipients = list(
        await session.scalars(
            select(NotificationRecipient.id)
            .where(
                NotificationRecipient.active.is_(True),
                toggle.is_(True),
            )
            .order_by(NotificationRecipient.id)
        )
    )
    if not recipients:
        return
    customer = await session.get(Customer, reservation.customer_id)
    plan = await session.get(Plan, reservation.plan_id)
    params = build_params(
        customer=customer,
        plan=plan,
        starts_at=reservation.starts_at,
        deposit_cop=max(
            0,
            (
                reservation.price_cop
                if reservation.status == "RESERVED"
                else deposit_amount(reservation.price_cop)
            )
            - reservation.amount_paid_cop,
        ),
    )
    for recipient_id in recipients:
        await enqueue_staff_notification(
            session,
            recipient_id=recipient_id,
            event_kind=event_kind,
            source_entity=source_entity,
            source_id=source_id,
            params=params,
            request_id=request_id,
        )


async def intercept_staff_inbound(
    session: AsyncSession,
    *,
    phone_number: str,
    provider_timestamp: datetime | None,
    external_message_id: str,
    settings: Settings,
    request_id: UUID | str | None,
) -> bool:
    recipient = await session.scalar(
        select(NotificationRecipient)
        .where(
            NotificationRecipient.phone_number == phone_number,
            NotificationRecipient.active.is_(True),
        )
        .with_for_update()
    )
    if recipient is None:
        return False
    if (
        provider_timestamp is None
        or recipient.last_inbound_message_id == external_message_id
        or recipient.last_inbound_at is not None
        and provider_timestamp <= recipient.last_inbound_at
    ):
        return True
    recipient.last_inbound_at = provider_timestamp
    recipient.last_inbound_message_id = external_message_id
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action="STAFF_INBOUND_RECEIVED",
            entity="notification_recipient",
            old_value=None,
            new_value={
                "recipient_id": recipient.id,
                "last_inbound_at": provider_timestamp.isoformat(),
            },
            reason="Ventana de atención del asesor actualizada",
            request_id=request_id,
        )
    )
    # Use provider time to keep delayed/replayed receipts from reviving expired notices.
    now = datetime.now(UTC)
    cutoff = max(now, provider_timestamp) - timedelta(hours=settings.staff_deferred_max_age_hours)
    deferred = list(
        await session.scalars(
            select(StaffOutbox)
            .where(
                StaffOutbox.recipient_id == recipient.id,
                StaffOutbox.status == "DEFERRED",
                StaffOutbox.created_at > cutoff,
            )
            .order_by(StaffOutbox.id)
            .with_for_update()
        )
    )
    for row in deferred:
        row.status, row.next_attempt_at = "PENDING", now
        staff_audit(
            session,
            "STAFF_NOTIFICATION_REQUEUED",
            row,
            old_status="DEFERRED",
            request_id=request_id,
        )
    return True
