"""G2 B4 adversarial contracts: injected clock, real queues and mocked Meta HTTP."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy import select, text

from app.channel.inbound import record_provider_status
from app.channel.models import MessageProviderStatus
from app.channel.outbound import WhatsAppOutboundClient
from app.customer.models import Customer
from app.main import app
from app.notifications.models import StaffOutbox
from app.notifications.worker import process_staff_outbox_once
from tests.booking_balance.b4_helpers import (
    DUE,
    DUE_AT,
    EARLY,
    START,
    config,
    entries,
    pay_in_full,
    reload_reservation,
    reminder_contract,
    reserved,
)
from tests.staff_notifications.helpers import audits, recipient

META_URL = "https://graph.facebook.com/v20.0/balance-test/messages"
PARAMS = [
    "Ana",
    "Ritual del Corazón",
    "10 de octubre de 2026 a las 7:00 p. m.",
    "$200.000",
    "9 de octubre de 2026 a las 7:00 p. m.",
]


async def assert_http_outside_transaction() -> None:
    async with app.state.db_sessionmaker() as observer:
        count = await observer.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND xact_start IS NOT NULL"
            )
        )
    assert count == 0, "B4: Meta fue llamado dentro de una transacción abierta"


async def test_r1_two_reminders_exact_payload_bogota_and_flag_off(client):
    scheduler, process, model = reminder_contract()
    row = await reserved()
    sm = app.state.db_sessionmaker
    await scheduler(sm, config(BALANCE_REMINDERS_ENABLED=False), DUE_AT)
    assert await entries(model) == []
    assert await entries(StaffOutbox) == []
    assert await audits("RESERVATION_BALANCE_OVERDUE") == []
    await scheduler(sm, config(), EARLY - timedelta(seconds=1))
    assert await entries(model) == []

    payloads = []

    async def transport(request):
        await assert_http_outside_transaction()
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"balance.{len(payloads)}"}]})

    with respx.mock(assert_all_called=False) as router:
        router.post(META_URL).mock(side_effect=transport)
        async with WhatsAppOutboundClient(config()) as sender:
            for now, kind in (
                (EARLY, "BALANCE_REMINDER_EARLY"),
                (DUE, "BALANCE_REMINDER_DUE"),
            ):
                await scheduler(sm, config(), now)
                await scheduler(sm, config(), now + timedelta(minutes=5))
                await process(sm, sender, config(), now=now + timedelta(minutes=5))
                rows = await entries(model)
                assert sum(notification.kind == kind for notification in rows) == 1
                assert all(notification.status == "SENT" for notification in rows)
                assert all(notification.params == PARAMS for notification in rows)
    async with sm() as session:
        phone = await session.scalar(
            select(Customer.phone_number).where(Customer.id == row.customer_id)
        )
    expected = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "recordatorio_saldo_reserva",
            "language": {"code": "es"},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in PARAMS]}
            ],
        },
    }
    assert payloads == [expected, expected]


async def test_r2_fully_paid_before_due_produces_nothing(client):
    scheduler, _, model = reminder_contract()
    await reserved(amount_paid_cop=400000, payment_kind="FULL", balance_due_at=None)
    await scheduler(app.state.db_sessionmaker, config(), EARLY)
    await scheduler(app.state.db_sessionmaker, config(), DUE_AT)
    assert await entries(model) == []
    assert await audits("RESERVATION_BALANCE_OVERDUE") == []


async def test_r2_queued_reminder_expires_without_http_after_full_payment(client):
    scheduler, process, model = reminder_contract()
    row = await reserved()
    await scheduler(app.state.db_sessionmaker, config(), EARLY)
    assert len(await entries(model)) == 1
    await pay_in_full(row)
    sender = AsyncMock()
    await process(app.state.db_sessionmaker, sender, config(), now=EARLY)
    saved = (await entries(model))[0]
    assert saved.status == "EXPIRED"
    assert saved.claim_token is None and saved.claimed_at is None
    assert saved.provider_message_id is None
    sender.send_template.assert_not_awaited()
    sender.send_text.assert_not_awaited()


async def test_r3_late_booking_skips_early_once_and_sends_due(client):
    scheduler, process, model = reminder_contract()
    booked = START - timedelta(days=2)
    await reserved(reserved_at=booked)
    sm = app.state.db_sessionmaker
    await scheduler(sm, config(), booked)
    await scheduler(sm, config(), booked + timedelta(minutes=5))
    assert await entries(model) == []
    skipped = await audits("BALANCE_REMINDER_SKIPPED_LATE")
    assert len(skipped) == 1
    assert skipped[0].new_value["kind"] == "BALANCE_REMINDER_EARLY"
    await scheduler(sm, config(), DUE)
    assert [notification.kind for notification in await entries(model)] == ["BALANCE_REMINDER_DUE"]
    with respx.mock as router:
        router.post(META_URL).respond(200, json={"messages": [{"id": "balance.late.due"}]})
        async with WhatsAppOutboundClient(config()) as sender:
            await process(sm, sender, config(), now=DUE)
    assert (await entries(model))[0].status == "SENT"


async def test_r4_overdue_marks_once_and_notifies_active_evidence_recipients(client):
    scheduler, _, _ = reminder_contract()
    row = await reserved()
    active = await recipient(phone_number="+573000000121")
    also_active = await recipient(phone_number="+573000000122")
    await recipient(phone_number="+573000000123", active=False)
    await recipient(phone_number="+573000000124", notify_on_evidence=False)
    sm = app.state.db_sessionmaker
    await scheduler(sm, config(), DUE_AT)
    await scheduler(sm, config(), DUE_AT + timedelta(minutes=5))
    saved = await reload_reservation(row)
    assert saved.status == "RESERVED"
    assert saved.balance_overdue_at == DUE_AT
    assert len(await audits("RESERVATION_BALANCE_OVERDUE")) == 1
    notifications = await entries(StaffOutbox)
    assert len(notifications) == 2
    assert {notification.recipient_id for notification in notifications} == {
        active.id,
        also_active.id,
    }
    assert all(notification.event_kind == "BALANCE_OVERDUE" for notification in notifications)
    assert all(
        notification.params[1:] == [PARAMS[3], PARAMS[1], PARAMS[2]]
        for notification in notifications
    )
    with respx.mock as router:
        meta = router.post(META_URL).respond(
            200, json={"messages": [{"id": "staff.balance.overdue"}]}
        )
        async with WhatsAppOutboundClient(config()) as sender:
            await process_staff_outbox_once(sm, sender, config(), now=DUE_AT)
        assert meta.call_count == 2
        payload = json.loads(meta.calls[0].request.content)
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "aviso_saldo_vencido"


async def test_r5_missing_customer_template_does_not_enqueue_and_audits(client):
    scheduler, _, model = reminder_contract()
    await reserved()
    settings = config(CUSTOMER_TEMPLATE_BALANCE_REMINDER_NAME="")
    await scheduler(app.state.db_sessionmaker, settings, EARLY)
    await scheduler(app.state.db_sessionmaker, settings, EARLY + timedelta(minutes=5))
    assert await entries(model) == []
    assert len(await audits("BALANCE_REMINDER_NO_TEMPLATE")) == 1


@pytest.mark.parametrize(
    "status,code,expected", [(400, 132001, "FAILED"), (503, 131000, "PENDING")]
)
async def test_r5_provider_permanent_and_retryable_errors(client, status, code, expected):
    scheduler, process, model = reminder_contract()
    await reserved()
    sm = app.state.db_sessionmaker
    await scheduler(sm, config(), EARLY)
    with respx.mock as router:
        meta = router.post(META_URL).respond(
            status, json={"error": {"code": code, "message": "Fallo sintético"}}
        )
        async with WhatsAppOutboundClient(config()) as sender:
            await process(sm, sender, config(), now=EARLY)
            saved = (await entries(model))[0]
            assert saved.status == expected
            assert saved.attempts == 1 and saved.last_error_code == code
            assert saved.claim_token is None and saved.claimed_at is None
            await process(sm, sender, config(), now=EARLY + timedelta(seconds=1))
            assert meta.call_count == 1
            if expected == "PENDING":
                assert saved.next_attempt_at == EARLY + timedelta(seconds=2)
                meta.respond(200, json={"messages": [{"id": "balance.retry.success"}]})
                await process(sm, sender, config(), now=saved.next_attempt_at)
                assert (await entries(model))[0].status == "SENT"
                assert meta.call_count == 2
            else:
                await process(sm, sender, config(), now=EARLY + timedelta(days=1))
                assert meta.call_count == 1


@pytest.mark.parametrize("failed", [False, True])
async def test_r6_customer_statuses_use_null_message_and_are_deduplicated(client, failed):
    scheduler, process, model = reminder_contract()
    await reserved()
    sm = app.state.db_sessionmaker
    await scheduler(sm, config(), EARLY)
    provider_id = "balance.status.failed" if failed else "balance.status.progress"
    with respx.mock as router:
        router.post(META_URL).respond(200, json={"messages": [{"id": provider_id}]})
        async with WhatsAppOutboundClient(config()) as sender:
            await process(sm, sender, config(), now=EARLY)
    states = ("failed", "failed") if failed else ("delivered", "read", "delivered", "read")
    for state in states:
        payload = {"id": provider_id, "status": state, "timestamp": str(int(EARLY.timestamp()))}
        if failed:
            payload["errors"] = [{"code": 132001, "title": "Plantilla ausente"}]
        await record_provider_status(payload, sm)
    saved = (await entries(model))[0]
    assert saved.status == ("FAILED" if failed else "READ")
    statuses = await entries(MessageProviderStatus)
    assert len(statuses) == (1 if failed else 2)
    assert all(status.message_id is None for status in statuses)
    assert all(status.provider_message_id == provider_id for status in statuses)
    if failed:
        assert saved.last_error_code == 132001
