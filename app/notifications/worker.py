from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channel.worker import backoff_seconds
from app.config.settings import Settings
from app.notifications.errors import OutboundSendError
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.notifications.service import staff_audit
from app.notifications.staff_texts import render_staff_text, template_for, window_until


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


def retire(row: StaffOutbox, state: str, now: datetime) -> None:
    row.status, row.claim_token, row.claimed_at = state, None, None
    row.updated_at = now


def fail(
    session: AsyncSession, row: StaffOutbox, error: Exception, settings: Settings, now: datetime
) -> None:
    old = row.status
    row.attempts += 1
    row.last_error = str(error)[:4000]
    row.last_error_code = getattr(error, "code", None)
    permanent = isinstance(error, OutboundSendError) and not error.retryable
    retire(
        row,
        "FAILED" if permanent or row.attempts >= settings.staff_outbox_max_attempts else "PENDING",
        now,
    )
    row.next_attempt_at = now + timedelta(
        seconds=backoff_seconds(
            row.attempts,
            settings.outbox_max_backoff_seconds,
        )
    )
    staff_audit(session, "STAFF_NOTIFICATION_FAILED", row, old_status=old)


async def claim_staff_outbox_batch(
    sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> list[StaffClaim]:
    async with sm() as session, session.begin():
        rows = list(
            (
                await session.execute(
                    select(StaffOutbox, NotificationRecipient)
                    .join(
                        NotificationRecipient,
                        NotificationRecipient.id == StaffOutbox.recipient_id,
                    )
                    .where(StaffOutbox.status == "PENDING", StaffOutbox.next_attempt_at <= now)
                    .order_by(StaffOutbox.created_at, StaffOutbox.id)
                    .limit(settings.outbox_batch_size)
                    .with_for_update(of=StaffOutbox, skip_locked=True)
                )
            ).all()
        )
        claims = []
        for row, recipient in rows:
            row.status, row.claim_token, row.claimed_at = "SENDING", uuid4(), now
            claims.append(
                StaffClaim(
                    row.id,
                    row.claim_token,
                    recipient.phone_number,
                    recipient.active,
                    recipient.last_inbound_at,
                    row.event_kind,
                    tuple(row.params),
                    row.last_error_code,
                )
            )
    return claims


async def maintain_staff_outbox(
    sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> None:
    stale = now - timedelta(seconds=settings.outbox_sending_timeout_seconds)
    cutoff = now - timedelta(hours=settings.staff_deferred_max_age_hours)
    async with sm() as session, session.begin():
        candidates = list(
            await session.scalars(
                select(StaffOutbox)
                .where(
                    or_(
                        and_(StaffOutbox.status == "DEFERRED", StaffOutbox.created_at < cutoff),
                        and_(
                            StaffOutbox.status == "SENDING",
                            or_(
                                StaffOutbox.claimed_at < stale,
                                and_(
                                    StaffOutbox.claimed_at.is_(None), StaffOutbox.created_at < stale
                                ),
                            ),
                        ),
                    )
                )
                .order_by(StaffOutbox.id)
                .with_for_update(skip_locked=True)
            )
        )
        for row in candidates:
            if row.status == "DEFERRED":
                retire(row, "EXPIRED", now)
                staff_audit(session, "STAFF_NOTIFICATION_EXPIRED", row, old_status="DEFERRED")
            else:
                fail(session, row, TimeoutError("Envío atascado recuperado"), settings, now)


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
        async with sm() as session, session.begin():
            row = await session.get(StaffOutbox, claim.id, with_for_update=True)
            if row is None or row.status != "SENDING" or row.claim_token != claim.token:
                continue
            if error is not None:
                fail(session, row, error, settings, now)
                continue
            retire(row, state, now)
            row.message_kind = kind
            row.template_name = template if kind == "TEMPLATE" else None
            if state == "SENT":
                row.provider_message_id, row.sent_at = provider_id, now
                row.last_error, row.last_error_code = None, None
            staff_audit(session, f"STAFF_NOTIFICATION_{state}", row, old_status="SENDING")
    return len(claims)
