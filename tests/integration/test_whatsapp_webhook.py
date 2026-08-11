import json
from collections.abc import AsyncIterator

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy import func, select
from starlette.requests import Request

from app.audit.models import AuditEvent
from app.channel import inbound
from app.channel.inbound import process_webhook_event, store_webhook_event
from app.channel.models import Message, Outbox, WebhookEvent
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.main import app
from tests.integration.helpers import (
    VERIFY_TOKEN,
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


async def count_rows(model: type) -> int:
    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


def build_request(body: bytes) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/webhook",
            "headers": [],
            "app": app,
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_get_webhook_valid_token_returns_challenge(client: AsyncClient) -> None:
    response = await client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-123"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_get_webhook_invalid_token_returns_403(client: AsyncClient) -> None:
    response = await client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_invalid_signature_returns_403_and_no_message(client: AsyncClient) -> None:
    body = whatsapp_message_payload("wamid.invalid")

    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )

    assert response.status_code == 403
    assert await count_rows(Message) == 0


@pytest.mark.asyncio
async def test_post_oversized_body_returns_413_and_has_no_database_effects(
    client: AsyncClient,
) -> None:
    body = b'{"oversized":"' + (b"x" * 1_048_577) + b'"}'

    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )

    assert response.status_code == 413
    assert await count_rows(WebhookEvent) == 0
    assert await count_rows(Customer) == 0
    assert await count_rows(Conversation) == 0
    assert await count_rows(Message) == 0
    assert await count_rows(Outbox) == 0
    assert await count_rows(AuditEvent) == 0


@pytest.mark.asyncio
async def test_post_valid_persists_received_webhook_event_before_background() -> None:
    from app.channel.webhook import receive_webhook

    body = whatsapp_message_payload("wamid.inbox.received")

    async with app.router.lifespan_context(app):
        response = await receive_webhook(
            build_request(body),
            BackgroundTasks(),
            x_hub_signature_256=signature(body),
            content_length=None,
            x_request_id="req-inbox-received",
        )

        async_sessionmaker = app.state.db_sessionmaker
        async with async_sessionmaker() as session:
            webhook_event = await session.scalar(select(WebhookEvent))

        assert response.status_code == 200
        assert webhook_event is not None
        assert webhook_event.status == "RECEIVED"
        assert webhook_event.request_id == "req-inbox-received"
        assert await count_rows(Message) == 0
        assert await count_rows(Outbox) == 0


@pytest.mark.asyncio
async def test_post_valid_message_creates_pipeline_rows(client: AsyncClient) -> None:
    body = whatsapp_message_payload("wamid.first")

    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )

    assert response.status_code == 200
    assert await count_rows(Customer) == 1
    assert await count_rows(Conversation) == 1
    assert await count_rows(Message) == 1
    assert await count_rows(Outbox) == 1


@pytest.mark.asyncio
async def test_pipeline_creates_new_conversation_then_audits_transition(
    client: AsyncClient,
) -> None:
    body = whatsapp_message_payload("wamid.state.transition")

    response = await client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature(body)},
    )

    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        conversation = await session.scalar(select(Conversation))
        audit_event = await session.scalar(select(AuditEvent))

    assert response.status_code == 200
    assert conversation is not None
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.channel == "WHATSAPP"
    assert audit_event is not None
    assert audit_event.actor == "SYSTEM"
    assert audit_event.action == "CONVERSATION_STATE_TRANSITION"
    assert audit_event.old_value == {"conversation_id": conversation.id, "state": "NEW"}
    assert audit_event.new_value == {"conversation_id": conversation.id, "state": "BOT_ACTIVE"}


@pytest.mark.asyncio
async def test_process_webhook_event_success_marks_processed_and_runs_pipeline(
    client: AsyncClient,
) -> None:
    body = whatsapp_message_payload("wamid.inbox.processed")

    webhook_event_id = await store_webhook_event(
        json.loads(body),
        app.state.db_sessionmaker,
        request_id="req-inbox-processed",
    )

    await process_webhook_event(webhook_event_id, app.state.db_sessionmaker)

    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        webhook_event = await session.get(WebhookEvent, webhook_event_id)

    assert webhook_event is not None
    assert webhook_event.status == "PROCESSED"
    assert webhook_event.processed_at is not None
    assert await count_rows(Customer) == 1
    assert await count_rows(Conversation) == 1
    assert await count_rows(Message) == 1
    assert await count_rows(Outbox) == 1


@pytest.mark.asyncio
async def test_process_webhook_event_exception_marks_failed_without_partial_rows(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_after_customer(*args: object, **kwargs: object) -> Conversation:
        raise RuntimeError("forced pipeline failure")

    body = whatsapp_message_payload("wamid.inbox.failed")
    webhook_event_id = await store_webhook_event(
        json.loads(body),
        app.state.db_sessionmaker,
        request_id="req-inbox-failed",
    )
    monkeypatch.setattr(inbound, "get_or_create_active_conversation", raise_after_customer)

    await process_webhook_event(webhook_event_id, app.state.db_sessionmaker)

    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        webhook_event = await session.get(WebhookEvent, webhook_event_id)

    assert webhook_event is not None
    assert webhook_event.status == "FAILED"
    assert webhook_event.error == "forced pipeline failure"
    assert await count_rows(Message) == 0
    assert await count_rows(Outbox) == 0


@pytest.mark.asyncio
async def test_reprocess_processed_webhook_event_creates_no_new_rows(client: AsyncClient) -> None:
    body = whatsapp_message_payload("wamid.inbox.reprocess")
    webhook_event_id = await store_webhook_event(
        json.loads(body),
        app.state.db_sessionmaker,
        request_id="req-inbox-reprocess",
    )

    await process_webhook_event(webhook_event_id, app.state.db_sessionmaker)
    await process_webhook_event(webhook_event_id, app.state.db_sessionmaker)

    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        webhook_event = await session.get(WebhookEvent, webhook_event_id)

    assert webhook_event is not None
    assert webhook_event.status == "PROCESSED"
    assert await count_rows(Customer) == 1
    assert await count_rows(Conversation) == 1
    assert await count_rows(Message) == 1
    assert await count_rows(Outbox) == 1


@pytest.mark.asyncio
async def test_process_duplicate_message_webhook_event_marks_processed_without_new_rows(
    client: AsyncClient,
) -> None:
    body = whatsapp_message_payload("wamid.inbox.duplicate-event")
    first_event_id = await store_webhook_event(
        json.loads(body),
        app.state.db_sessionmaker,
        request_id="req-inbox-duplicate-first",
    )
    duplicate_event_id = await store_webhook_event(
        json.loads(body),
        app.state.db_sessionmaker,
        request_id="req-inbox-duplicate-second",
    )

    await process_webhook_event(first_event_id, app.state.db_sessionmaker)
    await process_webhook_event(duplicate_event_id, app.state.db_sessionmaker)

    async_sessionmaker = app.state.db_sessionmaker
    async with async_sessionmaker() as session:
        duplicate_event = await session.get(WebhookEvent, duplicate_event_id)

    assert duplicate_event is not None
    assert duplicate_event.status == "PROCESSED"
    assert duplicate_event.error is None
    assert await count_rows(Customer) == 1
    assert await count_rows(Conversation) == 1
    assert await count_rows(Message) == 1
    assert await count_rows(Outbox) == 1


@pytest.mark.asyncio
async def test_post_duplicate_payload_creates_one_message_and_one_outbox(
    client: AsyncClient,
) -> None:
    body = whatsapp_message_payload("wamid.duplicate")
    headers = {"X-Hub-Signature-256": signature(body)}

    first_response = await client.post("/webhook", content=body, headers=headers)
    second_response = await client.post("/webhook", content=body, headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert await count_rows(Message) == 1
    assert await count_rows(Outbox) == 1


@pytest.mark.asyncio
async def test_second_message_same_customer_reuses_customer_and_conversation(
    client: AsyncClient,
) -> None:
    first_body = whatsapp_message_payload("wamid.one")
    second_body = whatsapp_message_payload("wamid.two", text="Otra pregunta")

    await client.post(
        "/webhook",
        content=first_body,
        headers={"X-Hub-Signature-256": signature(first_body)},
    )
    await client.post(
        "/webhook",
        content=second_body,
        headers={"X-Hub-Signature-256": signature(second_body)},
    )

    assert await count_rows(Customer) == 1
    assert await count_rows(Conversation) == 1
    assert await count_rows(Message) == 2
    assert await count_rows(Outbox) == 2
