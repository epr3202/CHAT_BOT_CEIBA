"""Scheduled customer templates share staff queue mechanics without conversation admission."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.config.settings import Settings
from app.notifications.errors import OutboundSendError
from app.notifications.models import CustomerNotification
from app.notifications.queue import claim_batch, maintain_queue, settle_claim
from app.notifications.staff_texts import sanitize_param
from app.notifications.worker import StaffSender
from app.reservation.models import Reservation


def customer_audit(
    session: AsyncSession,
    action: str,
    row: CustomerNotification,
    *,
    old_status: str | None = None,
    request_id: UUID | str | None = None,
    now: datetime | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action=action,
            entity="customer_notification",
            old_value={"status": old_status} if old_status else None,
            new_value={
                "customer_notification_id": row.id,
                "reservation_id": str(row.reservation_id),
                "customer_id": row.customer_id,
                "kind": row.kind,
                "status": row.status,
            },
            reason="Recordatorio programado de saldo al cliente",
            request_id=request_id or str(uuid4()),
            created_at=now or datetime.now(UTC),
        )
    )


@dataclass(frozen=True)
class CustomerClaim:
    id: int
    token: UUID
    phone_number: str
    template_name: str
    params: tuple[str, ...]


async def process_customer_notifications_once(
    sm: async_sessionmaker[AsyncSession],
    sender: StaffSender,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    if not settings.balance_reminders_enabled:
        return 0
    now = now or datetime.now(UTC)
    await maintain_queue(
        sm,
        CustomerNotification,
        settings,
        now,
        audit=customer_audit,
        prefix="CUSTOMER_NOTIFICATION",
    )

    def build(values: tuple[CustomerNotification, Reservation], token: UUID) -> CustomerClaim:
        row, _ = values
        return CustomerClaim(row.id, token, row.phone_number, row.template_name, tuple(row.params))

    def admissible(values: tuple[CustomerNotification, Reservation]) -> bool:
        row, reservation = values
        return (
            reservation.status == "RESERVED"
            and reservation.amount_paid_cop < reservation.price_cop
            and reservation.starts_at > now
            and bool(row.template_name.strip())
        )

    claims = await claim_batch(
        sm,
        select(CustomerNotification, Reservation)
        .join(Reservation, Reservation.reservation_id == CustomerNotification.reservation_id)
        .where(
            CustomerNotification.status == "PENDING", CustomerNotification.next_attempt_at <= now
        )
        .order_by(CustomerNotification.created_at, CustomerNotification.id)
        .limit(settings.outbox_batch_size)
        .with_for_update(of=(CustomerNotification, Reservation), skip_locked=True),
        now,
        build,
        admissible=admissible,
        audit=customer_audit,
        prefix="CUSTOMER_NOTIFICATION",
    )
    for claim in claims:
        error, provider_id = None, None
        # Parameter shape is validated before HTTP; no free-form text is rendered.
        if len(claim.params) != 5 or any(
            not isinstance(param, str) or sanitize_param(param) != param for param in claim.params
        ):
            error = OutboundSendError("Parámetros del recordatorio inválidos", retryable=False)
        else:
            try:
                provider_id = await sender.send_template(
                    claim.phone_number,
                    claim.template_name,
                    "es",
                    list(claim.params),
                )
            except (OutboundSendError, httpx.RequestError) as caught:
                error = caught

        def update(row: Any, *, message_id: str | None = provider_id) -> None:
            row.provider_message_id, row.sent_at = message_id, now
            row.last_error, row.last_error_code = None, None

        await settle_claim(
            sm,
            CustomerNotification,
            claim.id,
            claim.token,
            settings,
            now,
            state="SENT",
            error=error,
            update=update,
            audit=customer_audit,
            prefix="CUSTOMER_NOTIFICATION",
        )
    return len(claims)
