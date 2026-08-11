from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models_registry  # noqa: F401
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppOutboundClient
from app.config.database import create_engine, create_sessionmaker
from app.config.logging import configure_logging
from app.config.settings import get_settings

logger = structlog.get_logger(__name__)


class TextSender(Protocol):
    async def send_text(self, to: str, body: str) -> str:
        pass


def backoff_seconds(attempts: int, max_backoff_seconds: int) -> int:
    return min(2**attempts, max_backoff_seconds)


async def claim_due_outbox_batch(
    sessionmaker: async_sessionmaker[AsyncSession],
    claimed_at: datetime,
    batch_size: int,
) -> Sequence[Outbox]:
    async with sessionmaker() as session:
        async with session.begin():
            result = await session.scalars(
                select(Outbox)
                .where(
                    Outbox.status == "PENDING",
                    or_(Outbox.next_attempt_at.is_(None), Outbox.next_attempt_at <= claimed_at),
                )
                .order_by(Outbox.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            outbox_items = list(result.all())
            for outbox_item in outbox_items:
                outbox_item.status = "SENDING"
                outbox_item.claimed_at = claimed_at
        return outbox_items


async def recover_stale_sending_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    now: datetime,
    sending_timeout_seconds: int,
    max_attempts: int,
    max_backoff_seconds: int,
) -> int:
    stale_before = now - timedelta(seconds=sending_timeout_seconds)
    recovered = 0

    async with sessionmaker() as session:
        async with session.begin():
            result = await session.scalars(
                select(Outbox)
                .where(
                    Outbox.status == "SENDING",
                    Outbox.claimed_at.is_not(None),
                    Outbox.claimed_at < stale_before,
                )
                .order_by(Outbox.created_at)
                .with_for_update(skip_locked=True)
            )
            for outbox_item in result.all():
                await mark_outbox_failure(
                    session,
                    outbox_item,
                    TimeoutError("stale SENDING recovered by reaper"),
                    now,
                    max_attempts=max_attempts,
                    max_backoff_seconds=max_backoff_seconds,
                )
                recovered += 1
                logger.warning(
                    "outbox_stale_sending_recovered",
                    outbox_id=outbox_item.id,
                    attempts=outbox_item.attempts,
                    status=outbox_item.status,
                    next_attempt_at=outbox_item.next_attempt_at.isoformat()
                    if outbox_item.next_attempt_at is not None
                    else None,
                )

    return recovered


async def process_outbox_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    sender: TextSender,
    now: datetime | None = None,
    batch_size: int | None = None,
    sending_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
    max_backoff_seconds: int | None = None,
) -> int:
    settings = get_settings()
    now = now or datetime.now(UTC)
    batch_size = batch_size if batch_size is not None else settings.outbox_batch_size
    sending_timeout_seconds = (
        sending_timeout_seconds
        if sending_timeout_seconds is not None
        else settings.outbox_sending_timeout_seconds
    )
    max_attempts = max_attempts if max_attempts is not None else settings.outbox_max_attempts
    max_backoff_seconds = (
        max_backoff_seconds
        if max_backoff_seconds is not None
        else settings.outbox_max_backoff_seconds
    )
    await recover_stale_sending_outbox(
        sessionmaker,
        now=now,
        sending_timeout_seconds=sending_timeout_seconds,
        max_attempts=max_attempts,
        max_backoff_seconds=max_backoff_seconds,
    )
    outbox_items = await claim_due_outbox_batch(sessionmaker, claimed_at=now, batch_size=batch_size)

    for outbox_item in outbox_items:
        try:
            await process_claimed_outbox_item(
                sessionmaker,
                outbox_item,
                sender,
                max_attempts=max_attempts,
                max_backoff_seconds=max_backoff_seconds,
            )
        except Exception as error:
            logger.error(
                "outbox_item_processing_unhandled",
                outbox_id=outbox_item.id,
                error=str(error),
            )

    return len(outbox_items)


async def process_claimed_outbox_item(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_item: Outbox,
    sender: TextSender,
    max_attempts: int,
    max_backoff_seconds: int,
) -> None:
    try:
        body = extract_text_body(outbox_item)
        sent_at = datetime.now(UTC)
        provider_message_id = await sender.send_text(outbox_item.recipient_phone_number, body)
    except Exception as error:
        await settle_outbox_failure(
            sessionmaker,
            outbox_item.id,
            error,
            datetime.now(UTC),
            max_attempts=max_attempts,
            max_backoff_seconds=max_backoff_seconds,
        )
        return

    await settle_outbox_success(
        sessionmaker,
        outbox_id=outbox_item.id,
        body=body,
        provider_message_id=provider_message_id,
        sent_at=sent_at,
        max_attempts=max_attempts,
        max_backoff_seconds=max_backoff_seconds,
    )


async def settle_outbox_success(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_id: int,
    body: str,
    provider_message_id: str,
    sent_at: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            outbox_item = await session.get(Outbox, outbox_id, with_for_update=True)
            if outbox_item is None:
                logger.warning("outbox_missing_during_success_settle", outbox_id=outbox_id)
                return

            inbound_message = await session.get(Message, outbox_item.message_id)
            if inbound_message is None:
                await mark_outbox_failure(
                    session,
                    outbox_item,
                    RuntimeError(f"Input message {outbox_item.message_id} does not exist"),
                    sent_at,
                    max_attempts=max_attempts,
                    max_backoff_seconds=max_backoff_seconds,
                )
                return

            outbox_item.status = "SENT"
            outbox_item.sent_at = sent_at
            outbox_item.claimed_at = None
            outbox_item.next_attempt_at = None
            outbox_item.last_error = None

            existing_outbound_message = await session.scalar(
                select(Message).where(Message.external_message_id == provider_message_id)
            )
            if existing_outbound_message is None:
                session.add(
                    Message(
                        external_message_id=provider_message_id,
                        conversation_id=outbox_item.conversation_id,
                        customer_id=inbound_message.customer_id,
                        channel=outbox_item.channel,
                        direction="OUTBOUND",
                        message_type="text",
                        content={"text": {"body": body}},
                        provider_timestamp=None,
                    )
                )


async def settle_outbox_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_id: int,
    error: Exception,
    failed_at: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            outbox_item = await session.get(Outbox, outbox_id, with_for_update=True)
            if outbox_item is None:
                logger.warning("outbox_missing_during_failure_settle", outbox_id=outbox_id)
                return
            await mark_outbox_failure(
                session,
                outbox_item,
                error,
                failed_at,
                max_attempts=max_attempts,
                max_backoff_seconds=max_backoff_seconds,
            )


async def mark_outbox_failure(
    session: AsyncSession,
    outbox_item: Outbox,
    error: Exception,
    now: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
) -> None:
    outbox_item.attempts += 1
    outbox_item.last_error = str(error)[:1000]
    outbox_item.claimed_at = None

    if outbox_item.attempts >= max_attempts:
        outbox_item.status = "FAILED"
        outbox_item.next_attempt_at = None
        session.add(
            AuditEvent(
                actor="INTEGRATION",
                action="WHATSAPP_OUTBOX_SEND_FAILED",
                entity="outbox",
                old_value=None,
                new_value={
                    "outbox_id": outbox_item.id,
                    "attempts": outbox_item.attempts,
                    "status": outbox_item.status,
                },
                reason=outbox_item.last_error or "Unknown outbound send error",
                request_id=None,
            )
        )
    else:
        outbox_item.status = "PENDING"
        outbox_item.next_attempt_at = now + timedelta(
            seconds=backoff_seconds(outbox_item.attempts, max_backoff_seconds)
        )

    logger.info(
        "outbox_send_failed",
        outbox_id=outbox_item.id,
        attempts=outbox_item.attempts,
        status=outbox_item.status,
        next_attempt_at=outbox_item.next_attempt_at.isoformat()
        if outbox_item.next_attempt_at is not None
        else None,
        failed_at=now.isoformat(),
    )


def extract_text_body(outbox_item: Outbox) -> str:
    text = outbox_item.payload.get("text")
    if isinstance(text, dict):
        body = text.get("body")
        if isinstance(body, str):
            return body
    raise ValueError(f"Outbox {outbox_item.id} does not contain text.body")


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.environment, settings.log_level)
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    sessionmaker = create_sessionmaker(engine)

    async with WhatsAppOutboundClient(settings) as sender:
        try:
            while True:
                # At-least-once semantics: a crash after Meta accepts the HTTP send
                # but before settle commits may resend. For the MVP this is preferred
                # over losing an outbound message silently.
                processed = await process_outbox_once(
                    sessionmaker,
                    sender,
                    batch_size=settings.outbox_batch_size,
                    sending_timeout_seconds=settings.outbox_sending_timeout_seconds,
                    max_attempts=settings.outbox_max_attempts,
                    max_backoff_seconds=settings.outbox_max_backoff_seconds,
                )
                logger.info("outbox_poll_completed", processed=processed)
                await asyncio.sleep(settings.outbox_poll_interval_seconds)
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
