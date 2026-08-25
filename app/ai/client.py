from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.errors import AIErrorReason, AIUnavailable, EmptyClassificationInput
from app.ai.models import AIExecution
from app.ai.prompts import get_intent_prompt
from app.ai.prompts.event_type_extraction_v1 import (
    EVENT_TYPE_EXTRACTION_PROMPT_VERSION,
    event_type_extraction_prompt,
)
from app.ai.prompts.services_v1 import (
    SERVICES_PROMPT_VERSION,
    services_classification_prompt,
)
from app.ai.schemas import (
    EventTypeExtraction,
    IntentClassification,
    ServicesClassification,
)
from app.config.settings import Settings
from app.event.event_type import normalize_event_type

INTENT_CLASSIFICATION_FUNCTION = "INTENT_CLASSIFICATION"
SERVICES_CLASSIFICATION_FUNCTION = "SERVICES_CLASSIFICATION"
EVENT_TYPE_EXTRACTION_FUNCTION = "EVENT_TYPE_EXTRACTION"
DEFAULT_INTENT_MODEL = "openai/gpt-4o-mini"
TELEMETRY_SAFE_KNOWN_FIELDS = frozenset({"event_type", "preferred_visit_date"})
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _TaskResult[TaskValue]:
    value: TaskValue
    validation_status: str = "VALID"


class OpenRouterIntentClient:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        http_client: httpx.AsyncClient | None = None,
        model: str | None = None,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._model = model or settings.openrouter_model_intent or DEFAULT_INTENT_MODEL
        self._prompt = get_intent_prompt(settings.ai_prompt_version)
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> OpenRouterIntentClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._settings.openrouter_base_url.rstrip("/") + "/",
                timeout=self._settings.openrouter_timeout_seconds,
            )
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()

    async def classify_intent(
        self,
        message_text: str,
        context: dict[str, Any],
        conversation_id: int | None = None,
        *,
        request_id: uuid.UUID | None,
        external_message_id: str | None = None,
    ) -> IntentClassification:
        result = await self._execute_task(
            task=INTENT_CLASSIFICATION_FUNCTION,
            prompt_version=self._prompt.version,
            system_prompt=self._prompt.content,
            instruction="Clasifica el siguiente mensaje.",
            message_text=message_text,
            context=context,
            conversation_id=conversation_id,
            request_id=request_id,
            external_message_id=external_message_id,
            parse_result=lambda output: _TaskResult(IntentClassification.model_validate(output)),
        )
        return result

    async def classify_services(
        self,
        message_text: str,
        context: dict[str, Any],
        conversation_id: int | None = None,
        *,
        request_id: uuid.UUID | None,
        external_message_id: str | None = None,
    ) -> list[str]:
        result = await self._execute_task(
            task=SERVICES_CLASSIFICATION_FUNCTION,
            prompt_version=SERVICES_PROMPT_VERSION,
            system_prompt=services_classification_prompt(),
            instruction="Clasifica los servicios solicitados en el mensaje.",
            message_text=message_text,
            context=context,
            conversation_id=conversation_id,
            request_id=request_id,
            external_message_id=external_message_id,
            parse_result=lambda output: _TaskResult(
                list(ServicesClassification.model_validate(output).service_codes)
            ),
        )
        return result

    async def extract_event_type(
        self,
        message_text: str,
        context: dict[str, Any],
        conversation_id: int | None = None,
        *,
        request_id: uuid.UUID | None,
        external_message_id: str | None = None,
    ) -> str | None:
        result = await self._execute_task(
            task=EVENT_TYPE_EXTRACTION_FUNCTION,
            prompt_version=EVENT_TYPE_EXTRACTION_PROMPT_VERSION,
            system_prompt=event_type_extraction_prompt(),
            instruction="Extrae el tipo de celebración del mensaje.",
            message_text=message_text,
            context=context,
            conversation_id=conversation_id,
            request_id=request_id,
            external_message_id=external_message_id,
            parse_result=_parse_event_type_result,
        )
        return result

    async def _execute_task[TaskValue](
        self,
        *,
        task: str,
        prompt_version: str,
        system_prompt: str,
        instruction: str,
        message_text: str,
        context: dict[str, Any],
        conversation_id: int | None,
        request_id: uuid.UUID | None,
        external_message_id: str | None,
        parse_result: Callable[[dict[str, Any]], _TaskResult[TaskValue]],
    ) -> TaskValue:
        if not message_text.strip():
            raise EmptyClassificationInput("Classification input must contain text")
        if self._http_client is None:
            raise RuntimeError("OpenRouterIntentClient must be used as an async context manager")

        started = time.monotonic()
        success = False
        error_reason: AIErrorReason | None = None
        raw_output: str | None = None
        parsed_output: dict[str, Any] | None = None
        validation_status = "INVALID_SCHEMA"
        error_detail: str | None = None
        input_payload = {
            "message_text": message_text,
            "context": telemetry_context(context),
        }

        try:
            payload = self._build_payload(
                message_text,
                context,
                system_prompt=system_prompt,
                instruction=instruction,
            )
            response = await self._post_with_retries("chat/completions", payload)
            raw_output = extract_message_content(response.json())
            parsed_output = parse_json_content(raw_output)
            task_result = parse_result(parsed_output)
            success = True
            validation_status = task_result.validation_status
            return task_result.value
        except AIUnavailable as error:
            error_reason = error.reason
            validation_status = "HTTP_ERROR"
            error_detail = error.detail or str(error)
            raise
        except (json.JSONDecodeError, TypeError, KeyError, IndexError) as error:
            error_reason = AIErrorReason.INVALID_JSON
            error_detail = str(error)
            raise AIUnavailable(AIErrorReason.INVALID_JSON, str(error)) from error
        except ValidationError as error:
            error_reason = AIErrorReason.SCHEMA_VIOLATION
            error_detail = str(error)
            raise AIUnavailable(AIErrorReason.SCHEMA_VIOLATION, str(error)) from error
        except Exception as error:
            error_detail = str(error)
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            try:
                await self._record_execution(
                    task=task,
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                    success=success,
                    error_reason=error_reason,
                    conversation_id=conversation_id,
                    input_character_count=len(message_text),
                    request_id=request_id,
                    external_message_id=external_message_id,
                    input_payload=input_payload,
                    raw_output=raw_output,
                    parsed_output=parsed_output,
                    validation_status=validation_status,
                    error=error_detail,
                )
            except Exception as persistence_error:
                logger.warning(
                    "ai_execution_persist_failed",
                    request_id=str(request_id) if request_id is not None else None,
                    task=task,
                    error=str(persistence_error),
                )

    def _build_payload(
        self,
        message_text: str,
        context: dict[str, Any],
        *,
        system_prompt: str,
        instruction: str,
    ) -> dict[str, Any]:
        normalized_context = {
            "last_intent": context.get("last_intent"),
            "pending_action": context.get("pending_action"),
            "last_question_code": context.get("last_question_code"),
            "known_fields": context.get("known_fields", {}),
            "failed_understanding_count": context.get("failed_understanding_count", 0),
        }
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{instruction} Responde únicamente JSON válido, "
                        "sin markdown ni fences.\n\n"
                        f"Contexto:\n{json.dumps(normalized_context, ensure_ascii=False)}\n\n"
                        f"Mensaje:\n{message_text}"
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    async def _post_with_retries(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        assert self._http_client is not None
        attempts = self._settings.openrouter_max_retries + 1
        last_timeout: httpx.TimeoutException | None = None

        for attempt in range(attempts):
            try:
                response = await self._http_client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self._settings.openrouter_api_key}"},
                    json=payload,
                )
            except httpx.TimeoutException as error:
                last_timeout = error
                if attempt + 1 >= attempts:
                    raise AIUnavailable(AIErrorReason.TIMEOUT, str(error)) from error
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                if attempt + 1 >= attempts:
                    raise AIUnavailable(AIErrorReason.HTTP_ERROR, str(error)) from error
                continue

            return response

        raise AIUnavailable(AIErrorReason.TIMEOUT, str(last_timeout))

    async def _record_execution(
        self,
        task: str,
        prompt_version: str,
        latency_ms: int,
        success: bool,
        error_reason: AIErrorReason | None,
        conversation_id: int | None,
        input_character_count: int,
        request_id: uuid.UUID | None,
        external_message_id: str | None,
        input_payload: dict[str, Any],
        raw_output: str | None,
        parsed_output: dict[str, Any] | None,
        validation_status: str,
        error: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            async with session.begin():
                session.add(
                    AIExecution(
                        task=task,
                        model=self._model,
                        latency_ms=latency_ms,
                        success=success,
                        error_reason=error_reason.value if error_reason is not None else None,
                        prompt_version=prompt_version,
                        conversation_id=conversation_id,
                        input_character_count=input_character_count,
                        request_id=request_id,
                        external_message_id=external_message_id,
                        input_payload=input_payload,
                        raw_output=raw_output,
                        parsed_output=parsed_output,
                        validation_status=validation_status,
                        error=error,
                    )
                )


def telemetry_context(context: dict[str, Any]) -> dict[str, Any]:
    known_fields = context.get("known_fields", {})
    sanitized_known_fields = (
        {key: value for key, value in known_fields.items() if key in TELEMETRY_SAFE_KNOWN_FIELDS}
        if isinstance(known_fields, dict)
        else {}
    )
    return {
        "last_intent": context.get("last_intent"),
        "pending_action": context.get("pending_action"),
        "last_question_code": context.get("last_question_code"),
        "known_fields": sanitized_known_fields,
        "failed_understanding_count": context.get("failed_understanding_count", 0),
        "pending_confirmation": context.get("pending_confirmation"),
    }


def _parse_event_type_result(output: dict[str, Any]) -> _TaskResult[str | None]:
    extracted = EventTypeExtraction.model_validate(output)
    normalized = normalize_event_type(extracted.event_type)
    if normalized is None:
        return _TaskResult(None, validation_status="DISCARDED")
    raw_canonical = extracted.event_type.strip().upper().replace(" ", "_").replace("-", "_")
    status = "VALID" if raw_canonical == normalized else "NORMALIZED"
    return _TaskResult(normalized, validation_status=status)


def extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload["choices"]
    message = choices[0]["message"]
    content = message["content"]
    if not isinstance(content, str):
        raise TypeError("choices[0].message.content must be a string")
    return content


def parse_json_content(content: str) -> dict[str, Any]:
    cleaned = strip_json_fences(content.strip())
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("model response must be a JSON object")
    return parsed


def strip_json_fences(content: str) -> str:
    if content.startswith("```json"):
        content = content.removeprefix("```json").strip()
    elif content.startswith("```"):
        content = content.removeprefix("```").strip()

    if content.endswith("```"):
        content = content.removesuffix("```").strip()
    return content
