from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy import String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.config.settings import Settings
from app.notifications.errors import OutboundSendError
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.notifications.queue import claim_batch, maintain_queue, settle_claim
from app.notifications.queue import fail as fail_notification
from app.notifications.queue import retire as retire
from app.notifications.service import staff_audit
from app.notifications.staff_texts import render_staff_text, template_for, window_until
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation


class StaffSender(Protocol):
    async def send_text(self, to: str, body: str) -> str: ...
    async def send_template(
        self, to: str, name: str, language_code: str, body_params: list[str]
    ) -> str: ...


@dataclass(frozen=True)
class StaffClaim:
    id: int
    token: UUID
    phone: str
    active: bool
    last_inbound_at: datetime | None
    event_kind: str
    params: tuple[str, ...]
    last_error_code: int | None


def fail(
    session: AsyncSession, row: StaffOutbox, error: Exception, settings: Settings, now: datetime
) -> None:
    fail_notification(
        session, row, error, settings, now, audit=staff_audit, prefix="STAFF_NOTIFICATION"
    )


def current_source_condition() -> ColumnElement[bool]:
    """MVCC source checks avoid taking business locks after the queue lock."""
    pending = (
        select(Reservation.reservation_id)
        .where(
            Reservation.reservation_id.cast(String) == StaffOutbox.source_id,
            Reservation.status == "PAYMENT_PENDING",
        )
        .correlate(StaffOutbox)
        .exists()
    )
    evidence = (
        select(PaymentEvidence.id)
        .join(Reservation, Reservation.reservation_id == PaymentEvidence.reservation_id)
        .where(
            PaymentEvidence.id.cast(String) == StaffOutbox.source_id,
            PaymentEvidence.review_status == "PENDING_REVIEW",
            PaymentEvidence.customer_id == Reservation.customer_id,
            Reservation.status.in_(("PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED")),
        )
        .correlate(StaffOutbox)
        .exists()
    )
    overdue = (
        select(Reservation.reservation_id)
        .where(
            Reservation.reservation_id.cast(String) == StaffOutbox.source_id,
            Reservation.status == "RESERVED",
            Reservation.balance_overdue_at.is_not(None),
            Reservation.amount_paid_cop < Reservation.price_cop,
        )
        .correlate(StaffOutbox)
        .exists()
    )
    return or_(
        and_(StaffOutbox.event_kind == "TEST", StaffOutbox.source_entity == "manual_test"),
        and_(
            StaffOutbox.event_kind == "PAYMENT_PENDING_CREATED",
            StaffOutbox.source_entity == "reservation",
            pending,
        ),
        and_(
            StaffOutbox.event_kind == "EVIDENCE_RECEIVED",
            StaffOutbox.source_entity == "payment_evidence",
            evidence,
        ),
        and_(
            StaffOutbox.event_kind == "BALANCE_OVERDUE",
            StaffOutbox.source_entity == "reservation",
            overdue,
        ),
    )


def supersede(session: AsyncSession, row: StaffOutbox, now: datetime) -> None:
    old_status = row.status
    retire(row, "EXPIRED", now)
    row.last_error = "El estado de origen cambió antes del envío"
    staff_audit(
        session,
        "STAFF_NOTIFICATION_SUPERSEDED",
        row,
        old_status=old_status,
        request_id=uuid4(),
    )


async def admit_current_source(
    sm: async_sessionmaker[AsyncSession], claim: StaffClaim, now: datetime
) -> bool:
    # A different claim in this batch may have been slow. Recheck each source
    # immediately before its HTTP decision, after the claim transaction committed.
    async with sm() as session, session.begin():
        result = (
            await session.execute(
                select(StaffOutbox, current_source_condition())
                .where(
                    StaffOutbox.id == claim.id,
                    StaffOutbox.status == "SENDING",
                    StaffOutbox.claim_token == claim.token,
                )
                .with_for_update(of=StaffOutbox)
            )
        ).one_or_none()
        if result is None:
            return False
        row, current = result
        if not current:
            supersede(session, row, now)
        return bool(current)


async def claim_staff_outbox_batch(
    sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> list[StaffClaim]:
    def build(values: tuple[StaffOutbox, NotificationRecipient], token: UUID) -> StaffClaim:
        row, recipient = values
        return StaffClaim(
            row.id,
            token,
            recipient.phone_number,
            recipient.active,
            recipient.last_inbound_at,
            row.event_kind,
            tuple(row.params),
            row.last_error_code,
        )

    return await claim_batch(
        sm,
        select(StaffOutbox, NotificationRecipient)
        .join(NotificationRecipient, NotificationRecipient.id == StaffOutbox.recipient_id)
        .where(StaffOutbox.status == "PENDING", StaffOutbox.next_attempt_at <= now)
        .order_by(StaffOutbox.created_at, StaffOutbox.id)
        .limit(settings.outbox_batch_size)
        .with_for_update(of=StaffOutbox, skip_locked=True),
        now,
        build,
    )


async def maintain_staff_outbox(
    sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> None:
    async with sm() as session, session.begin():
        obsolete = await session.scalars(
            select(StaffOutbox)
            .where(
                StaffOutbox.status.in_(("PENDING", "DEFERRED")),
                ~current_source_condition(),
            )
            .order_by(StaffOutbox.id)
            .with_for_update(of=StaffOutbox, skip_locked=True)
        )
        for row in obsolete:
            supersede(session, row, now)
    await maintain_queue(
        sm, StaffOutbox, settings, now, audit=staff_audit, prefix="STAFF_NOTIFICATION"
    )


async def process_staff_outbox_once(
    sm: async_sessionmaker[AsyncSession],
    sender: StaffSender,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    if not settings.staff_notifications_enabled:
        return 0
    now = now or datetime.now(UTC)
    await maintain_staff_outbox(sm, settings, now)
    claims = await claim_staff_outbox_batch(sm, settings, now)
    for claim in claims:
        if not await admit_current_source(sm, claim, now):
            continue
        template = template_for(claim.event_kind, settings)
        until = window_until(claim.last_inbound_at, settings)
        kind, state, provider_id, error = None, "SENT", None, None
        if not claim.active:
            state = "EXPIRED"
        elif until is not None and until > now and claim.last_error_code != 131047:
            kind = "TEXT"
        elif template:
            kind = "TEMPLATE"
        else:
            state = "DEFERRED"
        try:
            # All claim/maintenance sessions have exited before any provider I/O.
            if kind == "TEXT":
                provider_id = await sender.send_text(
                    claim.phone,
                    render_staff_text(claim.event_kind, list(claim.params)),
                )
            elif kind == "TEMPLATE":
                provider_id = await sender.send_template(
                    claim.phone,
                    template,
                    settings.staff_template_language,
                    list(claim.params),
                )
        except (OutboundSendError, httpx.RequestError) as caught:
            error = caught

        def update(
            row: StaffOutbox,
            *,
            message_kind: str | None = kind,
            template_name: str = template,
            delivery_state: str = state,
            message_id: str | None = provider_id,
        ) -> None:
            row.message_kind = message_kind
            row.template_name = template_name if message_kind == "TEMPLATE" else None
            if delivery_state == "SENT":
                row.provider_message_id, row.sent_at = message_id, now
                row.last_error, row.last_error_code = None, None

        await settle_claim(
            sm,
            StaffOutbox,
            claim.id,
            claim.token,
            settings,
            now,
            state=state,
            error=error,
            update=update,
            audit=staff_audit,
            prefix="STAFF_NOTIFICATION",
        )
    return len(claims)
