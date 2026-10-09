"""Opt-in inbound transcription; media stays in memory and HTTP runs outside sessions."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.ai.audio import AudioTranscriptionResult, transcribe_audio
from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.channel.audio_duration import InvalidOpus, opus_duration_seconds
from app.channel.media import (
    InboundMediaDownloadError,
    InboundMediaHashMismatch,
    InboundMediaTooLarge,
    download_inbound_media,
    normalize_sha256,
)
from app.channel.models import Message
from app.channel.transcription_models import MessageTranscription
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.customer.phone import normalize_phone_number

if TYPE_CHECKING:
    from app.channel.inbox import InboxClaim, SessionMaker

# This context only suppresses transport logs for private media. Origin is an explicit field.
_private_audio_http: ContextVar[bool] = ContextVar("private_audio_http", default=False)


class _PrivateAudioHTTPFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_audio_http.get()


for _logger_name in (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_PrivateAudioHTTPFilter())


def _derive_claim(claim: InboxClaim, row: MessageTranscription) -> InboxClaim:
    context = {
        **claim.persisted.context,
        "transcription_id": row.id,
        "audio_transcription_status": row.status,
    }
    changes: dict[str, Any] = {"context": context}
    if row.status == "SUCCESS":
        changes.update(
            message_text=row.transcript or "",
            message_type="text",
            input_origin="AUDIO_TRANSCRIPT",
        )
        context["input_origin"] = "AUDIO_TRANSCRIPT"
    return replace(claim, persisted=replace(claim.persisted, **changes))


async def persist_transcription(
    sm: SessionMaker,
    claim: InboxClaim,
    *,
    status: str,
    mime: str | None = None,
    media_sha256: str | None = None,
    size_bytes: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    asr: AudioTranscriptionResult | None = None,
) -> MessageTranscription:
    """Atomically append telemetry, one unique result and its audit; discard losing telemetry."""
    async with sm() as session, session.begin():
        async with session.begin_nested() as attempt:
            execution_id = None
            if asr is not None:
                execution = AIExecution(
                    task="AUDIO_TRANSCRIPTION",
                    model=asr.model,
                    prompt_version=asr.prompt_version,
                    latency_ms=asr.latency_ms,
                    success=asr.success,
                    error_reason=asr.error_reason,
                    validation_status=asr.validation_status,
                    conversation_id=claim.conversation_id,
                    request_id=claim.request_id,
                    external_message_id=claim.persisted.external_message_id,
                    input_character_count=0,
                    input_payload={
                        "message_id": claim.message_id,
                        "mime": mime,
                        "size_bytes": size_bytes,
                        "duration_ms": duration_ms,
                        "tokens": asr.tokens,
                    },
                    raw_output=None,
                    parsed_output={
                        "is_speech": asr.is_speech,
                        "language": asr.language,
                        "transcript_chars": len(asr.transcript or ""),
                    },
                )
                session.add(execution)
                await session.flush()
                execution_id = execution.id
            created_id = await session.scalar(
                insert(MessageTranscription)
                .values(
                    message_id=claim.message_id,
                    status=status,
                    transcript=asr.transcript if asr else None,
                    is_speech=asr.is_speech if asr else None,
                    language=asr.language if asr else None,
                    ai_execution_id=execution_id,
                    model=asr.model if asr else None,
                    prompt_version=asr.prompt_version if asr else None,
                    media_sha256=media_sha256,
                    size_bytes=size_bytes,
                    duration_ms=duration_ms,
                    error_code=error_code,
                )
                .on_conflict_do_nothing(index_elements=[MessageTranscription.message_id])
                .returning(MessageTranscription.id)
            )
            if created_id is None:
                # Rollback our AI row too: history contains only the winning execution.
                await attempt.rollback()
        row = await session.scalar(
            select(MessageTranscription).where(
                MessageTranscription.message_id == claim.message_id
            )
        )
        if row is None:
            raise RuntimeError("Transcription result missing after insertion")
        if created_id is not None:
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="AUDIO_TRANSCRIPTION_COMPLETED",
                    entity="message",
                    old_value=None,
                    new_value={
                        "message_id": claim.message_id,
                        "transcription_id": row.id,
                        "status": row.status,
                        "ai_execution_id": row.ai_execution_id,
                        "duration_ms": row.duration_ms,
                        "size_bytes": row.size_bytes,
                        "transcript_chars": len(row.transcript or ""),
                    },
                    reason="AUDIO_TRANSCRIPTION_RESULT",
                    request_id=claim.request_id,
                )
            )
    return row


async def ensure_transcription(sm: SessionMaker, claim: InboxClaim) -> InboxClaim:
    """Reuse a stored result or perform the bounded, non-mutating ASR operation."""
    if claim.persisted.message_type != "audio" or claim.persisted.message_text.strip():
        return claim
    settings = get_settings()
    if not settings.audio_transcription_enabled:
        # The disabled path performs no new reads or audit writes.
        return claim

    from app.channel.inbox import silent_reason

    async with sm() as session, session.begin():
        message = await session.get(Message, claim.message_id)
        conversation = await session.get(Conversation, claim.conversation_id)
        customer = await session.get(Customer, claim.persisted.customer_id)
        if message is None or conversation is None or customer is None:
            return claim
        reason = None
        if silent_reason(conversation) is not None:
            reason = "PAUSED"
        elif not settings.audio_transcription_allow_all:
            allowed = set()
            for value in settings.audio_transcription_allowed_phones.split(","):
                if value.strip():
                    try:
                        allowed.add(normalize_phone_number(value))
                    except ValueError:
                        continue
            if normalize_phone_number(customer.phone_number) not in allowed:
                reason = "NOT_ALLOWLISTED"
        if reason is not None:
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="AUDIO_TRANSCRIPTION_SKIPPED",
                    entity="message",
                    old_value=None,
                    new_value={"message_id": message.id, "reason": reason},
                    reason=reason,
                    request_id=claim.request_id,
                )
            )
            return claim
        existing = await session.scalar(
            select(MessageTranscription).where(
                MessageTranscription.message_id == claim.message_id
            )
        )
        if existing is not None:
            return _derive_claim(claim, existing)
        metadata = dict(message.content.get("audio") or {})
        received_at = message.provider_timestamp or message.created_at

    values: dict[str, Any] = {}

    async def finish(status: str, error_code: str | None = None, **extra: object) -> InboxClaim:
        row = await persist_transcription(
            sm, claim, status=status, error_code=error_code, **values, **extra
        )
        return _derive_claim(claim, row)

    if datetime.now(UTC) - received_at > timedelta(days=6):
        return await finish("INVALID_MEDIA", "EXPIRED_MEDIA")
    declared_size = metadata.get("file_size")
    if type(declared_size) is int and declared_size >= 0:
        values["size_bytes"] = declared_size
        if declared_size > settings.audio_max_bytes:
            return await finish("TOO_LONG", "SIZE_LIMIT")
    identifier = metadata.get("media_id") or metadata.get("id")
    webhook_sha256 = metadata.get("sha256")
    if not isinstance(webhook_sha256, str):
        return await finish("INVALID_MEDIA", "INVALID_HASH")
    try:
        expected_sha256 = normalize_sha256(webhook_sha256)
    except (ValueError, TypeError):
        return await finish("INVALID_MEDIA", "INVALID_HASH")
    if not isinstance(identifier, str) or not identifier:
        return await finish("INVALID_MEDIA", "MISSING_MEDIA")
    token = _private_audio_http.set(True)
    try:
        try:
            media = await download_inbound_media(
                identifier, settings=settings, max_bytes=settings.audio_max_bytes
            )
        except InboundMediaTooLarge:
            return await finish("TOO_LONG", "SIZE_LIMIT")
        except InboundMediaHashMismatch:
            return await finish("INVALID_MEDIA", "HASH_MISMATCH")
        except InboundMediaDownloadError:
            return await finish("INVALID_MEDIA", "DOWNLOAD_FAILED")
        mime = media.mime_type.split(";", 1)[0].strip().lower()
        values.update(mime=mime, size_bytes=media.size_bytes, media_sha256=media.sha256)
        if media.sha256 != expected_sha256:
            return await finish("INVALID_MEDIA", "HASH_MISMATCH")
        if mime != "audio/ogg":
            return await finish("INVALID_MEDIA", "UNSUPPORTED_MIME")
        try:
            duration = opus_duration_seconds(media.bytes)
        except InvalidOpus:
            return await finish("INVALID_MEDIA", "INVALID_DURATION")
        values["duration_ms"] = round(duration * 1000)
        if duration > settings.audio_max_seconds:
            return await finish("TOO_LONG", "DURATION_LIMIT")
        asr = await transcribe_audio(media.bytes, duration, settings)
    finally:
        _private_audio_http.reset(token)
    return await finish(asr.status, asr.error_reason, asr=asr)
