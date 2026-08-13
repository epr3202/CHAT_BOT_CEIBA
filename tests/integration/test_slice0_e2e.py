from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppOutboundClient
from app.channel.worker import process_outbox_once
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from tests.integration.helpers import (
    PHONE_NUMBER_ID,
    app_client,
    cleanup_test_environment,
    configure_test_environment,
    database_sessionmaker,
    signature,
    whatsapp_message_payload,
)


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async for sessionmaker in database_sessionmaker():
        yield sessionmaker


async def count_rows(sessionmaker_fixture: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sessionmaker_fixture() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def count_messages_by_direction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    direction: str,
) -> int:
    async with sessionmaker_fixture() as session:
        return (
            await session.scalar(
                select(func.count()).select_from(Message).where(Message.direction == direction)
            )
            or 0
        )


@pytest.mark.asyncio
@respx.mock
async def test_slice0_signed_webhook_to_worker_and_duplicate_absorption(
    client: AsyncClient,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    body = whatsapp_message_payload(
        message_id="wamid.slice0.inbound",
        phone="3001112233",
        text="Hola, quiero información",
    )

    webhook_response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )

    assert webhook_response.status_code == 200

    async with sessionmaker_fixture() as session:
        customer = await session.scalar(select(Customer))
        conversation = await session.scalar(select(Conversation))
        inbound_message = await session.scalar(
            select(Message).where(Message.direction == "INBOUND")
        )
        outbox = await session.scalar(select(Outbox))

    assert customer is not None
    assert customer.phone_number == "+573001112233"
    assert conversation is not None
    assert conversation.state == "BOT_ACTIVE"
    assert inbound_message is not None
    assert inbound_message.external_message_id == "wamid.slice0.inbound"
    assert outbox is not None
    assert outbox.status == "PENDING"

    respx.post(
        f"https://graph.facebook.com/{get_settings().meta_graph_api_version}/{PHONE_NUMBER_ID}/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "messages": [{"id": "wamid.slice0.outbound"}],
            },
        )
    )
    async with WhatsAppOutboundClient(get_settings()) as sender:
        processed = await process_outbox_once(sessionmaker_fixture, sender)

    assert processed == 1

    async with sessionmaker_fixture() as session:
        sent_outbox = await session.get(Outbox, outbox.id)
        outbound_message = await session.scalar(
            select(Message).where(Message.direction == "OUTBOUND")
        )

    assert sent_outbox is not None
    assert sent_outbox.status == "SENT"
    assert outbound_message is not None
    assert outbound_message.external_message_id == "wamid.slice0.outbound"

    duplicate_response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )

    assert duplicate_response.status_code == 200
    assert await count_rows(sessionmaker_fixture, Customer) == 1
    assert await count_rows(sessionmaker_fixture, Conversation) == 1
    assert await count_rows(sessionmaker_fixture, Outbox) == 1
    assert await count_messages_by_direction(sessionmaker_fixture, "INBOUND") == 1
    assert await count_messages_by_direction(sessionmaker_fixture, "OUTBOUND") == 1
    assert await count_rows(sessionmaker_fixture, AuditEvent) == 1
