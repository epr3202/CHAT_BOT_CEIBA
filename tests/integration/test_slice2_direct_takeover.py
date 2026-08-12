from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.agent.auth import hash_agent_token
from app.agent.models import Agent, AgentSession
from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.handoff.models import Handoff
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
    await bootstrap_agent(name="Admin", document_id="99999999", pin="123456", role="ADMIN")
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


def agent_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def admin_headers(client: AsyncClient) -> dict[str, str]:
    return await login_headers(client, "99999999", "123456")


def fake_classification(intent: str) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.91,
        entities={},
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TEST",
    )


def mock_classifier(monkeypatch: pytest.MonkeyPatch, result: IntentClassification) -> None:
    async def classify(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return result

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify)


async def post_whatsapp(
    client: AsyncClient,
    message_id: str,
    text: str = "Hola",
    phone: str = "573001112233",
) -> None:
    body = whatsapp_message_payload(message_id, phone=phone, text=text)
    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )
    assert response.status_code == 200


async def create_agent(
    client: AsyncClient,
    name: str = "Alexandra",
    document_id: str | None = None,
    pin: str = "123456",
    role: str = "AGENT",
) -> dict[str, Any]:
    admin_auth = await login_headers(client, "99999999", "123456")
    response = await client.post(
        "/admin/agents",
        headers=admin_auth,
        json={"name": name, "role": role},
    )
    assert response.status_code == 200
    payload = response.json()
    credentials = await client.post(
        f"/admin/agents/{payload['id']}/credentials",
        headers=admin_auth,
        json={"document_id": document_id or f"10{payload['id']:08d}", "pin": pin},
    )
    assert credentials.status_code == 200
    login = await client.post(
        "/admin/login",
        json={"document_id": document_id or f"10{payload['id']:08d}", "pin": pin},
    )
    assert login.status_code == 200
    payload["token"] = login.json()["token"]
    payload["document_id"] = document_id or f"10{payload['id']:08d}"
    return payload


async def latest_conversation() -> Conversation:
    async with app.state.db_sessionmaker() as session:
        conversation = await session.scalar(select(Conversation).order_by(Conversation.id.desc()))
        assert conversation is not None
        return conversation


async def count_rows(model: type) -> int:
    async with app.state.db_sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.asyncio
async def test_tc_auth_001_login_creates_session_and_stores_only_hashes(
    client: AsyncClient,
) -> None:
    payload = await create_agent(client, "Alexandra", document_id="1020304050", pin="654321")

    assert payload["id"]
    assert payload["name"] == "Alexandra"
    assert len(payload["token"]) >= 32

    async with app.state.db_sessionmaker() as session:
        agent = await session.get(Agent, payload["id"])
        agent_session = await session.scalar(
            select(AgentSession).where(AgentSession.agent_id == payload["id"])
        )
        audit_values = [
            str(event.new_value) + str(event.old_value)
            for event in (await session.scalars(select(AuditEvent))).all()
        ]

    assert agent is not None
    assert agent.document_id == "1020304050"
    assert agent.password_hash is not None
    assert agent.password_hash.startswith("$2b$")
    assert "654321" not in agent.password_hash
    assert agent_session is not None
    assert agent_session.token_hash == hash_agent_token(payload["token"])
    assert payload["token"] not in "".join(audit_values)
    assert "654321" not in "".join(audit_values)

    listed = await client.get("/admin/agents", headers=await admin_headers(client))
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]


@pytest.mark.asyncio
async def test_tc_auth_002_bad_pin_and_missing_user_return_same_401(client: AsyncClient) -> None:
    await create_agent(client, "Emerson", document_id="1020304050", pin="654321")

    bad_pin = await client.post(
        "/admin/login",
        json={"document_id": "1020304050", "pin": "000000"},
    )
    missing_user = await client.post(
        "/admin/login",
        json={"document_id": "99990000", "pin": "000000"},
    )

    assert bad_pin.status_code == 401
    assert missing_user.status_code == 401
    assert bad_pin.json() == missing_user.json()


@pytest.mark.asyncio
async def test_tc_auth_004_logout_revokes_session(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client, "Emerson", document_id="1020304050")
    logout = await client.post("/admin/logout", headers=agent_headers(agent["token"]))
    assert logout.status_code == 200
    me = await client.get("/admin/me", headers=agent_headers(agent["token"]))
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_tc_auth_003_deactivated_agent_returns_403_and_invalidates_sessions(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client, "Inactive")

    deactivate = await client.post(
        f"/admin/agents/{agent['id']}/deactivate",
        headers=await admin_headers(client),
    )
    assert deactivate.status_code == 200

    relogin = await client.post(
        "/admin/login",
        json={"document_id": agent["document_id"], "pin": "123456"},
    )
    response = await client.get("/admin/me", headers=agent_headers(agent["token"]))

    assert relogin.status_code == 403
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tc_auth_006_admin_take_uses_real_assigned_agent_id(
    client: AsyncClient,
) -> None:
    await post_whatsapp(client, "wamid.agent.admin-not-agent")
    conversation = await latest_conversation()
    auth = await admin_headers(client)

    response = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=auth,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assigned_to"] == "Admin"
    assert payload["assigned_agent"]["name"] == "Admin"

    async with app.state.db_sessionmaker() as session:
        conversation_after = await session.get(Conversation, conversation.id)

    assert conversation_after is not None
    assert conversation_after.state == "HUMAN_ACTIVE"
    assert conversation_after.assigned_agent_id == payload["assigned_agent"]["id"]


@pytest.mark.asyncio
async def test_tc_take_001_002_direct_take_bot_active_creates_taken_handoff_without_outbox(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.take.bot-active")
    conversation = await latest_conversation()
    outbox_before = await count_rows(Outbox)

    response = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reason"] == "MANUAL_TAKEOVER"
    assert payload["status"] == "TAKEN"
    assert payload["assigned_agent"]["id"] == agent["id"]
    assert payload["assigned_to"] == "Alexandra"
    assert await count_rows(Outbox) == outbox_before

    async with app.state.db_sessionmaker() as session:
        conversation_after = await session.get(Conversation, conversation.id)
        handoffs = list((await session.scalars(select(Handoff))).all())
        audit_actions = list((await session.scalars(select(AuditEvent.action))).all())

    assert conversation_after is not None
    assert conversation_after.state == "HUMAN_ACTIVE"
    assert conversation_after.bot_enabled is False
    assert conversation_after.pending_action == "WAIT_FOR_HUMAN"
    assert conversation_after.assigned_agent_id == agent["id"]
    assert len(handoffs) == 1
    assert handoffs[0].reason == "MANUAL_TAKEOVER"
    assert handoffs[0].status == "TAKEN"
    assert handoffs[0].assigned_agent_id == agent["id"]
    assert "HANDOFF_CREATED" in audit_actions
    assert "HANDOFF_TAKEN" in audit_actions
    assert "CONVERSATION_STATE_TRANSITION" in audit_actions


@pytest.mark.asyncio
async def test_tc_take_003_concurrent_direct_take_allows_one_agent(client: AsyncClient) -> None:
    first_agent = await create_agent(client, "Alexandra")
    second_agent = await create_agent(client, "Mateo")
    await post_whatsapp(client, "wamid.take.concurrent")
    conversation = await latest_conversation()

    first, second = await asyncio.gather(
        client.post(
            f"/admin/conversations/{conversation.id}/take",
            headers=agent_headers(first_agent["token"]),
        ),
        client.post(
            f"/admin/conversations/{conversation.id}/take",
            headers=agent_headers(second_agent["token"]),
        ),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    async with app.state.db_sessionmaker() as session:
        handoffs = list((await session.scalars(select(Handoff))).all())
        conversation_after = await session.get(Conversation, conversation.id)

    assert len(handoffs) == 1
    assert conversation_after is not None
    assert conversation_after.state == "HUMAN_ACTIVE"
    assert conversation_after.assigned_agent_id in {first_agent["id"], second_agent["id"]}


@pytest.mark.asyncio
async def test_tc_take_004_005_006_rejects_non_eligible_states(client: AsyncClient) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.take.reject-human")
    human_conversation = await latest_conversation()
    ok = await client.post(
        f"/admin/conversations/{human_conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert ok.status_code == 200

    human_again = await client.post(
        f"/admin/conversations/{human_conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert human_again.status_code == 409

    await post_whatsapp(client, "wamid.take.reject-closed", phone="573001112234")
    closed_conversation = await latest_conversation()
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            managed = await session.get(Conversation, closed_conversation.id)
            assert managed is not None
            await transition_conversation(session, managed, ConversationState.CLOSED, "TEST")

    closed = await client.post(
        f"/admin/conversations/{closed_conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert closed.status_code == 409

    await post_whatsapp(client, "wamid.take.reject-waiting", phone="573001112235")
    waiting_conversation = await latest_conversation()
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            managed = await session.get(Conversation, waiting_conversation.id)
            assert managed is not None
            await transition_conversation(
                session,
                managed,
                ConversationState.WAITING_FOR_HUMAN,
                "TEST",
            )
            session.add(
                Handoff(
                    conversation_id=managed.id,
                    status="PENDING",
                    reason="CUSTOMER_REQUEST",
                    priority="NORMAL",
                    summary="handoff pendiente existente",
                )
            )

    waiting = await client.post(
        f"/admin/conversations/{waiting_conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert waiting.status_code == 409
    assert "handoff pendiente" in waiting.text.lower()


@pytest.mark.asyncio
async def test_tc_take_007_008_webhook_during_human_active_is_visible_and_idempotent(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.take.human-active.initial")
    conversation = await latest_conversation()
    take = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert take.status_code == 200
    outbox_before = await count_rows(Outbox)

    await post_whatsapp(client, "wamid.take.human-active.customer", "Sigo esperando")
    await post_whatsapp(client, "wamid.take.human-active.customer", "Sigo esperando")

    async with app.state.db_sessionmaker() as session:
        inbound_count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.external_message_id == "wamid.take.human-active.customer",
            )
        )
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "MESSAGE_RECEIVED_DURING_HANDOFF")
        )

    assert inbound_count == 1
    assert audit is not None
    assert await count_rows(Outbox) == outbox_before

    messages = await client.get(
        f"/admin/conversations/{conversation.id}/messages",
        headers=agent_headers(agent["token"]),
    )
    assert messages.status_code == 200
    assert any(message["body"] == "Sigo esperando" for message in messages.json())


@pytest.mark.asyncio
async def test_taken_conversation_survives_client_restart_and_new_customer_message() -> None:
    async for first_client in app_client():
        agent = await create_agent(first_client, "Persistente", document_id="11223344")
        await post_whatsapp(first_client, "wamid.persist.initial", phone="573155827006")
        conversation = await latest_conversation()
        take = await first_client.post(
            f"/admin/conversations/{conversation.id}/take",
            headers=agent_headers(agent["token"]),
        )
        assert take.status_code == 200

    async for second_client in app_client():
        second_login = await second_client.post(
            "/admin/login",
            json={"document_id": "11223344", "pin": "123456"},
        )
        assert second_login.status_code == 200
        await post_whatsapp(
            second_client,
            "wamid.persist.after-restart",
            phone="573155827006",
            text="Sigo aquí",
        )
        mine = await second_client.get(
            "/admin/conversations?assigned_to_me=true",
            headers=agent_headers(second_login.json()["token"]),
        )
        assert mine.status_code == 200
        payload = mine.json()
        assert [row["id"] for row in payload] == [conversation.id]
        assert payload[0]["state"] == "HUMAN_ACTIVE"
        assert payload[0]["assigned_agent"] == {
            "id": agent["id"],
            "name": "Persistente",
            "role": "AGENT",
        }
        assert payload[0]["last_message_preview"] == "Sigo aquí"

        async with app.state.db_sessionmaker() as session:
            conversation_count = await session.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.customer_id == conversation.customer_id)
            )
        assert conversation_count == 1


@pytest.mark.asyncio
async def test_tc_take_009_return_direct_take_handoff_releases_agent(client: AsyncClient) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.take.return")
    conversation = await latest_conversation()
    take = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    handoff_id = take.json()["id"]

    returned = await client.post(
        f"/admin/handoffs/{handoff_id}/return",
        headers=agent_headers(agent["token"]),
        json={"resolution": "Atendido."},
    )

    assert returned.status_code == 200
    async with app.state.db_sessionmaker() as session:
        conversation_after = await session.get(Conversation, conversation.id)
        handoff_after = await session.get(Handoff, handoff_id)

    assert conversation_after is not None
    assert conversation_after.state == "BOT_ACTIVE"
    assert conversation_after.bot_enabled is True
    assert conversation_after.assigned_agent_id is None
    assert handoff_after is not None
    assert handoff_after.status == "RETURNED"
    assert handoff_after.assigned_agent_id is None


@pytest.mark.asyncio
async def test_tc_take_010_direct_take_resolved_reopens_with_audit(client: AsyncClient) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.take.resolved")
    conversation = await latest_conversation()
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            managed = await session.get(Conversation, conversation.id)
            assert managed is not None
            await transition_conversation(session, managed, ConversationState.RESOLVED, "TEST")

    response = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )

    assert response.status_code == 200
    async with app.state.db_sessionmaker() as session:
        reopened = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CONVERSATION_REOPENED")
        )
        conversation_after = await session.get(Conversation, conversation.id)

    assert reopened is not None
    assert conversation_after is not None
    assert conversation_after.state == "HUMAN_ACTIVE"


@pytest.mark.asyncio
async def test_tc_take_011_list_conversations_filters_paginates_and_orders(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client)
    await post_whatsapp(client, "wamid.list.old", phone="573001112236", text="Primero")
    first_conversation = await latest_conversation()
    await post_whatsapp(client, "wamid.list.new", phone="573001112237", text="Segundo")
    second_conversation = await latest_conversation()
    take = await client.post(
        f"/admin/conversations/{second_conversation.id}/take",
        headers=agent_headers(agent["token"]),
    )
    assert take.status_code == 200

    listed = await client.get("/admin/conversations", headers=agent_headers(agent["token"]))
    assert listed.status_code == 200
    payload = listed.json()
    assert [row["id"] for row in payload[:2]] == [second_conversation.id, first_conversation.id]
    assert payload[0]["customer_phone"] == "+573001112237"
    assert payload[0]["state"] == "HUMAN_ACTIVE"
    assert payload[0]["assigned_agent"] == {"id": agent["id"], "name": "Alexandra", "role": "AGENT"}
    assert "assignment_history" not in payload[0]
    history = await client.get(
        f"/admin/conversations/{second_conversation.id}/history",
        headers=agent_headers(agent["token"]),
    )
    assert history.status_code == 200
    assert history.json()[0]["actor"] == "Alexandra"
    assert history.json()[0]["action"] == "HANDOFF_TAKEN"
    assert "Motivo: MANUAL_TAKEOVER" in payload[0]["handoff_summary"]
    assert payload[0]["last_message_preview"] == "Segundo"
    assert payload[0]["last_message_at"] is not None

    mine = await client.get(
        "/admin/conversations?assigned_to_me=true",
        headers=agent_headers(agent["token"]),
    )
    assert mine.status_code == 200
    assert [row["id"] for row in mine.json()] == [second_conversation.id]

    bot_active = await client.get(
        "/admin/conversations?state=BOT_ACTIVE&limit=1&offset=0",
        headers=agent_headers(agent["token"]),
    )
    assert bot_active.status_code == 200
    assert len(bot_active.json()) == 1
    assert bot_active.json()[0]["id"] == first_conversation.id
