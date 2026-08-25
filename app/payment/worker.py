from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.channel.media import (
    InboundMediaDownloadError,
    InboundMediaFile,
    InboundMediaHashMismatch,
    InboundMediaTooLarge,
    download_inbound_media,
    normalize_sha256,
)
from app.config.settings import Settings
from app.payment.models import PaymentEvidence

logger = structlog.get_logger(__name__)

MAX_DOWNLOAD_ATTEMPTS = 6
MEDIA_DOWNLOAD_WINDOW = timedelta(days=6)
SUPPORTED_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


@dataclass(frozen=True)
class EvidenceClaim:
    evidence_id: int
    media_id: str
    mime_type: str
    declared_sha256: str
    attempts: int
    created_at: datetime


def evidence_backoff_seconds(attempts: int, max_backoff_seconds: int) -> int:
    """Use the same bounded exponential schedule as the outbox worker."""
    return min(2**attempts, max_backoff_seconds)


async def process_payment_evidence_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> int:
    claimed_at = now or datetime.now(UTC)
    claim = await _claim_one_evidence(
        sessionmaker,
        claimed_at,
        lease_seconds=settings.outbox_sending_timeout_seconds,
    )
    if claim is None:
        return 0

    extension = SUPPORTED_MIME_EXTENSIONS.get(claim.mime_type)
    created_at = _aware_utc(claim.created_at)
    if extension is None:
        await _settle_failure(
            sessionmaker,
            claim,
            claimed_at,
            permanent=True,
            reason="Unsupported payment evidence MIME type",
            max_backoff_seconds=settings.outbox_max_backoff_seconds,
        )
        return 1
    if created_at < claimed_at - MEDIA_DOWNLOAD_WINDOW:
        await _settle_failure(
            sessionmaker,
            claim,
            claimed_at,
            permanent=True,
            reason="Payment evidence media URL is outside the download window",
            max_backoff_seconds=settings.outbox_max_backoff_seconds,
        )
        return 1

    try:
        media = await download_inbound_media(
            claim.media_id,
            settings=settings,
            http_client=http_client,
        )
        _validate_download(claim, media)
        storage_path = _store_private_file(
            Path(settings.payment_evidence_dir),
            claim.evidence_id,
            extension,
            media.bytes,
        )
    except (InboundMediaHashMismatch, InboundMediaTooLarge) as error:
        await _settle_failure(
            sessionmaker,
            claim,
            claimed_at,
            permanent=True,
            reason=str(error),
            max_backoff_seconds=settings.outbox_max_backoff_seconds,
        )
    except (InboundMediaDownloadError, OSError) as error:
        await _settle_failure(
            sessionmaker,
            claim,
            claimed_at,
            permanent=claim.attempts >= MAX_DOWNLOAD_ATTEMPTS,
            reason=str(error),
            max_backoff_seconds=settings.outbox_max_backoff_seconds,
        )
    else:
        await _settle_success(sessionmaker, claim, media, storage_path, claimed_at)
    return 1


async def _claim_one_evidence(
    sessionmaker: async_sessionmaker[AsyncSession],
    now: datetime,
    *,
    lease_seconds: int,
) -> EvidenceClaim | None:
    async with sessionmaker() as session:
        async with session.begin():
            evidence = await session.scalar(
                select(PaymentEvidence)
                .where(
                    PaymentEvidence.download_status.in_(("PENDING", "FAILED_RETRYABLE")),
                    or_(
                        PaymentEvidence.next_attempt_at.is_(None),
                        PaymentEvidence.next_attempt_at <= now,
                    ),
                )
                .order_by(PaymentEvidence.created_at, PaymentEvidence.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if evidence is None:
                return None
            evidence.download_attempts += 1
            evidence.next_attempt_at = now + timedelta(seconds=lease_seconds)
            return EvidenceClaim(
                evidence_id=evidence.id,
                media_id=evidence.media_id,
                mime_type=evidence.mime_type,
                declared_sha256=evidence.declared_sha256,
                attempts=evidence.download_attempts,
                created_at=evidence.created_at,
            )


def _validate_download(claim: EvidenceClaim, media: InboundMediaFile) -> None:
    if media.mime_type.split(";", 1)[0].strip().casefold() != claim.mime_type.casefold():
        raise InboundMediaHashMismatch("Downloaded MIME type differs from inbound declaration")
    try:
        declared_sha256 = normalize_sha256(claim.declared_sha256)
    except ValueError as error:
        raise InboundMediaHashMismatch(
            "Inbound declaration contains an invalid sha256"
        ) from error
    if media.sha256 != declared_sha256:
        raise InboundMediaHashMismatch("Downloaded hash differs from inbound declaration")


def _store_private_file(
    storage_dir: Path,
    evidence_id: int,
    extension: str,
    content: bytes,
) -> str:
    storage_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    target = storage_dir / f"{evidence_id}{extension}"
    temporary = storage_dir / f".{evidence_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, 0o640)
        temporary.replace(target)
        os.chmod(target, 0o640)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return str(target)


async def _settle_success(
    sessionmaker: async_sessionmaker[AsyncSession],
    claim: EvidenceClaim,
    media: InboundMediaFile,
    storage_path: str,
    now: datetime,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            evidence = await session.get(
                PaymentEvidence, claim.evidence_id, with_for_update=True
            )
            if evidence is None:
                return
            evidence.download_status = "DOWNLOADED"
            evidence.storage_path = storage_path
            evidence.verified_sha256 = media.sha256
            evidence.size_bytes = media.size_bytes
            evidence.next_attempt_at = None
            session.add(
                AuditEvent(
                    actor="INTEGRATION",
                    action="PAYMENT_EVIDENCE_DOWNLOADED",
                    entity="payment_evidence",
                    old_value={"download_status": "PENDING"},
                    new_value={
                        "evidence_id": evidence.id,
                        "download_status": evidence.download_status,
                        "attempts": evidence.download_attempts,
                        "size_bytes": evidence.size_bytes,
                    },
                    reason="Payment evidence downloaded and hash verified",
                    request_id=None,
                    created_at=now,
                )
            )


async def _settle_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    claim: EvidenceClaim,
    now: datetime,
    *,
    permanent: bool,
    reason: str,
    max_backoff_seconds: int,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            evidence = await session.get(
                PaymentEvidence, claim.evidence_id, with_for_update=True
            )
            if evidence is None:
                return
            is_permanent = permanent or evidence.download_attempts >= MAX_DOWNLOAD_ATTEMPTS
            evidence.download_status = (
                "FAILED_PERMANENT" if is_permanent else "FAILED_RETRYABLE"
            )
            evidence.next_attempt_at = (
                None
                if is_permanent
                else now
                + timedelta(
                    seconds=evidence_backoff_seconds(
                        evidence.download_attempts, max_backoff_seconds
                    )
                )
            )
            session.add(
                AuditEvent(
                    actor="INTEGRATION",
                    action="PAYMENT_EVIDENCE_DOWNLOAD_FAILED",
                    entity="payment_evidence",
                    old_value=None,
                    new_value={
                        "evidence_id": evidence.id,
                        "download_status": evidence.download_status,
                        "attempts": evidence.download_attempts,
                        "size_bytes": evidence.size_bytes,
                    },
                    reason=reason[:500],
                    request_id=None,
                    created_at=now,
                )
            )
    logger.warning(
        "payment_evidence_download_failed",
        evidence_id=claim.evidence_id,
        attempts=claim.attempts,
        permanent=permanent,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
