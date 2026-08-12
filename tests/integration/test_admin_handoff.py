from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import IntentClassification
from app.channel.models import Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
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


def fake_classification(
    intent: str,
    *,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    confidence: float = 0.91,
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=confidence,
        entities={},
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=needs_human,
        handoff_reason=handoff_reason,
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


async def post_whatsapp(client: AsyncClient, message_id: str, text: str) -> None:
    body = whatsapp_message_payload(message_id, text=text)
    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )
    assert response.status_code == 200


async def count_outbox() -> int:
    async with app.state.db_sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(Outbox)) or 0


@pytest.mark.asyncio
async def test_list_handoffs_rejects_invalid_status(client: AsyncClient) -> None:
    response = await client.get("/admin/handoffs?status=RESOLVED", headers=admin_headers())

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_full_handoff_cycle_returns_control_to_bot(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_classifier(
        monkeypatch,
        fake_classification(
            "HUMAN_REQUEST",
            needs_human=True,
            handoff_reason="CUSTOMER_REQUEST",
        ),
    )
    await post_whatsapp(client, "wamid.handoff.full.1", "Quiero hablar con un asesor")

    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            customer = await session.scalar(
                select(Customer).where(Customer.phone_number == "+573001112233")
            )
            assert customer is not None
            customer.full_name = "Natalia Perez"

    pending = await client.get("/admin/handoffs", headers=admin_headers())
    assert pending.status_code == 200
    handoff = pending.json()[0]
    handoff_id = handoff["id"]
    conversation_id = handoff["conversation_id"]
    assert handoff["status"] == "PENDING"
    assert handoff["customer_name"] == "Natalia Perez"
    assert handoff["customer_phone"] == "+573001112233"

    await post_whatsapp(client, "wamid.handoff.full.2", "Sigo esperando")
    assert await count_outbox() == 1

    take = await client.post(
        f"/admin/handoffs/{handoff_id}/take",
        headers=admin_headers(),
        json={"agent": "Alexandra"},
    )
    assert take.status_code == 200

    async with app.state.db_sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.state == "HUMAN_ACTIVE"
    assert conversation.bot_enabled is False

    agent_message = await client.post(
        f"/admin/conversations/{conversation_id}/messages",
        headers=admin_headers(),
        json={"text": "Hola, soy Alexandra. Ya reviso tu solicitud."},
    )
    assert agent_message.status_code == 200
    assert await count_outbox() == 2

    returned = await client.post(
        f"/admin/handoffs/{handoff_id}/return",
        headers=admin_headers(),
        json={"resolution": "Cliente atendido y devuelto al bot."},
    )
    assert returned.status_code == 200

    async with app.state.db_sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
        handoff_after_return = await session.get(Handoff, handoff_id)
    assert conversation is not None
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.bot_enabled is True
    assert handoff_after_return is not None
    assert handoff_after_return.status == "RETURNED"

    mock_classifier(monkeypatch, fake_classification("GREETING"))
    await post_whatsapp(client, "wamid.handoff.full.3", "Hola de nuevo")
    assert await count_outbox() == 3


@pytest.mark.asyncio
async def test_concurrent_take_allows_only_one_agent(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_classifier(
        monkeypatch,
        fake_classification(
            "HUMAN_REQUEST",
            needs_human=True,
            handoff_reason="CUSTOMER_REQUEST",
        ),
    )
    await post_whatsapp(client, "wamid.handoff.concurrent.1", "Necesito un asesor")

    pending = await client.get("/admin/handoffs", headers=admin_headers())
    handoff_id = pending.json()[0]["id"]

    first, second = await asyncio.gather(
        client.post(
            f"/admin/handoffs/{handoff_id}/take",
            headers=admin_headers(),
            json={"agent": "Agente A"},
        ),
        client.post(
            f"/admin/handoffs/{handoff_id}/take",
            headers=admin_headers(),
            json={"agent": "Agente B"},
        ),
    )
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409]

    async with app.state.db_sessionmaker() as session:
        handoff = await session.get(Handoff, handoff_id)
        conversation = await session.get(Conversation, handoff.conversation_id)

    assert handoff is not None
    assert handoff.status == "TAKEN"
    assert handoff.assigned_to in {"Agente A", "Agente B"}
    assert conversation is not None
    assert conversation.state == "HUMAN_ACTIVE"
    assert conversation.bot_enabled is False


@pytest.mark.asyncio
async def test_outside_human_hours_uses_off_hours_template(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_classifier(
        monkeypatch,
        fake_classification(
            "HUMAN_REQUEST",
            needs_human=True,
            handoff_reason="CUSTOMER_REQUEST",
        ),
    )
    monkeypatch.setattr(
        "app.handoff.service.is_human_business_hours",
        lambda *_args, **_kwargs: False,
    )

    await post_whatsapp(client, "wamid.handoff.offhours.1", "Asesor")

    async with app.state.db_sessionmaker() as session:
        outbox = await session.scalar(select(Outbox))

    assert outbox is not None
    assert "dentro de nuestro horario de atención" in outbox.payload["text"]["body"]
