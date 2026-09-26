"""Unchanged RED criteria, executed first against the exact R2 product."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.channel import inbound
from app.config.settings import get_settings
from tests.remediation.r3.helpers import MAIN, SERVICES, Provider, prepare, snapshot, valid
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("error_name", ["ConnectError", "ReadError", "VALID"])
async def test_main_transport_contract(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, error_name: str
) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "0")
    get_settings.cache_clear()
    observed: BaseException | None = None
    result = None
    with respx.mock as router:
        provider = Provider(
            router,
            {
                MAIN: [
                    valid()
                    if error_name == "VALID"
                    else getattr(httpx, error_name)("R3 synthetic provider failure")
                ]
            },
        )
        try:
            async with OpenRouterIntentClient(get_settings(), db) as client:
                result = await client.classify_intent("synthetic", {}, request_id=None)
        except Exception as error:
            observed = error
        provider.exhausted()
    final = await snapshot(db)
    evidence(
        request,
        final=final,
        calls=provider.calls,
        exception=type(observed).__name__ if observed else None,
    )
    if error_name == "VALID":
        assert observed is None and result.primary_intent == "GREETING"
    else:
        assert isinstance(observed, AIUnavailable)
        assert observed.reason == AIErrorReason.HTTP_ERROR
        assert final["ai_execution"][0]["error_reason"] == "HTTP_ERROR"


@pytest.mark.parametrize("error_name", ["ConnectError", "ReadError", "VALID"])
async def test_new_inbox_turn_degrades_locally(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, error_name: str
) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "0")
    get_settings.cache_clear()
    event_id = await prepare(db)
    before = await snapshot(db)
    with respx.mock as router:
        provider = Provider(
            router,
            {
                MAIN: [
                    valid()
                    if error_name == "VALID"
                    else getattr(httpx, error_name)("R3 synthetic provider failure")
                ]
            },
        )
        counts = await inbound.process_webhook_event(event_id, db)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls, counts=counts)
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["inbox_job"][0]["attempts"] == 0
    assert final["webhook_event"][0]["status"] == "PROCESSED"
    assert len(final["outbox"]) == 1 and len(final["message"]) == 1
    assert final["message"] == before["message"]


@pytest.mark.parametrize("task", ["EVENT_TYPE_EXTRACTION", "SERVICES_CLASSIFICATION"])
async def test_reached_auxiliary_transport_degrades_by_its_contract(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, task: str
) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "0")
    get_settings.cache_clear()
    event_id = await prepare(
        db,
        state="COLLECTING_EVENT_DATA",
        pending="COLLECT_SERVICES" if task == SERVICES else "COLLECT_EVENT_TYPE",
    )
    before = await snapshot(db)
    with respx.mock as router:
        provider = Provider(
            router, {MAIN: [valid()], task: [httpx.ReadError("R3 synthetic auxiliary failure")]}
        )
        counts = await inbound.process_webhook_event(event_id, db)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls, counts=counts)
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["inbox_job"][0]["attempts"] == 0
    assert final["ai_execution"][0]["success"] is True
    assert final["ai_execution"][1]["error_reason"] == "HTTP_ERROR"
    assert final["webhook_event"][0]["status"] == "PROCESSED"
    assert final["outbox"]
    assert provider.calls == {MAIN: 1, task: 1}
