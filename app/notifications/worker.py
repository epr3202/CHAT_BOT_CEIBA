from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.notifications.errors import OutboundSendError
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.notifications.queue import claim_batch, maintain_queue, settle_claim
from app.notifications.queue import fail as fail_notification
from app.notifications.queue import retire as retire
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


def fail(
    session: AsyncSession, row: StaffOutbox, error: Exception, settings: Settings, now: datetime
) -> None:
    fail_notification(
        session, row, error, settings, now, audit=staff_audit, prefix="STAFF_NOTIFICATION"
    )


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
