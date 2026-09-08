from __future__ import annotations

import asyncio
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models_registry  # noqa: F401
from app.audit.models import AuditEvent
from app.channel.media import MediaService, PermanentCatalogMediaError
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppInvalidMediaError, WhatsAppOutboundClient
from app.config.database import create_engine, create_sessionmaker
from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)


SettlementOutcome = Literal["APPLIED", "DISCARDED"]


@dataclass(frozen=True)
class OutboxClaim:
    """Detached acquisition snapshot. Never refresh its identity from the row."""

    id: int
    claim_token: UUID
    recipient_phone_number: str
    message_kind: str
    payload: dict[str, Any]
    catalog_asset_id: UUID | None


class OutboundSender(Protocol):
    async def send_text(self, to: str, body: str) -> str:
        pass

    async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
        pass


def backoff_seconds(attempts: int, max_backoff_seconds: int) -> int:
    return min(2**attempts, max_backoff_seconds)


async def claim_due_outbox_batch(
    sessionmaker: async_sessionmaker[AsyncSession],
    claimed_at: datetime,
    batch_size: int,
) -> Sequence[OutboxClaim]:
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
            claims = []
            for outbox_item in outbox_items:
                outbox_item.status = "SENDING"
                outbox_item.claimed_at = claimed_at
                outbox_item.claim_token = uuid4()
                claims.append(
                    OutboxClaim(
                        id=outbox_item.id,
                        claim_token=outbox_item.claim_token,
                        recipient_phone_number=outbox_item.recipient_phone_number,
                        message_kind=outbox_item.message_kind,
                        payload=deepcopy(outbox_item.payload),
                        catalog_asset_id=outbox_item.catalog_asset_id,
                    )
                )
        return claims


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
                    or_(
                        Outbox.claimed_at < stale_before,
                        and_(
                            Outbox.claim_token.is_(None),
                            Outbox.claimed_at.is_(None),
                            Outbox.created_at < stale_before,
                        ),
                    ),
                )
                .order_by(Outbox.created_at)
                .with_for_update(skip_locked=True)
            )
            for outbox_item in result.all():
                await _mark_outbox_failure_locked(
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
    sender: OutboundSender,
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
    outbox_item: OutboxClaim,
    sender: OutboundSender,
    max_attempts: int,
    max_backoff_seconds: int,
) -> SettlementOutcome:
    try:
        if outbox_item.message_kind == "DOCUMENT":
            return await process_claimed_document_outbox_item(
                sessionmaker,
                outbox_item,
                sender,
                max_attempts=max_attempts,
                max_backoff_seconds=max_backoff_seconds,
            )
        body = extract_text_body(outbox_item)
        sent_at = datetime.now(UTC)
        provider_message_id = await sender.send_text(outbox_item.recipient_phone_number, body)
    except Exception as error:
        return await settle_outbox_failure(
            sessionmaker,
            outbox_item.id,
            error,
            datetime.now(UTC),
            claim_token=outbox_item.claim_token,
            max_attempts=max_attempts,
            max_backoff_seconds=max_backoff_seconds,
        )

    return await settle_outbox_success(
        sessionmaker,
        outbox_id=outbox_item.id,
        claim_token=outbox_item.claim_token,
        body=body,
        provider_message_id=provider_message_id,
        sent_at=sent_at,
        max_attempts=max_attempts,
        max_backoff_seconds=max_backoff_seconds,
    )


async def process_claimed_document_outbox_item(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_item: OutboxClaim,
    sender: OutboundSender,
    max_attempts: int,
    max_backoff_seconds: int,
) -> SettlementOutcome:
    media_service = MediaService(sessionmaker, get_settings(), sender)
    try:
        caption = extract_document_caption(outbox_item)
        asset_id = document_catalog_asset_id(outbox_item)
        document = await media_service.resolve_document(asset_id)
        sent_at = datetime.now(UTC)
        try:
            provider_message_id = await sender.send_document(
                outbox_item.recipient_phone_number,
                document.media_id,
                document.filename,
                caption,
            )
        except WhatsAppInvalidMediaError:
            await media_service.invalidate_media_cache(
                asset_id,
                "Meta rejected cached media_id during document send",
            )
            document = await media_service.resolve_document(asset_id)
            provider_message_id = await sender.send_document(
                outbox_item.recipient_phone_number,
                document.media_id,
                document.filename,
                caption,
            )
            sent_at = datetime.now(UTC)
    except PermanentCatalogMediaError as error:
        return await settle_outbox_failure(
            sessionmaker,
            outbox_item.id,
            error,
            datetime.now(UTC),
            claim_token=outbox_item.claim_token,
            max_attempts=max_attempts,
            max_backoff_seconds=max_backoff_seconds,
            permanent=True,
        )
    except Exception as error:
        return await settle_outbox_failure(
            sessionmaker,
            outbox_item.id,
            error,
            datetime.now(UTC),
            claim_token=outbox_item.claim_token,
            max_attempts=max_attempts,
            max_backoff_seconds=max_backoff_seconds,
        )

    return await settle_outbox_success(
        sessionmaker,
        outbox_id=outbox_item.id,
        claim_token=outbox_item.claim_token,
        body=caption,
        provider_message_id=provider_message_id,
        sent_at=sent_at,
        max_attempts=max_attempts,
        max_backoff_seconds=max_backoff_seconds,
        message_type="document",
        content={
            "document": {
                "catalog_asset_id": str(asset_id),
                "filename": document.filename,
                "caption": caption,
            }
        },
    )


async def _lock_owned_outbox(
    session: AsyncSession,
    outbox_id: int,
    claim_token: UUID,
    outcome: str,
) -> Outbox | None:
    """Ownership check and subsequent effects share the caller's transaction/row lock."""
    row = await session.get(Outbox, outbox_id, with_for_update=True)
    reason = (
        "missing"
        if row is None
        else "invalid_identity"
        if not isinstance(claim_token, UUID)
        else "not_sending"
        if row.status != "SENDING"
        else "identity_mismatch"
        if row.claim_token != claim_token
        else None
    )
    if reason is not None:
        logger.info("outbox_result_discarded", outbox_id=outbox_id, outcome=outcome, reason=reason)
        return None
    return row


async def settle_outbox_success(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_id: int,
    body: str,
    provider_message_id: str,
    sent_at: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
    message_type: str = "text",
    content: dict[str, object] | None = None,
    *,
    claim_token: UUID,
) -> SettlementOutcome:
    async with sessionmaker() as session:
        async with session.begin():
            outbox_item = await _lock_owned_outbox(session, outbox_id, claim_token, "success")
            if outbox_item is None:
                return "DISCARDED"

            inbound_message = await session.get(Message, outbox_item.message_id)
            if inbound_message is None:
                await _mark_outbox_failure_locked(
                    session,
                    outbox_item,
                    RuntimeError(f"Input message {outbox_item.message_id} does not exist"),
                    sent_at,
                    max_attempts=max_attempts,
                    max_backoff_seconds=max_backoff_seconds,
                )
                return "APPLIED"

            outbox_item.status = "SENT"
            outbox_item.claim_token = None
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
                        message_type=message_type,
                        content=content or {"text": {"body": body}},
                        provider_timestamp=None,
                    )
                )

    return "APPLIED"


async def settle_outbox_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox_id: int,
    error: Exception,
    failed_at: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
    permanent: bool = False,
    *,
    claim_token: UUID,
) -> SettlementOutcome:
    async with sessionmaker() as session:
        async with session.begin():
            outbox_item = await _lock_owned_outbox(session, outbox_id, claim_token, "failure")
            if outbox_item is None:
                return "DISCARDED"
            await _mark_outbox_failure_locked(
                session,
                outbox_item,
                error,
                failed_at,
                max_attempts=max_attempts,
                max_backoff_seconds=max_backoff_seconds,
                permanent=permanent,
            )

    return "APPLIED"


async def _mark_outbox_failure_locked(
    session: AsyncSession,
    outbox_item: Outbox,
    error: Exception,
    now: datetime,
    max_attempts: int,
    max_backoff_seconds: int,
    permanent: bool = False,
) -> None:
    # Only called with a row lock by verified settlement or the expiry reaper.
    outbox_item.claim_token = None
    outbox_item.attempts += 1
    outbox_item.last_error = str(error)[:1000]
    outbox_item.claimed_at = None

    if permanent or outbox_item.attempts >= max_attempts:
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


def extract_text_body(outbox_item: OutboxClaim) -> str:
    text = outbox_item.payload.get("text")
    if isinstance(text, dict):
        body = text.get("body")
        if isinstance(body, str):
            return body
    raise ValueError(f"Outbox {outbox_item.id} does not contain text.body")


def extract_document_caption(outbox_item: OutboxClaim) -> str:
    document = outbox_item.payload.get("document")
    if isinstance(document, dict):
        caption = document.get("caption")
        if isinstance(caption, str) and caption:
            return caption
    raise ValueError(f"Outbox {outbox_item.id} does not contain document.caption")


def document_catalog_asset_id(outbox_item: OutboxClaim) -> UUID:
    if outbox_item.catalog_asset_id is None:
        raise ValueError(f"Outbox {outbox_item.id} does not reference a catalog asset")
    return outbox_item.catalog_asset_id


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
            await asyncio.gather(
                _run_outbox_loop(sessionmaker, sender, settings),
                _run_inbox_loop(sessionmaker, settings),
                _run_payment_evidence_loop(sessionmaker, settings),
            )
        finally:
            await engine.dispose()


async def _run_inbox_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    from app.channel.inbox import process_inbox_once

    while True:
        try:
            counts = await process_inbox_once(sessionmaker, settings=settings)
            logger.info("inbox_poll_completed", **counts)
        except Exception as error:
            logger.error("inbox_poll_failed", error_type=type(error).__name__)
        await asyncio.sleep(settings.inbox_poll_interval_seconds)


async def _run_outbox_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    sender: OutboundSender,
    settings: Settings,
) -> None:
    while True:
        try:
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
        except Exception:
            logger.exception("outbox_poll_failed")
        await asyncio.sleep(settings.outbox_poll_interval_seconds)


async def _run_payment_evidence_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    from app.payment.worker import process_payment_evidence_once

    async with httpx.AsyncClient(timeout=15.0) as http_client:
        while True:
            try:
                processed = await process_payment_evidence_once(
                    sessionmaker,
                    settings=settings,
                    http_client=http_client,
                )
                logger.info("payment_evidence_poll_completed", processed=processed)
            except Exception:
                logger.exception("payment_evidence_poll_failed")
            await asyncio.sleep(settings.outbox_poll_interval_seconds)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
