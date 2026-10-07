"""Literal audio transcription with bounded transport and no domain actions."""

from __future__ import annotations

import base64
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.client import OpenRouterHTTPClient, extract_message_content
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.prompts.audio_v1 import AUDIO_PROMPT, AUDIO_PROMPT_VERSION, AUDIO_USER_TEXT
from app.config.settings import Settings


class AudioTranscription(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    transcript: str = Field(max_length=2000)
    is_speech: bool
    language: str | None


class AudioTranscriptionResult(BaseModel):
    """Validated provider proposal; persistence and turn application live outside AI."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    status: Literal["SUCCESS", "UNCLEAR", "FAILED"]
    transcript: str | None = None
    is_speech: bool | None = None
    language: str | None = None
    model: str
    prompt_version: str = AUDIO_PROMPT_VERSION
    latency_ms: int = Field(ge=0)
    success: bool
    error_reason: str | None = None
    validation_status: Literal["VALID", "DISCARDED", "INVALID_SCHEMA", "HTTP_ERROR"]
    tokens: dict[str, int] = Field(default_factory=dict)


def build_audio_payload(model: str, audio_bytes: bytes) -> dict[str, Any]:
    """The exact ogg/provider/schema contract accepted by the S0 gate."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": AUDIO_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": AUDIO_USER_TEXT},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(audio_bytes).decode("ascii"),
                            "format": "ogg",
                        },
                    },
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": 600,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "audio_transcription",
                "strict": True,
                "schema": AudioTranscription.model_json_schema(),
            },
        },
        "provider": {"zdr": True, "require_parameters": True},
    }


async def transcribe_audio(
    audio_bytes: bytes, duration_seconds: float, settings: Settings
) -> AudioTranscriptionResult:
    """One HTTP attempt, one strict parse, and a deterministic result classification."""
    started = time.monotonic()
    tokens: dict[str, int] = {}
    model = settings.openrouter_model_audio
    transport_settings = settings.model_copy(
        update={
            "openrouter_timeout_seconds": settings.audio_transcription_timeout_seconds,
            "openrouter_max_retries": 0,
        }
    )

    def failed(
        error_reason: str,
        validation_status: Literal["INVALID_SCHEMA", "HTTP_ERROR"],
    ) -> AudioTranscriptionResult:
        return AudioTranscriptionResult(
            status="FAILED",
            model=model,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            success=False,
            error_reason=error_reason,
            validation_status=validation_status,
            tokens=tokens,
        )

    try:
        async with OpenRouterHTTPClient(transport_settings) as client:
            response = await client.post(
                "chat/completions", build_audio_payload(model, audio_bytes)
            )
        body = response.json()
        if not isinstance(body, dict):
            return failed("INVALID_JSON", "INVALID_SCHEMA")
        usage = body.get("usage")
        if isinstance(usage, dict):
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                count = usage.get(name)
                if type(count) is int and count >= 0:
                    tokens[name] = count
        parsed = AudioTranscription.model_validate_json(extract_message_content(body))
    except AIUnavailable as error:
        status = (
            "HTTP_ERROR"
            if error.reason in {AIErrorReason.TIMEOUT, AIErrorReason.HTTP_ERROR}
            else "INVALID_SCHEMA"
        )
        return failed(error.reason.value, status)
    except ValidationError as error:
        reason = (
            "INVALID_JSON"
            if any(item["type"] == "json_invalid" for item in error.errors())
            else "SCHEMA_VIOLATION"
        )
        return failed(reason, "INVALID_SCHEMA")
    except httpx.TimeoutException:
        return failed("TIMEOUT", "HTTP_ERROR")
    except httpx.HTTPError:
        return failed("HTTP_ERROR", "HTTP_ERROR")
    except (ValueError, TypeError, KeyError, IndexError):
        return failed("INVALID_JSON", "INVALID_SCHEMA")

    # Keep the accepted S0 schema unchanged while respecting the storage bound.
    if parsed.language is not None and len(parsed.language) > 16:
        return failed("SCHEMA_VIOLATION", "INVALID_SCHEMA")
    transcript = parsed.transcript.strip()
    reason = None
    if not parsed.is_speech:
        reason = "NO_SPEECH"
    elif not transcript:
        reason = "EMPTY_TRANSCRIPT"
    elif len(transcript) > 25 * duration_seconds + 40:
        reason = "EXCESSIVE_TRANSCRIPT"
    return AudioTranscriptionResult(
        status="UNCLEAR" if reason else "SUCCESS",
        transcript=transcript,
        is_speech=parsed.is_speech,
        language=parsed.language,
        model=model,
        latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        success=reason is None,
        error_reason=reason,
        validation_status="DISCARDED" if reason else "VALID",
        tokens=tokens,
    )
