from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
import respx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.models import AIExecution
from app.ai.schemas import IntentClassification
from app.config.settings import Settings
from tests.integration.helpers import DATABASE_URL, reset_test_database


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield await reset_test_database()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL_INTENT="openai/test-model",
        OPENROUTER_TIMEOUT_SECONDS=0.2,
        OPENROUTER_MAX_RETRIES=0,
        ENVIRONMENT="testing",
        _env_file=None,
    )


def completion_payload(arguments: dict[str, object] | str) -> dict[str, object]:
    content = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ],
    }


def valid_classification() -> dict[str, object]:
    return {
        "primary_intent": "GREETING",
        "secondary_intents": [],
        "sub_intent": None,
        "confidence": 0.91,
        "entities": {},
        "requested_action": "SEND_GREETING",
        "missing_fields": [],
        "needs_confirmation": False,
        "needs_human": False,
        "handoff_reason": None,
        "priority": "NORMAL",
        "context_reference": {
            "pending_action": None,
            "last_question_code": None,
        },
        "reasoning_code": "EXPLICIT_GREETING",
    }


def classification_with_event_type(value: str) -> dict[str, object]:
    payload = valid_classification()
    payload["primary_intent"] = "EVENT_INFORMATION"
    payload["extracted_entities"] = [
        {
            "entity": "event_type",
            "raw_value": value,
            "normalized_value": value,
            "quality_status": "PROVIDED",
            "confidence": 0.93,
            "needs_confirmation": False,
            "validation_errors": [],
        }
    ]
    return payload


@contextmanager
def capture_structured_records() -> Iterator[None]:
    previous_config = structlog.get_config()
    structlog.configure(
        processors=[structlog.stdlib.render_to_log_kwargs],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    try:
        yield
    finally:
        structlog.configure(**previous_config)


async def count_ai_executions(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(AIExecution)) or 0


@pytest.mark.asyncio
@respx.mock
async def test_valid_json_returns_intent_classification(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        classification = await client.classify_intent("Hola", context={}, request_id=None)

    assert isinstance(classification, IntentClassification)
    assert classification.primary_intent == "GREETING"
    assert await count_ai_executions(sessionmaker_fixture) == 1


@pytest.mark.asyncio
@respx.mock
async def test_prompt_includes_pending_action_and_last_question_code_context(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        await client.classify_intent(
            "Correcto",
            context={
                "pending_action": "CONFIRM_QUOTE_REQUEST",
                "last_question_code": "RESP-QUOTE-002",
            },
            request_id=None,
        )

    request = route.calls.last.request
    payload = json.loads(request.content)
    user_content = payload["messages"][1]["content"]
    assert '"pending_action": "CONFIRM_QUOTE_REQUEST"' in user_content
    assert '"last_question_code": "RESP-QUOTE-002"' in user_content


@pytest.mark.asyncio
@respx.mock
async def test_unknown_intent_becomes_schema_violation(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    payload = valid_classification()
    payload["primary_intent"] = "MADE_UP"
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(payload))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as error:
            await client.classify_intent("Hola", context={}, request_id=None)

    assert error.value.reason == AIErrorReason.SCHEMA_VIOLATION
    assert await count_ai_executions(sessionmaker_fixture) == 1


@pytest.mark.asyncio
@respx.mock
async def test_extra_field_becomes_schema_violation(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    payload = valid_classification()
    payload["unexpected"] = "not allowed"
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(payload))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as error:
            await client.classify_intent("Hola", context={}, request_id=None)

    assert error.value.reason == AIErrorReason.SCHEMA_VIOLATION


@pytest.mark.asyncio
@respx.mock
async def test_needs_human_requires_handoff_reason(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    payload = valid_classification()
    payload["needs_human"] = True
    payload["handoff_reason"] = None
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(payload))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as error:
            await client.classify_intent("Quiero hablar con alguien", context={}, request_id=None)

    assert error.value.reason == AIErrorReason.SCHEMA_VIOLATION


@pytest.mark.asyncio
@respx.mock
async def test_timeout_becomes_ai_unavailable(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=raise_timeout)

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as error:
            await client.classify_intent("Hola", context={}, request_id=None)

    assert error.value.reason == AIErrorReason.TIMEOUT
    assert await count_ai_executions(sessionmaker_fixture) == 1


@pytest.mark.asyncio
@respx.mock
async def test_json_fences_are_stripped(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    fenced = "```json\n" + json.dumps(valid_classification()) + "\n```"
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(fenced))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        classification = await client.classify_intent("Hola", context={}, request_id=None)

    assert classification.primary_intent == "GREETING"


@pytest.mark.asyncio
@respx.mock
async def test_failure_records_ai_execution(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload("{invalid"))
    )

    started = time.monotonic()
    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as error:
            await client.classify_intent("???", context={}, request_id=None)

    assert error.value.reason == AIErrorReason.INVALID_JSON
    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert execution is not None
    assert execution.success is False
    assert execution.error_reason == "INVALID_JSON"
    assert execution.validation_status == "INVALID_SCHEMA"
    assert execution.raw_output == "{invalid"
    assert execution.parsed_output is None
    assert execution.conversation_id is None
    assert execution.input_character_count == 3
    assert execution.latency_ms >= 0
    assert time.monotonic() - started < 5


@pytest.mark.asyncio
@respx.mock
async def test_prompt_version_setting_selects_v2_and_records_execution(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    settings.ai_prompt_version = "intent_v2"
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        await client.classify_intent("Hola", context={}, request_id=None)

    request_payload = json.loads(route.calls.last.request.content)
    assert request_payload["messages"][0]["content"].startswith("Eres una capa de interpretación")
    assert "Rúbrica explícita de confianza" in request_payload["messages"][0]["content"]

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert execution is not None
    assert execution.prompt_version == "intent_v2"


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_001_persists_raw_parsed_prompt_conversation_and_timestamp(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    raw_payload = classification_with_event_type("CENA ROMÁNTICA")
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(raw_payload))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        classification = await client.classify_intent("Cena romántica", context={}, request_id=None)

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert classification.extracted_entities[0].normalized_value == "CENA ROMÁNTICA"
    assert execution is not None
    assert execution.raw_output == json.dumps(raw_payload)
    assert execution.parsed_output == raw_payload
    assert execution.validation_status == "VALID"
    assert execution.prompt_version == settings.ai_prompt_version
    assert execution.created_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_002_persists_invalid_schema_raw_and_parsed_output(
    settings: Settings,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    raw_payload = valid_classification()
    raw_payload["primary_intent"] = "MADE_UP"
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(raw_payload))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as raised:
            await client.classify_intent("Mensaje inválido", context={}, request_id=None)

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert raised.value.reason == AIErrorReason.SCHEMA_VIOLATION
    assert execution is not None
    assert execution.raw_output == json.dumps(raw_payload)
    assert execution.parsed_output == raw_payload
    assert execution.validation_status == "INVALID_SCHEMA"
    assert execution.error


@pytest.mark.asyncio
async def test_tc_aiexec_003_http_finishes_before_persistence_transaction(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    client = OpenRouterIntentClient(settings, Mock(), http_client=httpx.AsyncClient())

    async def fake_post(endpoint: str, payload: dict[str, object]) -> httpx.Response:
        order.extend(("http_started", "http_finished"))
        return httpx.Response(200, json=completion_payload(valid_classification()))

    async def tracking_record(**kwargs: object) -> None:
        order.append("persistence_started")

    monkeypatch.setattr(client, "_post_with_retries", fake_post)
    monkeypatch.setattr(client, "_record_execution", tracking_record)

    await client.classify_intent("Hola", context={}, request_id=None)
    await client._http_client.aclose()  # type: ignore[union-attr]

    assert order == ["http_started", "http_finished", "persistence_started"]


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_004_persistence_failure_does_not_fail_classification(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    async def fail_persistence(**kwargs: object) -> None:
        raise RuntimeError("ai_execution unavailable")

    request_id = uuid4()
    async with OpenRouterIntentClient(settings, Mock()) as client:
        monkeypatch.setattr(client, "_record_execution", fail_persistence)
        with capture_structured_records(), caplog.at_level(logging.WARNING, logger="app.ai.client"):
            classification = await client.classify_intent("Hola", context={}, request_id=request_id)

    assert classification.primary_intent == "GREETING"
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "ai_execution_persist_failed"
        or "ai_execution_persist_failed" in record.getMessage()
    ]
    assert len(records) == 1
    assert str(records[0].request_id) == str(request_id)  # type: ignore[attr-defined]
    assert records[0].task == "INTENT_CLASSIFICATION"  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_persistence_failure_preserves_original_ai_error(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(503, text="provider unavailable")
    )

    async def fail_persistence(**kwargs: object) -> None:
        raise RuntimeError("ai_execution unavailable")

    async with OpenRouterIntentClient(settings, Mock()) as client:
        monkeypatch.setattr(client, "_record_execution", fail_persistence)
        with capture_structured_records(), caplog.at_level(logging.WARNING, logger="app.ai.client"):
            with pytest.raises(AIUnavailable) as raised:
                await client.classify_intent("Hola", context={}, request_id=None)

    assert raised.value.reason == AIErrorReason.HTTP_ERROR
    assert any(
        getattr(record, "event", None) == "ai_execution_persist_failed"
        or "ai_execution_persist_failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
@respx.mock
async def test_input_payload_allows_only_safe_known_fields(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )
    context = {
        "last_intent": "EVENT_INFORMATION",
        "pending_action": "COLLECT_EVENT_TYPE",
        "last_question_code": "RESP-DISCOVERY-002",
        "known_fields": {
            "phone_number": "+573001112233",
            "full_name": "Cliente de prueba",
            "event_type": "WEDDING",
            "preferred_visit_date": "2026-09-12",
            "event_month": "2026-09",
        },
        "failed_understanding_count": 1,
        "pending_confirmation": {"type": "EVENT_TYPE"},
    }
    recorded: dict[str, object] = {}

    async def capture_execution(**kwargs: object) -> None:
        recorded.update(kwargs)

    async with OpenRouterIntentClient(settings, Mock()) as client:
        monkeypatch.setattr(client, "_record_execution", capture_execution)
        await client.classify_intent("Quiero una boda", context=context, request_id=None)

    assert recorded["input_payload"] == {
        "message_text": "Quiero una boda",
        "context": {
            "last_intent": "EVENT_INFORMATION",
            "pending_action": "COLLECT_EVENT_TYPE",
            "last_question_code": "RESP-DISCOVERY-002",
            "known_fields": {
                "event_type": "WEDDING",
                "preferred_visit_date": "2026-09-12",
            },
            "failed_understanding_count": 1,
            "pending_confirmation": {"type": "EVENT_TYPE"},
        },
    }
