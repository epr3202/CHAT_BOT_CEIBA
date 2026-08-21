from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import structlog
from httpx import AsyncClient
from sqlalchemy import UniqueConstraint, select

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.channel.models import WebhookEvent
from app.conversation.models import Conversation
from app.main import app
from tests.integration.helpers import (
    app_client,
    cleanup_test_environment,
    configure_test_environment,
    signature,
    whatsapp_message_payload,
)

OPENROUTER_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
ORCHESTRATOR_LOGGER = "app.orchestrator.service"
DECISION_FIELDS = {
    "request_id",
    "intent",
    "state_before",
    "state_after",
    "transition",
    "decision_source",
    "pending_action",
}


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    real_classify_intent = OpenRouterIntentClient.classify_intent
    await configure_test_environment(monkeypatch)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", real_classify_intent)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


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


def completion_payload(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-observability-test",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(arguments),
                }
            }
        ],
    }


async def post_message(
    client: AsyncClient,
    external_message_id: str,
    *,
    text: str = "Hola",
    external_request_id: str | None = None,
) -> httpx.Response:
    body = whatsapp_message_payload(external_message_id, text=text)
    headers = {"X-Hub-Signature-256": signature(body)}
    if external_request_id is not None:
        headers["X-Request-ID"] = external_request_id
    return await client.post(
        "/webhook",
        content=body,
        headers=headers,
    )


async def stored_executions() -> list[AIExecution]:
    async with app.state.db_sessionmaker() as session:
        return list(
            (await session.scalars(select(AIExecution).order_by(AIExecution.created_at))).all()
        )


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


def assert_single_decision_record(
    caplog: pytest.LogCaptureFixture,
    decision_source: str,
    *,
    intent: str | None = None,
) -> logging.LogRecord:
    records = [record for record in caplog.records if record.name == ORCHESTRATOR_LOGGER]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO
    assert getattr(record, "event", None) == "orchestrator_decision"
    assert DECISION_FIELDS <= vars(record).keys()
    assert record.decision_source == decision_source  # type: ignore[attr-defined]
    if intent is not None:
        assert record.intent == intent  # type: ignore[attr-defined]
    return record


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_005_http_error_persists_error_without_raw_output(
    client: AsyncClient,
) -> None:
    respx.post(OPENROUTER_COMPLETIONS_URL).mock(
        return_value=httpx.Response(503, text="provider unavailable")
    )

    response = await post_message(client, "wamid.aiexec.005")
    executions = await stored_executions()

    assert response.status_code == 200
    assert len(executions) == 1
    execution = executions[0]
    assert execution.validation_status == "HTTP_ERROR"
    assert execution.success is False
    assert execution.error_reason == "HTTP_ERROR"
    assert execution.error
    assert execution.raw_output is None


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_006_every_execution_has_prompt_version_and_model(
    client: AsyncClient,
) -> None:
    call_count = 0

    def valid_then_unavailable(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=completion_payload(valid_classification()))
        return httpx.Response(503, text="provider unavailable")

    respx.post(OPENROUTER_COMPLETIONS_URL).mock(side_effect=valid_then_unavailable)

    first_response = await post_message(client, "wamid.aiexec.006.valid")
    second_response = await post_message(client, "wamid.aiexec.006.http-error")
    executions = await stored_executions()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(executions) == 2
    assert all(execution.prompt_version for execution in executions)
    assert all(execution.model for execution in executions)
    assert all(execution.task == "INTENT_CLASSIFICATION" for execution in executions)
    assert all(execution.input_payload for execution in executions)
    assert all(execution.validation_status for execution in executions)
    assert all(execution.external_message_id for execution in executions)
    assert all(execution.request_id for execution in executions)


@pytest.mark.asyncio
@respx.mock
async def test_tc_aiexec_007_webhook_request_id_reaches_persisted_execution(
    client: AsyncClient,
) -> None:
    respx.post(OPENROUTER_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    response = await post_message(
        client,
        "wamid.aiexec.007",
        external_request_id="caller-controlled-request-id",
    )
    executions = await stored_executions()
    async with app.state.db_sessionmaker() as session:
        webhook_event = await session.scalar(select(WebhookEvent))

    assert response.status_code == 200
    assert len(executions) == 1
    execution = executions[0]
    assert UUID(str(execution.request_id)).version == 4
    assert str(execution.request_id) != "caller-controlled-request-id"
    assert execution.external_message_id == "wamid.aiexec.007"
    assert webhook_event is not None
    assert str(webhook_event.request_id) == str(execution.request_id)


@pytest.mark.asyncio
async def test_tc_aiexec_008_two_tasks_share_external_message_id_without_unique_collision() -> None:
    required_columns = {
        "id",
        "created_at",
        "request_id",
        "external_message_id",
        "task",
        "model",
        "prompt_version",
        "input_payload",
        "raw_output",
        "parsed_output",
        "validation_status",
        "latency_ms",
        "error",
        "success",
        "error_reason",
        "conversation_id",
        "input_character_count",
    }
    assert required_columns <= set(AIExecution.__table__.columns.keys())
    assert not any(
        isinstance(constraint, UniqueConstraint)
        and "external_message_id" in {column.name for column in constraint.columns}
        for constraint in AIExecution.__table__.constraints
    )

    external_message_id = "wamid.aiexec.008"
    request_id = uuid4()
    common = {
        "model": "openai/test-model",
        "prompt_version": "intent_v4",
        "input_payload": {"message_text": "Hola", "context": {}},
        "raw_output": '{"primary_intent":"GREETING"}',
        "parsed_output": {"primary_intent": "GREETING"},
        "validation_status": "VALID",
        "latency_ms": 1,
        "error": None,
        "success": True,
        "error_reason": None,
        "conversation_id": None,
        "input_character_count": 4,
    }
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            session.add_all(
                [
                    AIExecution(
                        request_id=request_id,
                        external_message_id=external_message_id,
                        task="INTENT_CLASSIFICATION",
                        **common,
                    ),
                    AIExecution(
                        request_id=request_id,
                        external_message_id=external_message_id,
                        task="SERVICES_CLASSIFICATION",
                        **common,
                    ),
                ]
            )

    async with app.state.db_sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    select(AIExecution).where(
                        AIExecution.external_message_id == external_message_id
                    )
                )
            ).all()
        )

    assert len(rows) == 2
    assert {row.task for row in rows} == {
        "INTENT_CLASSIFICATION",
        "SERVICES_CLASSIFICATION",
    }


@pytest.mark.asyncio
@respx.mock
async def test_tc_log_001_deterministic_decision_has_structured_schema(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = respx.post(OPENROUTER_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )
    await post_message(client, "wamid.log.001.seed")

    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            conversation = await session.scalar(select(Conversation))
            assert conversation is not None
            conversation.pending_action = "CONFIRM_QUOTE_REQUEST"
            conversation.last_question_code = "RESP-QUOTE-002"

    caplog.clear()
    with capture_structured_records(), caplog.at_level(logging.INFO, logger=ORCHESTRATOR_LOGGER):
        response = await post_message(client, "wamid.log.001.decision", text="Sí")

    assert response.status_code == 200
    assert route.call_count == 1
    assert_single_decision_record(caplog, "DETERMINISTIC", intent="CONFIRM")


@pytest.mark.asyncio
@respx.mock
async def test_tc_log_002_llm_decision_has_structured_schema(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post(OPENROUTER_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=completion_payload(valid_classification()))
    )

    with capture_structured_records(), caplog.at_level(logging.INFO, logger=ORCHESTRATOR_LOGGER):
        response = await post_message(client, "wamid.log.002")

    assert response.status_code == 200
    assert_single_decision_record(caplog, "LLM", intent="GREETING")


@pytest.mark.asyncio
@respx.mock
async def test_tc_log_003_fallback_decision_has_structured_schema(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post(OPENROUTER_COMPLETIONS_URL).mock(
        return_value=httpx.Response(503, text="provider unavailable")
    )

    with capture_structured_records(), caplog.at_level(logging.INFO, logger=ORCHESTRATOR_LOGGER):
        response = await post_message(client, "wamid.log.003")

    assert response.status_code == 200
    assert_single_decision_record(caplog, "FALLBACK")
