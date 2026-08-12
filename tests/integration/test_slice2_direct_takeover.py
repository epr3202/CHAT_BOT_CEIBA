from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.agent.models import Agent
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
    ADMIN_API_TOKEN,
    app_client,
    cleanup_test_environment,
    configure_test_environment,
    signature,
    whatsapp_message_payload,
)


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_API_TOKEN}"}


def agent_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
) -> dict[str, Any]:
    body = {"name": name}
    if document_id is not None:
        body["document_id"] = document_id
    response = await client.post("/admin/agents", headers=admin_headers(), json=body)
    assert response.status_code == 200
    return response.json()


async def latest_conversation() -> Conversation:
    async with app.state.db_sessionmaker() as session:
        conversation = await session.scalar(select(Conversation).order_by(Conversation.id.desc()))
        assert conversation is not None
        return conversation


async def count_rows(model: type) -> int:
    async with app.state.db_sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.asyncio
async def test_tc_agent_001_create_agent_returns_plain_token_once_and_stores_hash(
    client: AsyncClient,
) -> None:
    payload = await create_agent(client, "Alexandra")

    assert payload["id"]
    assert payload["name"] == "Alexandra"
    assert len(payload["token"]) >= 32

    async with app.state.db_sessionmaker() as session:
        agent = await session.get(Agent, payload["id"])
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "AGENT_CREATED"))

    assert agent is not None
    assert agent.token_hash == hashlib.sha256(payload["token"].encode()).hexdigest()
    assert agent.token_hash != payload["token"]
    assert audit is not None
    assert payload["token"] not in str(audit.new_value)
    assert agent.token_hash not in str(audit.new_value)

    listed = await client.get("/admin/agents", headers=admin_headers())
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]


@pytest.mark.asyncio
async def test_tc_agent_002_invalid_agent_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/admin/me", headers=agent_headers("invalid-token"))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tc_agent_create_with_document_id_uses_document_as_agent_token(
    client: AsyncClient,
) -> None:
    document_id = "1020304050"

    payload = await create_agent(client, "Emerson", document_id=document_id)

    assert payload["token"] == document_id

    async with app.state.db_sessionmaker() as session:
        agent = await session.get(Agent, payload["id"])

    assert agent is not None
    assert agent.token_hash == hashlib.sha256(document_id.encode()).hexdigest()
    assert agent.token_hash != document_id

    me = await client.get("/admin/me", headers=agent_headers(document_id))
    assert me.status_code == 200
    assert me.json() == {"id": payload["id"], "name": "Emerson"}


@pytest.mark.asyncio
async def test_tc_agent_003_deactivated_agent_returns_403(client: AsyncClient) -> None:
    agent = await create_agent(client, "Inactive")

    deactivate = await client.post(
        f"/admin/agents/{agent['id']}/deactivate",
        headers=admin_headers(),
    )
    assert deactivate.status_code == 200

    response = await client.get("/admin/me", headers=agent_headers(agent["token"]))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tc_agent_004_admin_token_does_not_identify_agent_for_take(
    client: AsyncClient,
) -> None:
    await create_agent(client, "Alexandra")
    await post_whatsapp(client, "wamid.agent.admin-not-agent")
    conversation = await latest_conversation()

    response = await client.post(
        f"/admin/conversations/{conversation.id}/take",
        headers=admin_headers(),
    )

    assert response.status_code == 401


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
    assert payload[0]["assigned_agent"] == {"id": agent["id"], "name": "Alexandra"}
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
