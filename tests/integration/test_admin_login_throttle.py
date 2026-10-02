from __future__ import annotations

import threading
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.admin import routes
from app.audit.models import AuditEvent
from app.main import app
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
)

DOCUMENT_ID = "90000000"
OTHER_DOCUMENT_ID = "80000000"
PIN = "123456"
WRONG_PIN = "654321"


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "5")
    monkeypatch.setenv("ADMIN_LOGIN_WINDOW_MINUTES", "15")
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin", document_id=DOCUMENT_ID, pin=PIN, role="ADMIN")
    await bootstrap_agent(name="Agent", document_id=OTHER_DOCUMENT_ID, pin=PIN, role="AGENT")
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


async def record_five_failures(client: AsyncClient, document_id: str = DOCUMENT_ID) -> None:
    for _ in range(5):
        response = await client.post(
            "/admin/login", json={"document_id": document_id, "pin": WRONG_PIN}
        )
        assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_sixth_failed_attempt_returns_429_even_with_correct_pin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await record_five_failures(client)
    pin_checks: list[str] = []
    original_verify_pin = routes.verify_pin

    def track_verify_pin(pin: str, password_hash: str) -> bool:
        pin_checks.append(pin)
        return original_verify_pin(pin, password_hash)

    monkeypatch.setattr(routes, "verify_pin", track_verify_pin)
    response = await client.post(
        "/admin/login", json={"document_id": f" {DOCUMENT_ID} ", "pin": PIN}
    )

    assert response.status_code == 429, response.text
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"] == "Too many login attempts"
    assert pin_checks == []


@pytest.mark.asyncio
async def test_throttled_attempt_does_not_record_login_failed(client: AsyncClient) -> None:
    await record_five_failures(client)
    response = await client.post(
        "/admin/login", json={"document_id": DOCUMENT_ID, "pin": WRONG_PIN}
    )
    assert response.status_code == 429, response.text

    async with app.state.db_sessionmaker() as session:
        failures = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "ADMIN_LOGIN_FAILED",
                AuditEvent.new_value["document_id"].as_string() == DOCUMENT_ID,
            )
        )
        throttled = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "ADMIN_LOGIN_THROTTLED",
                    AuditEvent.new_value["document_id"].as_string() == DOCUMENT_ID,
                )
            )
        ).all()

    assert failures == 5
    assert len(throttled) == 1
    assert throttled[0].actor == "UNKNOWN"
    assert throttled[0].entity == "agent"
    assert throttled[0].new_value == {"document_id": DOCUMENT_ID, "recent_failures": 5}
    assert throttled[0].reason == "Login throttled"


@pytest.mark.asyncio
async def test_window_expiry_allows_login_again(client: AsyncClient) -> None:
    await record_five_failures(client)
    blocked = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})
    assert blocked.status_code == 429, blocked.text

    # Only this test fixture rewrites timestamps; production audit remains append-only.
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            updated = await session.execute(
                text(
                    "UPDATE audit_event SET created_at = now() - interval '16 minutes' "
                    "WHERE action = 'ADMIN_LOGIN_FAILED' "
                    "AND new_value->>'document_id' = :document_id"
                ),
                {"document_id": DOCUMENT_ID},
            )
            assert updated.rowcount == 5

    response = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_failures_are_scoped_by_document_id(client: AsyncClient) -> None:
    await record_five_failures(client)
    blocked = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})
    assert blocked.status_code == 429, blocked.text

    response = await client.post(
        "/admin/login", json={"document_id": OTHER_DOCUMENT_ID, "pin": PIN}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_successful_login_is_not_throttled_by_old_successes(client: AsyncClient) -> None:
    for _ in range(6):
        response = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})
        assert response.status_code == 200, response.text

    # Successes leave the complete failure budget available, but do not disable throttling.
    await record_five_failures(client)
    response = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})
    assert response.status_code == 429, response.text


@pytest.mark.asyncio
async def test_unknown_document_is_throttled_too(client: AsyncClient) -> None:
    unknown_document_id = "70000000"
    await record_five_failures(client, unknown_document_id)
    response = await client.post(
        "/admin/login", json={"document_id": unknown_document_id, "pin": PIN}
    )
    assert response.status_code == 429, response.text


@pytest.mark.asyncio
async def test_verify_pin_runs_off_the_event_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran_on_main_thread: list[bool] = []

    def track_verify_pin(pin: str, password_hash: str) -> bool:
        ran_on_main_thread.append(threading.current_thread() is threading.main_thread())
        return True

    monkeypatch.setattr("app.admin.routes.verify_pin", track_verify_pin)
    response = await client.post("/admin/login", json={"document_id": DOCUMENT_ID, "pin": PIN})

    assert response.status_code == 200, response.text
    assert ran_on_main_thread == [False]
