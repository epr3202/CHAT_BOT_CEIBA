from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.agent.models import Agent, AgentSession
from app.conversation.models import Conversation
from app.main import app
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
    signature,
    whatsapp_message_payload,
)


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin", document_id="90000000", pin="123456", role="ADMIN")
    await bootstrap_agent(name="Agent", document_id="80000000", pin="123456", role="AGENT")
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


async def latest_conversation() -> Conversation:
    async with app.state.db_sessionmaker() as session:
        conversation = await session.scalar(select(Conversation).order_by(Conversation.id.desc()))
        assert conversation is not None
        return conversation


async def post_whatsapp(client: AsyncClient, message_id: str, phone: str = "573001112233") -> None:
    body = whatsapp_message_payload(message_id, phone=phone)
    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tc_auth_004_expired_session_is_rejected(client: AsyncClient) -> None:
    headers = await login_headers(client, "80000000", "123456")
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            row = await session.scalar(select(AgentSession))
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    response = await client.get("/admin/me", headers=headers)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tc_auth_005_agent_cannot_manage_users_but_admin_can(client: AsyncClient) -> None:
    agent_headers = await login_headers(client, "80000000", "123456")
    admin_headers = await login_headers(client, "90000000", "123456")

    create_forbidden = await client.post(
        "/admin/agents",
        headers=agent_headers,
        json={"name": "Nuevo", "role": "AGENT"},
    )
    reset_forbidden = await client.post(
        "/admin/agents/1/credentials",
        headers=agent_headers,
        json={"document_id": "70000000", "pin": "123456"},
    )
    deactivate_forbidden = await client.post("/admin/agents/1/deactivate", headers=agent_headers)

    assert create_forbidden.status_code == 403
    assert reset_forbidden.status_code == 403
    assert deactivate_forbidden.status_code == 403

    created = await client.post(
        "/admin/agents",
        headers=admin_headers,
        json={"name": "Nuevo", "role": "AGENT"},
    )
    assert created.status_code == 200


@pytest.mark.asyncio
async def test_tc_auth_007_short_pin_is_rejected(client: AsyncClient) -> None:
    admin_headers = await login_headers(client, "90000000", "123456")
    created = await client.post(
        "/admin/agents",
        headers=admin_headers,
        json={"name": "Nuevo", "role": "AGENT"},
    )
    assert created.status_code == 200

    response = await client.post(
        f"/admin/agents/{created.json()['id']}/credentials",
        headers=admin_headers,
        json={"document_id": "70000000", "pin": "12345"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tc_auth_008_reset_credentials_revokes_sessions(client: AsyncClient) -> None:
    old_headers = await login_headers(client, "80000000", "123456")
    admin_headers = await login_headers(client, "90000000", "123456")

    async with app.state.db_sessionmaker() as session:
        agent = await session.scalar(select(Agent).where(Agent.document_id == "80000000"))
        assert agent is not None
        agent_id = agent.id

    reset = await client.post(
        f"/admin/agents/{agent_id}/credentials",
        headers=admin_headers,
        json={"document_id": "80000000", "pin": "654321"},
    )
    old_me = await client.get("/admin/me", headers=old_headers)
    new_login = await client.post(
        "/admin/login",
        json={"document_id": "80000000", "pin": "654321"},
    )

    assert reset.status_code == 200
    assert old_me.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_tc_auth_009_history_filters_by_conversation_in_sql(client: AsyncClient) -> None:
    headers = await login_headers(client, "80000000", "123456")
    await post_whatsapp(client, "wamid.history.1", phone="573001112233")
    first = await latest_conversation()
    await post_whatsapp(client, "wamid.history.2", phone="573001112234")
    second = await latest_conversation()

    first_take = await client.post(f"/admin/conversations/{first.id}/take", headers=headers)
    second_take = await client.post(f"/admin/conversations/{second.id}/take", headers=headers)
    assert first_take.status_code == 200
    assert second_take.status_code == 200

    history = await client.get(f"/admin/conversations/{second.id}/history", headers=headers)

    assert history.status_code == 200
    assert [event["action"] for event in history.json()] == [
        "HANDOFF_CREATED",
        "HANDOFF_TAKEN",
        "CONVERSATION_MANUAL_TAKEOVER",
    ][1:]
    assert all("history.1" not in str(event) for event in history.json())
