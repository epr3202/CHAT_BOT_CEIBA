"""B4 callbacks and inbound messages must not invert scheduled queue locks."""

import asyncio
import json
from contextlib import suppress
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel import inbound
from app.channel.models import Message, MessageProviderStatus
from app.customer.models import Customer
from app.main import app
from app.notifications.models import StaffOutbox
from app.reservation.models import Reservation
from tests.booking_balance.b4_helpers import (
    DUE_AT,
    EARLY,
    config,
    entries,
    reminder_contract,
    reserved,
)
from tests.integration.helpers import whatsapp_message_payload
from tests.staff_notifications.helpers import recipient


@pytest.mark.parametrize("queue_kind", ["customer", "staff"])
async def test_status_and_client_payload_does_not_block_scheduler_reprocessing(
    client: Any, monkeypatch: pytest.MonkeyPatch, queue_kind: str
) -> None:
    scheduler, _, customer_notification = reminder_contract()
    reservation = await reserved()
    sm = app.state.db_sessionmaker
    if queue_kind == "customer":
        now, model = EARLY, customer_notification
        await scheduler(sm, config(), now)
    else:
        await recipient(phone_number="+573000000175")
        now, model = DUE_AT, StaffOutbox
        await scheduler(sm, config(), now)
    notification = (await entries(model))[0]
    provider_id = f"balance.callback.{queue_kind}"
    async with sm.begin() as session:
        row = await session.get(model, notification.id)
        row.status, row.provider_message_id = "SENT", provider_id
        customer = await session.get(Customer, reservation.customer_id)
        phone = customer.phone_number
        if queue_kind == "staff":
            # A human reschedule resets overdue marking, while the source identity
            # and its already-sent staff notice remain unchanged.
            booking = await session.get(Reservation, reservation.reservation_id)
            booking.starts_at += timedelta(days=7)
            booking.ends_at += timedelta(days=7)
            booking.balance_due_at += timedelta(days=7)
            booking.balance_overdue_at = None
            now += timedelta(days=7)

    external_id = f"balance.callback.inbound.{queue_kind}"
    payload = json.loads(whatsapp_message_payload(external_id, phone=phone.lstrip("+")))
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["timestamp"] = str(int(now.timestamp()))
    value["statuses"] = [
        {"id": provider_id, "status": "delivered", "timestamp": str(int(now.timestamp()))}
    ]
    status_applied, proceed_to_customer = asyncio.Event(), asyncio.Event()
    real_customer_lookup = inbound.get_or_create_customer

    async def pause_before_customer(session: AsyncSession, phone_number: str) -> Customer:
        # Real phase A processes the callback first in this same transaction.
        # Its updated queue row remains locked after releasing the status savepoint.
        status_applied.set()
        await proceed_to_customer.wait()
        return await real_customer_lookup(session, phone_number)

    monkeypatch.setattr(inbound, "get_or_create_customer", pause_before_customer)
    scan = None
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        callback = asyncio.create_task(inbound.persist_payload_phase_a(payload, sm, uuid4()))
        ready = asyncio.create_task(status_applied.wait())
        try:
            done, _ = await asyncio.wait({ready}, timeout=2)
            assert ready in done, "B4: el payload no llegó al cliente después de su status"
            scan = asyncio.create_task(scheduler(sm, config(), now + timedelta(minutes=5)))
            done, _ = await asyncio.wait({scan}, timeout=2)
            assert scan in done, (
                "B4: el programador espera la fila actualizada por un callback que debe "
                "continuar al Customer; reinsertar su fuente existente invierte los locks"
            )
            assert await scan == 0
            proceed_to_customer.set()
            done, _ = await asyncio.wait({callback}, timeout=2)
            assert callback in done, "B4: el mensaje cliente quedó bloqueado tras el callback"
            assert len(await callback) == 1
        finally:
            if scan is not None:
                if not scan.done():
                    scan.cancel()
                with suppress(asyncio.CancelledError):
                    await scan
            if not ready.done():
                ready.cancel()
            with suppress(asyncio.CancelledError):
                await ready
            proceed_to_customer.set()
            if not callback.done():
                callback.cancel()
            with suppress(asyncio.CancelledError):
                await callback
        assert not router.calls

    queued = await entries(model)
    assert len(queued) == 1 and queued[0].status == "DELIVERED"
    statuses = await entries(MessageProviderStatus)
    assert len(statuses) == 1 and statuses[0].message_id is None
    async with sm() as session:
        message = await session.scalar(
            select(Message).where(Message.external_message_id == external_id)
        )
        assert message is not None and message.customer_id == reservation.customer_id
