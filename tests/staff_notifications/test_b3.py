import json
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy import func, select, text

from app.channel.inbound import process_whatsapp_webhook, record_provider_status
from app.channel.models import InboxJob, Message, MessageProviderStatus, Outbox
from app.channel.outbound import WhatsAppOutboundClient, WhatsAppSendError
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.main import app
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.b1a_contracts import require_symbol
from tests.booking_backend.helpers import plan
from tests.booking_backend.helpers import settings as base_settings
from tests.integration.helpers import login_headers, whatsapp_message_payload
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation
from tests.staff_notifications.helpers import (
    NOW,
    PHONE,
    audits,
    fresh,
    models,
    outbox,
    recipient,
    rows,
)


def settings(**changes):
    return base_settings(META_PHONE_NUMBER_ID="staff-test", **changes)


@pytest.mark.parametrize("enabled", [True, False])
async def test_tc_b3_001_002_003_evidence_atomic_deduplicated(client, monkeypatch, enabled):
    _, model = models()
    await recipient()
    await recipient(phone_number="+573000000124")
    await recipient(phone_number="+573000000125", active=False)
    await recipient(phone_number="+573000000126", notify_on_evidence=False)
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", str(enabled).lower())
    get_settings.cache_clear()
    reservation = await seed_reservation()
    async with app.state.db_sessionmaker() as session:
        customer = await session.get(Customer, reservation.customer_id)
        phone = customer.phone_number
    enqueue = require_symbol("app.notifications.service", "enqueue_for_reservation")
    observations = []

    async def observed(session, **kwargs):
        assert session.in_transaction(), "El encolado debe compartir la transacción de negocio"
        evidence = await session.scalar(select(PaymentEvidence))
        linked = await session.get(Reservation, reservation.reservation_id)
        assert evidence.reservation_id == linked.reservation_id
        assert linked.status == "PAYMENT_REVIEW"
        async with app.state.db_sessionmaker() as observer:
            assert await observer.scalar(select(func.count()).select_from(PaymentEvidence)) == 0
            assert (
                await observer.get(Reservation, linked.reservation_id)
            ).status == "PAYMENT_PENDING"
        observations.append(True)
        return await enqueue(session, **kwargs)

    monkeypatch.setattr("app.notifications.service.enqueue_for_reservation", observed)
    payload = json.loads(
        whatsapp_message_payload("staff.evidence.1", phone=phone.removeprefix("+"))
    )
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message.update(
        type="image", image={"id": "media-test", "mime_type": "image/jpeg", "sha256": "0" * 64}
    )
    await process_whatsapp_webhook(payload, app.state.db_sessionmaker)
    assert observations
    assert len(await rows(model)) == (2 if enabled else 0)
    before = await audits("STAFF_NOTIFICATION_ENQUEUED")
    await process_whatsapp_webhook(payload, app.state.db_sessionmaker)
    assert len(await rows(model)) == (2 if enabled else 0)
    assert len(await audits("STAFF_NOTIFICATION_ENQUEUED")) == len(before)


async def test_tc_b3_004_pending_atomic(client):
    _, model = models()
    await recipient(notify_on_payment_pending=True)
    await recipient(phone_number="+573000000124", notify_on_payment_pending=False)
    reservation = await seed_reservation()
    enqueue = require_symbol("app.notifications.service", "enqueue_for_reservation")
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, reservation.reservation_id)
        await enqueue(
            session,
            reservation=saved,
            event_kind="PAYMENT_PENDING_CREATED",
            source_entity="reservation",
            source_id=str(saved.reservation_id),
            settings=get_settings(),
            request_id="tc-b3-004",
        )
        assert len(list(await session.scalars(select(model)))) == 1
        await session.rollback()
    assert await rows(model) == [], "Rollback del negocio debe retirar también el aviso y su audit"
    assert await audits("STAFF_NOTIFICATION_ENQUEUED") == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a\n b\t c\r d", "a b c d"),
        ("  a    b  ", "a b"),
        ("x" * 130, "x" * 120),
        ("\n\t  ", "-"),
    ],
)
def test_tc_b3_005_sanitize(raw, expected):
    assert require_symbol("app.notifications.staff_texts", "sanitize_param")(raw) == expected


@pytest.mark.parametrize(
    "name,prefix", [("Laura Gómez", "Laura Gómez (+57 300 000 0123)"), (None, "+57 300 000 0123")]
)
def test_tc_b3_005_params(name, prefix):
    build = require_symbol("app.notifications.staff_texts", "build_params")
    params = build(
        customer=Customer(full_name=name, phone_number=PHONE),
        plan=plan(),
        starts_at=NOW,
        deposit_cop=125000,
    )
    assert params[0] == prefix and params[3] == "$125.000"
    assert len(params) == 4 and all(isinstance(value, str) for value in params)


@pytest.mark.parametrize(
    "hours,template,expected",
    [
        (1, "", "TEXT"),
        (23.5, "aviso_comprobante_reserva", "TEMPLATE"),
        (24, "aviso_comprobante_reserva", "TEMPLATE"),
        (24, "", "DEFERRED"),
    ],
)
async def test_tc_b3_006_007_channel_and_no_http_in_transaction(client, hours, template, expected):
    target = await recipient()
    await fresh(target, hours)
    row = await outbox(target)
    process = require_symbol("app.notifications.worker", "process_staff_outbox_once")
    calls = []

    async def transport(request):
        async with app.state.db_sessionmaker() as observer:
            count = await observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND pid<>pg_backend_pid() AND xact_start IS NOT NULL"
                )
            )
            assert count == 0, "HTTP durante una transacción abierta"
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "staff.sent.1"}]})

    config = settings(STAFF_NOTIFICATIONS_ENABLED=True, STAFF_TEMPLATE_EVIDENCE_NAME=template)
    with respx.mock(assert_all_called=False) as router:
        router.post("https://graph.facebook.com/v20.0/staff-test/messages").mock(
            side_effect=transport
        )
        async with WhatsAppOutboundClient(config) as sender:
            await process(app.state.db_sessionmaker, sender, config, now=NOW)
    saved = (await rows(type(row)))[0]
    assert saved.status == ("DEFERRED" if expected == "DEFERRED" else "SENT")
    if expected == "DEFERRED":
        assert calls == []
    elif expected == "TEXT":
        assert saved.message_kind == "TEXT" and calls[0]["type"] == "text"
        assert calls[0]["text"]["body"].endswith("\nPanel: https://admin.ceibaclubhouse.com")
    else:
        assert saved.message_kind == "TEMPLATE"
        assert calls[0] == {
            "messaging_product": "whatsapp",
            "to": PHONE,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": "es"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": p} for p in row.params],
                    }
                ],
            },
        }


@pytest.mark.parametrize(
    "http_status,code,retryable",
    [
        (500, 131000, True),
        (429, 130429, True),
        (400, 130429, True),
        (400, 132001, False),
        (400, 131047, False),
        (400, 999999, False),
        (401, 190, False),
    ],
)
async def test_tc_b3_008_error_codes(http_status, code, retryable):
    with respx.mock as router:
        router.post("https://graph.facebook.com/v20.0/staff-test/messages").respond(
            http_status,
            json={"error": {"code": code, "message": "Error sintético"}},
        )
        async with WhatsAppOutboundClient(settings()) as sender:
            with pytest.raises(WhatsAppSendError) as raised:
                await sender.send_text(PHONE, "Prueba")
    assert getattr(raised.value, "code", None) == code
    assert getattr(raised.value, "retryable", None) is retryable


@pytest.mark.parametrize(
    "permanent,attempts,expected",
    [(False, 0, "PENDING"), (True, 0, "FAILED"), (False, 4, "FAILED")],
)
async def test_tc_b3_008_backoff_and_exhaustion(client, permanent, attempts, expected):
    target = await recipient(last_inbound_at=NOW)
    row = await outbox(target, attempts=attempts)
    process = require_symbol("app.notifications.worker", "process_staff_outbox_once")
    assert "retryable" in __import__("inspect").signature(WhatsAppSendError).parameters
    sender = AsyncMock()
    sender.send_text.side_effect = WhatsAppSendError(
        "Error", code=132001 if permanent else 130429, retryable=not permanent
    )
    await process(
        app.state.db_sessionmaker, sender, settings(STAFF_NOTIFICATIONS_ENABLED=True), now=NOW
    )
    saved = (await rows(type(row)))[0]
    assert saved.status == expected and saved.attempts == attempts + 1
    if expected == "PENDING":
        assert saved.next_attempt_at > NOW
        assert saved.next_attempt_at == NOW + timedelta(seconds=2**saved.attempts)


async def test_tc_b3_009_status_monotonic_and_dedupe(client):
    target = await recipient()
    row = await outbox(
        target, status="SENT", message_kind="TEXT", provider_message_id="staff.status"
    )
    for state in ("delivered", "read", "delivered", "read"):
        await record_provider_status(
            {"id": "staff.status", "status": state, "timestamp": str(int(NOW.timestamp()))},
            app.state.db_sessionmaker,
        )
    assert (await rows(type(row)))[0].status == "READ"
    statuses = await rows(MessageProviderStatus)
    assert len(statuses) == 2 and all(s.message_id is None for s in statuses)


@pytest.mark.parametrize(
    "template,expected", [("aviso_comprobante_reserva", "PENDING"), ("", "DEFERRED")]
)
async def test_tc_b3_009_131047_recovery(client, monkeypatch, template, expected):
    monkeypatch.setenv("STAFF_TEMPLATE_EVIDENCE_NAME", template)
    get_settings.cache_clear()
    target = await recipient(last_inbound_at=NOW)
    row = await outbox(
        target, status="SENT", message_kind="TEXT", provider_message_id="staff.failed"
    )
    await record_provider_status(
        {
            "id": "staff.failed",
            "status": "failed",
            "errors": [{"code": 131047, "title": "Window closed"}],
            "timestamp": str(int(NOW.timestamp())),
        },
        app.state.db_sessionmaker,
    )
    saved = (await rows(type(row)))[0]
    assert saved.status == expected and saved.last_error_code == 131047
    if template:
        process = require_symbol("app.notifications.worker", "process_staff_outbox_once")
        sender = AsyncMock()
        sender.send_template.return_value = "staff.template.retry"
        await process(app.state.db_sessionmaker, sender, get_settings(), now=saved.next_attempt_at)
        sender.send_text.assert_not_called()
        sender.send_template.assert_awaited_once()


async def test_tc_b3_010_staff_inbound_reopens_and_is_silent(client):
    target = await recipient()
    recent = await outbox(target, status="DEFERRED", created_at=NOW - timedelta(hours=1))
    await outbox(target, status="DEFERRED", source_id="old", created_at=NOW - timedelta(hours=49))
    payload = json.loads(
        whatsapp_message_payload("staff.in.1", phone=PHONE.removeprefix("+"), text="Hola")
    )
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(
        int(NOW.timestamp())
    )
    for _ in range(2):
        await process_whatsapp_webhook(payload, app.state.db_sessionmaker)
    saved = (await rows(type(target)))[0]
    assert saved.last_inbound_at == NOW and saved.last_inbound_message_id == "staff.in.1"
    for model in (Customer, Conversation, Message, InboxJob, Outbox):
        assert await rows(model) == [], model.__name__
    notifications = await rows(type(recent))
    assert [row.status for row in notifications] == ["PENDING", "DEFERRED"]
    assert len(await audits("STAFF_INBOUND_RECEIVED")) == 1
    assert len(await audits("STAFF_NOTIFICATION_REQUEUED")) == 1


async def test_tc_b3_010_inactive_is_customer(client):
    await recipient(active=False)
    payload = json.loads(whatsapp_message_payload("inactive.1", phone=PHONE.removeprefix("+")))
    await process_whatsapp_webhook(payload, app.state.db_sessionmaker)
    assert len(await rows(Customer)) == len(await rows(InboxJob)) == 1


async def test_tc_b3_011_expiration_and_disabled_flag(client):
    target = await recipient(active=False)
    row = await outbox(target)
    active = await recipient(phone_number="+573000000124")
    await outbox(active, status="DEFERRED", created_at=NOW - timedelta(hours=49))
    process = require_symbol("app.notifications.worker", "process_staff_outbox_once")
    sender = AsyncMock()
    await process(
        app.state.db_sessionmaker, sender, settings(STAFF_NOTIFICATIONS_ENABLED=False), now=NOW
    )
    assert [item.status for item in await rows(type(row))] == ["PENDING", "DEFERRED"]
    await process(
        app.state.db_sessionmaker, sender, settings(STAFF_NOTIFICATIONS_ENABLED=True), now=NOW
    )
    assert [item.status for item in await rows(type(row))] == ["EXPIRED", "EXPIRED"]
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    assert len(await audits("STAFF_NOTIFICATION_EXPIRED")) == 2


async def test_tc_b3_012_admin_crud_audit_and_masking(client, monkeypatch):
    headers = await login_headers(client, "90000000")
    body = {"display_name": "Laura", "phone_number": PHONE}
    result = await client.post("/admin/notification-recipients", headers=headers, json=body)
    assert result.status_code == 201, result.text
    target = result.json()
    path = f"/admin/notification-recipients/{target['id']}"
    duplicate = await client.post("/admin/notification-recipients", headers=headers, json=body)
    assert duplicate.status_code == 409
    invalid = await client.post(
        "/admin/notification-recipients", headers=headers, json={**body, "phone_number": "123"}
    )
    assert invalid.status_code == 422
    listed = await client.get("/admin/notification-recipients", headers=headers)
    assert listed.status_code == 200 and "ventana_abierta_hasta" in listed.json()[0]
    assert (
        await client.patch(path, headers=headers, json={"display_name": "Laura"})
    ).status_code == 200
    assert await audits("NOTIFICATION_RECIPIENT_UPDATED") == []
    assert (await client.patch(path, headers=headers, json={"active": False})).status_code == 200
    audit = (await audits("NOTIFICATION_RECIPIENT_UPDATED"))[0]
    assert audit.old_value == {"active": True} and audit.new_value == {"active": False}
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", "false")
    get_settings.cache_clear()
    tested = await client.post(path + "/test", headers=headers)
    assert tested.status_code == 409 and tested.json()["detail"] == "Avisos desactivados"
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", "true")
    get_settings.cache_clear()
    await client.patch(path, headers=headers, json={"active": True})
    assert (await client.post(path + "/test", headers=headers)).status_code == 201
    recent = await client.get("/admin/staff-notifications", headers=headers)
    assert recent.status_code == 200
    assert PHONE not in recent.text and "params" not in recent.json()[0]
    assert len(await audits("NOTIFICATION_RECIPIENT_CREATED")) == 1


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/admin/notification-recipients", None),
        (
            "POST",
            "/admin/notification-recipients",
            {"display_name": "Laura", "phone_number": PHONE},
        ),
        ("PATCH", "/admin/notification-recipients/1", {"active": False}),
        ("POST", "/admin/notification-recipients/1/test", None),
        ("GET", "/admin/staff-notifications", None),
    ],
)
async def test_tc_b3_012_agent_forbidden(client, method, path, body):
    response = await client.request(
        method, path, headers=await login_headers(client, "80000000"), json=body
    )
    assert response.status_code == 403, response.text


async def test_tc_b3_013_customer_send_text_unchanged():
    with respx.mock as router:
        route = router.post("https://graph.facebook.com/v20.0/staff-test/messages").respond(
            200,
            json={"messages": [{"id": "customer.sent"}]},
        )
        async with WhatsAppOutboundClient(settings()) as sender:
            assert await sender.send_text(PHONE, "Respuesta aprobada") == "customer.sent"
    assert json.loads(route.calls[0].request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": PHONE,
        "type": "text",
        "text": {"preview_url": False, "body": "Respuesta aprobada"},
    }
