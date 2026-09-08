"""Client contract: real HTTPX/parser/telemetry, synthetic transport outcomes only."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx
import structlog.testing
from sqlalchemy import text

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.config.settings import get_settings
from tests.remediation.r3.helpers import MAIN, SENSITIVE, Provider, snapshot, valid
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


def configure(monkeypatch: pytest.MonkeyPatch, retries: int) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", str(retries))
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "0.25")
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "error_name",
    [
        "ConnectError",
        "ReadError",
        "WriteError",
        "CloseError",
        "RemoteProtocolError",
        "ProxyError",
    ],
)
@pytest.mark.parametrize("scenario", ["zero", "exhausted", "recovered"])
async def test_expected_transport_budget_and_sanitized_telemetry(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
    scenario: str,
) -> None:
    retries = {"zero": 0, "exhausted": 2, "recovered": 1}[scenario]
    configure(monkeypatch, retries)
    failures = [getattr(httpx, error_name)(SENSITIVE) for _ in range(retries + 1)]
    outcomes = [failures[0], valid()] if scenario == "recovered" else failures
    with structlog.testing.capture_logs() as logs, respx.mock as router:
        provider = Provider(router, {MAIN: outcomes})
        async with OpenRouterIntentClient(get_settings(), db) as client:
            if scenario == "recovered":
                result = await client.classify_intent("synthetic", {}, request_id=None)
                assert result.primary_intent == "GREETING"
            else:
                with pytest.raises(AIUnavailable) as raised:
                    await client.classify_intent("synthetic", {}, request_id=None)
                assert raised.value.reason == AIErrorReason.HTTP_ERROR
                assert error_name in raised.value.detail
                assert SENSITIVE not in str(raised.value) + raised.value.detail
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls, timeouts=provider.timeouts, logs=logs)
    assert provider.calls == {MAIN: retries + 1}
    assert all(set(v.values()) == {0.25} for v in provider.timeouts)
    assert len(final["ai_execution"]) == 1
    record = final["ai_execution"][0]
    assert record["success"] == (scenario == "recovered")
    assert record["error_reason"] == (None if scenario == "recovered" else "HTTP_ERROR")
    assert SENSITIVE not in json.dumps(logs, default=str)
    assert SENSITIVE not in (record["error"] or "")


@pytest.mark.parametrize(
    "error_name", ["ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"]
)
async def test_timeout_keeps_specific_category(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
) -> None:
    configure(monkeypatch, 1)
    with respx.mock as router:
        provider = Provider(
            router, {MAIN: [getattr(httpx, error_name)(SENSITIVE) for _ in range(2)]}
        )
        async with OpenRouterIntentClient(get_settings(), db) as client:
            with pytest.raises(AIUnavailable) as raised:
                await client.classify_intent("synthetic", {}, request_id=None)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls)
    assert raised.value.reason == AIErrorReason.TIMEOUT
    assert provider.calls == {MAIN: 2}
    assert final["ai_execution"][0]["error_reason"] == "TIMEOUT"
    assert SENSITIVE not in raised.value.detail


@pytest.mark.parametrize(
    "control", ["http401", "http429", "http503", "invalid_json", "invalid_schema", "valid"]
)
async def test_existing_http_parser_and_valid_contracts(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    configure(monkeypatch, 1)
    if control.startswith("http"):
        outcomes, reason = [httpx.Response(int(control[4:])) for _ in range(2)], "HTTP_ERROR"
    elif control == "invalid_json":
        outcomes, reason = ["R3 synthetic malformed JSON"], "INVALID_JSON"
    elif control == "invalid_schema":
        outcomes, reason = [{"primary_intent": "R3_INVALID_INTENT"}], "SCHEMA_VIOLATION"
    else:
        outcomes, reason = [valid()], None
    with respx.mock as router:
        provider = Provider(router, {MAIN: outcomes})
        async with OpenRouterIntentClient(get_settings(), db) as client:
            if reason:
                with pytest.raises(AIUnavailable) as raised:
                    await client.classify_intent("synthetic", {}, request_id=None)
                assert raised.value.reason.value == reason
            else:
                assert (
                    await client.classify_intent("synthetic", {}, request_id=None)
                ).primary_intent == "GREETING"
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls)
    assert provider.calls == {MAIN: 2 if control.startswith("http") else 1}
    assert final["ai_execution"][0]["error_reason"] == reason


@pytest.mark.parametrize(
    "error_name",
    ["LocalProtocolError", "UnsupportedProtocol", "InvalidURL", "RuntimeError", "AssertionError"],
)
async def test_configuration_and_programming_errors_are_not_unavailable(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
) -> None:
    configure(monkeypatch, 2)
    error_type = {"RuntimeError": RuntimeError, "AssertionError": AssertionError}.get(error_name)
    error_type = error_type or getattr(httpx, error_name)
    with respx.mock as router:
        provider = Provider(router, {MAIN: [error_type("R3 synthetic non-provider fault")]})
        async with OpenRouterIntentClient(get_settings(), db) as client:
            with pytest.raises(error_type):
                await client.classify_intent("synthetic", {}, request_id=None)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls, propagated=error_name)
    assert provider.calls == {MAIN: 1}
    assert final["ai_execution"][0]["success"] is False
    assert final["ai_execution"][0]["error_reason"] is None


async def test_unmocked_http_assertion_is_not_swallowed(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 2)
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        async with OpenRouterIntentClient(get_settings(), db) as client:
            with pytest.raises(AssertionError):
                await client.classify_intent("synthetic guard control", {}, request_id=None)
    final = await snapshot(db)
    evidence(request, final=final, guard="UNMOCKED_HTTP_REJECTED", calls=len(router.calls))
    assert final["ai_execution"][0]["success"] is False


async def test_cancelled_client_keeps_base_exception(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, 2)
    with respx.mock as router:
        provider = Provider(router, {MAIN: [asyncio.CancelledError("R3 synthetic cancellation")]})
        async with OpenRouterIntentClient(get_settings(), db) as client:
            with pytest.raises(asyncio.CancelledError):
                await client.classify_intent("synthetic", {}, request_id=None)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, calls=provider.calls)
    assert provider.calls == {MAIN: 1}
    assert not final["ai_execution"][0]["success"]


@pytest.mark.parametrize("outcome", ["valid", "unavailable"])
async def test_telemetry_sql_failure_does_not_replace_task_outcome(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    configure(monkeypatch, 0)
    async with db() as session, session.begin():
        await session.execute(
            text(
                "CREATE FUNCTION r3_reject_ai() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'R3_SYNTHETIC_PRIVATE'; END $$"
            )
        )
        await session.execute(
            text(
                "CREATE TRIGGER r3_reject_ai BEFORE INSERT ON ai_execution "
                "FOR EACH ROW EXECUTE FUNCTION r3_reject_ai()"
            )
        )
    try:
        with structlog.testing.capture_logs() as logs, respx.mock as router:
            provider = Provider(
                router, {MAIN: [valid() if outcome == "valid" else httpx.ReadError(SENSITIVE)]}
            )
            async with OpenRouterIntentClient(get_settings(), db) as client:
                if outcome == "valid":
                    result = await client.classify_intent("synthetic", {}, request_id=None)
                    assert result.primary_intent == "GREETING"
                else:
                    with pytest.raises(AIUnavailable) as raised:
                        await client.classify_intent("synthetic", {}, request_id=None)
                    assert raised.value.reason == AIErrorReason.HTTP_ERROR
            provider.exhausted()
        final = await snapshot(db)
        warnings = [r for r in logs if r.get("event") == "ai_execution_persist_failed"]
        evidence(request, final=final, calls=provider.calls, logs=logs)
        assert len(warnings) == 1 and warnings[0]["task"] == MAIN
        assert "R3_SYNTHETIC_PRIVATE" not in json.dumps(logs, default=str)
        assert final["ai_execution"] == []
        async with db() as session:
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        async with db() as session, session.begin():
            await session.execute(text("DROP TRIGGER r3_reject_ai ON ai_execution"))
            await session.execute(text("DROP FUNCTION r3_reject_ai()"))
