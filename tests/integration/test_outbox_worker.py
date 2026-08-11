from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppOutboundClient
from app.channel.states import Channel
from app.channel.worker import process_outbox_once
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from tests.integration.helpers import (
    PHONE_NUMBER_ID,
    cleanup_test_environment,
    configure_test_environment,
    database_sessionmaker,
)


class BlockingSender:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def send_text(self, to: str, body: str) -> str:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return "wamid.concurrent"


class SequencedSender:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def send_text(self, to: str, body: str) -> str:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async for sessionmaker in database_sessionmaker():
        yield sessionmaker


async def seed_pending_outbox(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    attempts: int = 0,
    suffix: str | None = None,
    status: str = "PENDING",
    next_attempt_at: datetime | None = None,
    claimed_at: datetime | None = None,
    created_at: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> int:
    suffix = suffix or str(attempts)
    phone_suffix = sum(ord(character) for character in suffix) % 10000
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer = Customer(phone_number=f"+5730011{phone_suffix:04d}")
            session.add(customer)
            await session.flush()

            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
            )
            session.add(conversation)
            await session.flush()

            inbound_message = Message(
                external_message_id=f"wamid.inbound.{suffix}",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": "Hola"}},
                provider_timestamp=None,
            )
            session.add(inbound_message)
            await session.flush()

            outbox = Outbox(
                conversation_id=conversation.id,
                message_id=inbound_message.id,
                channel=Channel.WHATSAPP,
                recipient_phone_number=customer.phone_number,
                payload=payload
                if payload is not None
                else {"type": "text", "text": {"body": f"Respuesta {suffix}"}},
                status=status,
                attempts=attempts,
                next_attempt_at=next_attempt_at,
                claimed_at=claimed_at,
                created_at=created_at or datetime.now(UTC) - timedelta(minutes=10),
            )
            session.add(outbox)
            await session.flush()
            return outbox.id


async def count_rows(sessionmaker_fixture: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sessionmaker_fixture() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.asyncio
@respx.mock
async def test_pending_outbox_becomes_sent_and_creates_outbound_message(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    outbox_id = await seed_pending_outbox(sessionmaker_fixture)
    settings = get_settings()
    respx.post(
        f"https://graph.facebook.com/{settings.meta_graph_api_version}/{PHONE_NUMBER_ID}/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "messages": [{"id": "wamid.outbound.1"}],
            },
        )
    )

    async with WhatsAppOutboundClient(settings) as sender:
        processed = await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)
        outbound_message = await session.scalar(
            select(Message).where(Message.direction == "OUTBOUND")
        )

    assert processed == 1
    assert outbox is not None
    assert outbox.status == "SENT"
    assert outbox.sent_at is not None
    assert outbox.claimed_at is None
    assert outbox.next_attempt_at is None
    assert outbound_message is not None
    assert outbound_message.external_message_id == "wamid.outbound.1"


@pytest.mark.asyncio
@respx.mock
async def test_meta_500_increments_attempts_and_keeps_pending(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    outbox_id = await seed_pending_outbox(sessionmaker_fixture)
    settings = get_settings()
    respx.post(
        f"https://graph.facebook.com/{settings.meta_graph_api_version}/{PHONE_NUMBER_ID}/messages"
    ).mock(return_value=httpx.Response(500, json={"error": {"message": "Meta error"}}))

    async with WhatsAppOutboundClient(settings) as sender:
        processed = await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)

    assert processed == 1
    assert outbox is not None
    assert outbox.status == "PENDING"
    assert outbox.attempts == 1
    assert outbox.last_error is not None
    assert outbox.next_attempt_at is not None
    assert outbox.next_attempt_at > datetime.now(UTC)


@pytest.mark.asyncio
@respx.mock
async def test_fifth_failure_marks_failed_and_creates_audit_event(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    outbox_id = await seed_pending_outbox(sessionmaker_fixture, attempts=4)
    settings = get_settings()
    respx.post(
        f"https://graph.facebook.com/{settings.meta_graph_api_version}/{PHONE_NUMBER_ID}/messages"
    ).mock(return_value=httpx.Response(500, json={"error": {"message": "Meta error"}}))

    async with WhatsAppOutboundClient(settings) as sender:
        processed = await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)
        audit_event = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "WHATSAPP_OUTBOX_SEND_FAILED")
        )

    assert processed == 1
    assert outbox is not None
    assert outbox.status == "FAILED"
    assert outbox.attempts == 5
    assert outbox.next_attempt_at is None
    assert audit_event is not None


@pytest.mark.asyncio
async def test_future_next_attempt_is_not_claimed_and_past_attempt_is_claimed_once(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    future_now = datetime.now(UTC)
    outbox_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="future",
        next_attempt_at=future_now + timedelta(minutes=5),
    )
    sender = SequencedSender(["wamid.future"])

    processed = await process_outbox_once(sessionmaker_fixture, sender, now=future_now)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)

    assert processed == 0
    assert sender.calls == 0
    assert outbox is not None
    assert outbox.status == "PENDING"

    async with sessionmaker_fixture() as session:
        async with session.begin():
            outbox = await session.get(Outbox, outbox_id)
            assert outbox is not None
            outbox.next_attempt_at = future_now - timedelta(seconds=1)

    sender = BlockingSender()
    first_worker = asyncio.create_task(
        process_outbox_once(sessionmaker_fixture, sender, now=future_now)
    )
    await sender.started.wait()
    second_processed = await process_outbox_once(sessionmaker_fixture, sender, now=future_now)
    sender.release.set()
    first_processed = await first_worker

    assert first_processed == 1
    assert second_processed == 0
    assert sender.calls == 1


@pytest.mark.asyncio
async def test_batch_failure_settles_per_item_without_rolling_back_successes(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC) - timedelta(minutes=10)
    first_id = await seed_pending_outbox(sessionmaker_fixture, suffix="batch01", created_at=now)
    second_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="batch02",
        created_at=now + timedelta(seconds=1),
    )
    third_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="batch03",
        created_at=now + timedelta(seconds=2),
    )
    sender = SequencedSender(
        [
            "wamid.batch.outbound.1",
            RuntimeError("unexpected send failure"),
            "wamid.batch.outbound.3",
        ]
    )

    processed = await process_outbox_once(sessionmaker_fixture, sender, batch_size=3)

    async with sessionmaker_fixture() as session:
        first = await session.get(Outbox, first_id)
        second = await session.get(Outbox, second_id)
        third = await session.get(Outbox, third_id)
        outbound_count = await session.scalar(
            select(func.count()).select_from(Message).where(Message.direction == "OUTBOUND")
        )

    assert processed == 3
    assert first is not None
    assert first.status == "SENT"
    assert third is not None
    assert third.status == "SENT"
    assert outbound_count == 2
    assert second is not None
    assert second.status == "PENDING"
    assert second.attempts == 1
    assert second.next_attempt_at is not None
    assert second.next_attempt_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_stale_sending_row_is_recovered_by_reaper(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    outbox_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="stale",
        status="SENDING",
        claimed_at=now - timedelta(minutes=5),
    )
    sender = SequencedSender([])

    processed = await process_outbox_once(
        sessionmaker_fixture,
        sender,
        now=now,
        sending_timeout_seconds=120,
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)

    assert processed == 0
    assert sender.calls == 0
    assert outbox is not None
    assert outbox.status == "PENDING"
    assert outbox.attempts == 1
    assert outbox.claimed_at is None
    assert outbox.next_attempt_at == now + timedelta(seconds=2)


@pytest.mark.asyncio
async def test_stale_sending_row_at_attempt_limit_fails_with_audit_event(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    outbox_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="stale-limit",
        status="SENDING",
        attempts=4,
        claimed_at=now - timedelta(minutes=5),
    )
    sender = SequencedSender([])

    processed = await process_outbox_once(
        sessionmaker_fixture,
        sender,
        now=now,
        sending_timeout_seconds=120,
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)
        audit_event = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "WHATSAPP_OUTBOX_SEND_FAILED")
        )

    assert processed == 0
    assert sender.calls == 0
    assert outbox is not None
    assert outbox.status == "FAILED"
    assert outbox.attempts == 5
    assert outbox.claimed_at is None
    assert outbox.next_attempt_at is None
    assert outbox.last_error == "stale SENDING recovered by reaper"
    assert audit_event is not None
    assert audit_event.new_value == {
        "outbox_id": outbox_id,
        "attempts": 5,
        "status": "FAILED",
    }


@pytest.mark.asyncio
async def test_malformed_payload_failure_does_not_block_claimed_batch_and_fails_after_retries(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC) - timedelta(minutes=10)
    first_id = await seed_pending_outbox(sessionmaker_fixture, suffix="malformed01", created_at=now)
    second_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="malformed02",
        created_at=now + timedelta(seconds=1),
        payload={"type": "text"},
    )
    third_id = await seed_pending_outbox(
        sessionmaker_fixture,
        suffix="malformed03",
        created_at=now + timedelta(seconds=2),
    )
    sender = SequencedSender(["wamid.malformed.outbound.1", "wamid.malformed.outbound.3"])

    processed = await process_outbox_once(sessionmaker_fixture, sender, batch_size=3)

    async with sessionmaker_fixture() as session:
        first = await session.get(Outbox, first_id)
        second = await session.get(Outbox, second_id)
        third = await session.get(Outbox, third_id)
        sending_count = await session.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.status == "SENDING")
        )
        outbound_count = await session.scalar(
            select(func.count()).select_from(Message).where(Message.direction == "OUTBOUND")
        )

    assert processed == 3
    assert sender.calls == 2
    assert first is not None
    assert first.status == "SENT"
    assert third is not None
    assert third.status == "SENT"
    assert outbound_count == 2
    assert second is not None
    assert second.status == "PENDING"
    assert second.attempts == 1
    assert second.last_error == f"Outbox {second_id} does not contain text.body"
    assert second.next_attempt_at is not None
    assert second.next_attempt_at > datetime.now(UTC)
    assert sending_count == 0

    retry_now = datetime.now(UTC) + timedelta(minutes=10)
    for _ in range(4):
        processed = await process_outbox_once(
            sessionmaker_fixture,
            sender,
            now=retry_now,
            batch_size=3,
        )
        assert processed == 1

    async with sessionmaker_fixture() as session:
        second = await session.get(Outbox, second_id)
        sending_count = await session.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.status == "SENDING")
        )
        audit_event = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "WHATSAPP_OUTBOX_SEND_FAILED")
        )

    assert second is not None
    assert second.status == "FAILED"
    assert second.attempts == 5
    assert second.next_attempt_at is None
    assert sending_count == 0
    assert audit_event is not None


@pytest.mark.asyncio
async def test_two_concurrent_workers_send_one_message_with_skip_locked(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await seed_pending_outbox(sessionmaker_fixture, suffix="concurrent")
    sender = BlockingSender()

    first_worker = asyncio.create_task(process_outbox_once(sessionmaker_fixture, sender))
    await sender.started.wait()
    second_processed = await process_outbox_once(sessionmaker_fixture, sender)
    sender.release.set()
    first_processed = await first_worker

    assert first_processed == 1
    assert second_processed == 0
    assert sender.calls == 1
    assert await count_rows(sessionmaker_fixture, Message) == 2
    assert await count_rows(sessionmaker_fixture, Outbox) == 1
