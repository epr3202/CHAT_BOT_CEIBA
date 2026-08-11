from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.models import AIExecution
from app.ai.schemas import IntentClassification
from app.config.database import Base
from app.config.settings import Settings
from tests.integration.helpers import DATABASE_URL


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


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
        classification = await client.classify_intent("Hola", context={})

    assert isinstance(classification, IntentClassification)
    assert classification.primary_intent == "GREETING"
    assert await count_ai_executions(sessionmaker_fixture) == 1


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
            await client.classify_intent("Hola", context={})

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
            await client.classify_intent("Hola", context={})

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
            await client.classify_intent("Quiero hablar con alguien", context={})

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
            await client.classify_intent("Hola", context={})

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
        classification = await client.classify_intent("Hola", context={})

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
            await client.classify_intent("???", context={})

    assert error.value.reason == AIErrorReason.INVALID_JSON
    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert execution is not None
    assert execution.success is False
    assert execution.error_reason == "INVALID_JSON"
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
        await client.classify_intent("Hola", context={})

    request_payload = json.loads(route.calls.last.request.content)
    assert request_payload["messages"][0]["content"].startswith(
        "Eres una capa de interpretación"
    )
    assert "Rúbrica explícita de confianza" in request_payload["messages"][0]["content"]

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(select(AIExecution))

    assert execution is not None
    assert execution.prompt_version == "intent_v2"
