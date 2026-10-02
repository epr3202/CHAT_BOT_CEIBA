from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.agent.models import Agent
from app.audit.models import AuditEvent
from app.main import app
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin", document_id="90000000", role="ADMIN")
    await bootstrap_agent(name="Agent", document_id="80000000", role="AGENT")
    async for test_client in app_client():
        yield test_client
    await cleanup_test_environment()


async def agent_id(document_id: str = "80000000") -> int:
    async with app.state.db_sessionmaker() as session:
        result = await session.scalar(select(Agent.id).where(Agent.document_id == document_id))
        assert result is not None
        return result


async def test_get_agent_includes_credentials_and_missing_agent_is_404(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    response = await client.get(f"/admin/agents/{await agent_id()}", headers=headers)
    assert response.status_code == 200
    assert response.json()["document_id"] == "80000000"
    assert response.json()["has_credentials"] is True
    assert "password_hash" not in response.json()
    missing = await client.get("/admin/agents/999999", headers=headers)
    assert missing.status_code == 404


async def test_patch_agent_name_role_conflicts_and_empty_body(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    target_id = await agent_id()
    path = f"/admin/agents/{target_id}"
    renamed = await client.patch(path, headers=headers, json={"name": "Nuevo"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Nuevo"
    promoted = await client.patch(path, headers=headers, json={"role": "ADMIN"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "ADMIN"
    duplicate = await client.patch(path, headers=headers, json={"name": "Admin"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Agent name already exists"
    empty = await client.patch(path, headers=headers, json={})
    assert empty.status_code == 422
    async with app.state.db_sessionmaker() as session:
        agent = await session.get(Agent, target_id)
        assert (agent.name, agent.role) == ("Nuevo", "ADMIN")
        events = list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.action == "AGENT_UPDATED")
                .order_by(AuditEvent.id)
            )
        )
        assert len(events) == 2
        assert events[0].old_value["name"] == "Agent"
        assert events[0].new_value["name"] == "Nuevo"
        assert events[1].old_value["role"] == "AGENT"
        assert events[1].new_value["role"] == "ADMIN"


async def test_activate_agent_is_idempotent(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    target_id = await agent_id()
    async with app.state.db_sessionmaker() as session, session.begin():
        agent = await session.get(Agent, target_id)
        agent.active = False
    for _ in range(2):
        response = await client.post(f"/admin/agents/{target_id}/activate", headers=headers)
        assert response.status_code == 200
        assert response.json()["active"] is True
    async with app.state.db_sessionmaker() as session:
        events = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.action == "AGENT_ACTIVATED"))
        )
        assert len(events) == 1
        assert events[0].actor == "Admin"


@pytest.mark.parametrize("operation", ["deactivate", "demote"])
async def test_last_active_admin_is_protected(client: AsyncClient, operation: str) -> None:
    headers = await login_headers(client, "90000000")
    target_id = await agent_id("90000000")

    async def change() -> object:
        if operation == "deactivate":
            return await client.post(f"/admin/agents/{target_id}/deactivate", headers=headers)
        return await client.patch(
            f"/admin/agents/{target_id}",
            headers=headers,
            json={"role": "AGENT"},
        )

    rejected = await change()
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == f"Cannot {operation} the last active admin"
    async with app.state.db_sessionmaker() as session:
        admin = await session.get(Agent, target_id)
        assert admin.active is True
        assert admin.role == "ADMIN"
    await bootstrap_agent(name="Second Admin", document_id="90000001", role="ADMIN")
    allowed = await change()
    assert allowed.status_code == 200
    async with app.state.db_sessionmaker() as session:
        admin = await session.get(Agent, target_id)
        assert (not admin.active) if operation == "deactivate" else admin.role == "AGENT"


async def test_agent_cannot_use_any_agent_management_endpoint(client: AsyncClient) -> None:
    headers = await login_headers(client, "80000000")
    target_id = await agent_id()
    requests = [
        ("GET", f"/admin/agents/{target_id}", None),
        ("GET", "/admin/agents", None),
        ("POST", "/admin/agents", {"name": "Forbidden", "role": "AGENT"}),
        ("PATCH", f"/admin/agents/{target_id}", {"name": "Forbidden"}),
        ("POST", f"/admin/agents/{target_id}/activate", None),
        ("POST", f"/admin/agents/{target_id}/deactivate", None),
        (
            "POST",
            f"/admin/agents/{target_id}/credentials",
            {"document_id": "70000000", "pin": "123456"},
        ),
    ]
    for method, path, body in requests:
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, (method, path, response.text)


async def test_list_and_create_include_credentials_and_sort_by_name(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    created = await client.post("/admin/agents", headers=headers, json={"name": "Zeta"})
    assert created.status_code == 200
    assert {"document_id", "has_credentials", "active"} <= created.json().keys()
    assert created.json()["document_id"] is None
    assert created.json()["has_credentials"] is False
    response = await client.get("/admin/agents", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert [row["name"] for row in rows] == ["Admin", "Agent", "Zeta"]
    assert all({"document_id", "has_credentials", "active"} <= row.keys() for row in rows)
    assert [row["has_credentials"] for row in rows] == [True, True, False]
