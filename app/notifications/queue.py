"""Shared claim, recovery and settlement for scheduled notification tables."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channel.worker import backoff_seconds
from app.config.settings import Settings
from app.notifications.errors import OutboundSendError


class NotificationRow(Protocol):
    id: int
    status: str
    attempts: int
    next_attempt_at: datetime
    claim_token: UUID | None
    claimed_at: datetime | None
    last_error: str | None
    last_error_code: int | None
    updated_at: datetime


Audit = Callable[..., None]


def retire(row: NotificationRow, state: str, now: datetime) -> None:
    row.status, row.claim_token, row.claimed_at = state, None, None
    row.updated_at = now


def fail(
    session: AsyncSession,
    row: NotificationRow,
    error: Exception,
    settings: Settings,
    now: datetime,
    *,
    audit: Audit,
    prefix: str,
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
        seconds=backoff_seconds(row.attempts, settings.outbox_max_backoff_seconds)
    )
    audit(session, f"{prefix}_FAILED", row, old_status=old)


async def claim_batch[Claim](
    sm: async_sessionmaker[AsyncSession],
    statement: Any,
    now: datetime,
    build_claim: Callable[[Any, UUID], Claim],
    *,
    admissible: Callable[[Any], bool] | None = None,
    audit: Audit | None = None,
    prefix: str = "",
) -> list[Claim]:
    """The caller supplies the table-specific query and immutable delivery snapshot."""
    claims = []
    async with sm() as session, session.begin():
        for values in (await session.execute(statement)).all():
            row = values[0]
            if admissible is not None and not admissible(values):
                retire(row, "EXPIRED", now)
                if audit is not None:
                    audit(session, f"{prefix}_EXPIRED", row, old_status="PENDING")
                continue
            token = uuid4()
            row.status, row.claim_token, row.claimed_at = "SENDING", token, now
            claims.append(build_claim(values, token))
    return claims


async def maintain_queue(
    sm: async_sessionmaker[AsyncSession],
    model: Any,
    settings: Settings,
    now: datetime,
    *,
    audit: Audit,
    prefix: str,
) -> None:
    stale = now - timedelta(seconds=settings.outbox_sending_timeout_seconds)
    cutoff = now - timedelta(hours=settings.staff_deferred_max_age_hours)
    async with sm() as session, session.begin():
        candidates = await session.scalars(
            select(model)
            .where(
                or_(
                    and_(model.status == "DEFERRED", model.created_at < cutoff),
                    and_(
                        model.status == "SENDING",
                        or_(
                            model.claimed_at < stale,
                            and_(model.claimed_at.is_(None), model.created_at < stale),
                        ),
                    ),
                )
            )
            .order_by(model.id)
            .with_for_update(skip_locked=True)
        )
        for row in candidates:
            if row.status == "DEFERRED":
                retire(row, "EXPIRED", now)
                audit(session, f"{prefix}_EXPIRED", row, old_status="DEFERRED")
            else:
                fail(
                    session,
                    row,
                    TimeoutError("Envío atascado recuperado"),
                    settings,
                    now,
                    audit=audit,
                    prefix=prefix,
                )


async def settle_claim(
    sm: async_sessionmaker[AsyncSession],
    model: Any,
    notification_id: int,
    token: UUID,
    settings: Settings,
    now: datetime,
    *,
    state: str,
    error: Exception | None,
    update: Callable[[Any], None],
    audit: Audit,
    prefix: str,
) -> None:
    async with sm() as session, session.begin():
        row = await session.get(model, notification_id, with_for_update=True)
        if row is None or row.status != "SENDING" or row.claim_token != token:
            return
        if error is not None:
            fail(session, row, error, settings, now, audit=audit, prefix=prefix)
            return
        retire(row, state, now)
        update(row)
        audit(session, f"{prefix}_{state}", row, old_status="SENDING")
