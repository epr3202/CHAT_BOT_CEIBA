from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.models import AIExecution
from app.ai.prompts import get_intent_prompt
from app.ai.schemas import IntentClassification
from app.config.settings import Settings

INTENT_CLASSIFICATION_FUNCTION = "INTENT_CLASSIFICATION"
DEFAULT_INTENT_MODEL = "openai/gpt-4o-mini"


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
    ) -> IntentClassification:
        if self._http_client is None:
            raise RuntimeError("OpenRouterIntentClient must be used as an async context manager")

        started = time.monotonic()
        success = False
        error_reason: AIErrorReason | None = None

        try:
            payload = self._build_payload(message_text, context)
            response = await self._post_with_retries("chat/completions", payload)
            content = extract_message_content(response.json())
            parsed = parse_json_content(content)
            classification = IntentClassification.model_validate(parsed)
            success = True
            return classification
        except AIUnavailable as error:
            error_reason = error.reason
            raise
        except (json.JSONDecodeError, TypeError, KeyError, IndexError) as error:
            error_reason = AIErrorReason.INVALID_JSON
            raise AIUnavailable(AIErrorReason.INVALID_JSON, str(error)) from error
        except ValidationError as error:
            error_reason = AIErrorReason.SCHEMA_VIOLATION
            raise AIUnavailable(AIErrorReason.SCHEMA_VIOLATION, str(error)) from error
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            await self._record_execution(
                latency_ms=latency_ms,
                success=success,
                error_reason=error_reason,
                conversation_id=conversation_id,
                input_character_count=len(message_text),
            )

    def _build_payload(self, message_text: str, context: dict[str, Any]) -> dict[str, Any]:
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
                {"role": "system", "content": self._prompt.content},
                {
                    "role": "user",
                    "content": (
                        "Clasifica el siguiente mensaje. Responde únicamente JSON válido, "
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
        latency_ms: int,
        success: bool,
        error_reason: AIErrorReason | None,
        conversation_id: int | None,
        input_character_count: int,
    ) -> None:
        async with self._sessionmaker() as session:
            async with session.begin():
                session.add(
                    AIExecution(
                        function=INTENT_CLASSIFICATION_FUNCTION,
                        model=self._model,
                        latency_ms=latency_ms,
                        success=success,
                        error_reason=error_reason.value if error_reason is not None else None,
                        prompt_version=self._prompt.version,
                        conversation_id=conversation_id,
                        input_character_count=input_character_count,
                    )
                )


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
