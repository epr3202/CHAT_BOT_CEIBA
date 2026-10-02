import json

import pytest
from sqlalchemy import select

from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import InboxJob
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.main import app
from tests.integration.helpers import login_headers, whatsapp_message_payload
from tests.staff_notifications.helpers import audits, models, rows

WARNING = (
    "Este número tiene conversaciones como cliente. Mientras esté activo como asesor, "
    "el bot no le responderá."
)


@pytest.mark.parametrize(
    "raw",
    ["3001234567", "300 123 4567", "+57 300-123-4567", "573001234567"],
)
async def test_f1_normalizes_colombian_phone(client, raw):
    response = await client.post(
        "/admin/notification-recipients",
        headers=await login_headers(client, "90000000"),
        json={"display_name": "Asesor", "phone_number": raw},
    )
    assert response.status_code == 201, response.text
    assert response.json()["phone_number"] == "+573001234567"
    listed = await client.get(
        "/admin/notification-recipients", headers=await login_headers(client, "90000000")
    )
    assert listed.json()[0]["phone_number"] == "+573001234567"


@pytest.mark.parametrize("raw", ["+5730012345", "abc"])
async def test_f1_invalid_phones_have_spanish_error(client, raw):
    response = await client.post(
        "/admin/notification-recipients",
        headers=await login_headers(client, "90000000"),
        json={"display_name": "Asesor", "phone_number": raw},
    )
    assert response.status_code == 422, response.text
    if raw.startswith("+57"):
        assert "Número colombiano inválido: usa 10 dígitos, por ejemplo 3001234567" in response.text
    else:
        assert "teléfono" in response.text.casefold()


async def test_f1_duplicate_after_normalization_is_conflict(client):
    headers = await login_headers(client, "90000000")
    first = await client.post(
        "/admin/notification-recipients",
        headers=headers,
        json={"display_name": "Uno", "phone_number": "3001234567"},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/admin/notification-recipients",
        headers=headers,
        json={"display_name": "Dos", "phone_number": "+573001234567"},
    )
    assert second.status_code == 409, second.text
    assert len(await rows(models()[0])) == 1


async def test_f1_created_local_phone_intercepts_provider_sender(client):
    response = await client.post(
        "/admin/notification-recipients",
        headers=await login_headers(client, "90000000"),
        json={"display_name": "Asesor", "phone_number": "3001234567"},
    )
    assert response.status_code == 201, response.text
    payload = json.loads(whatsapp_message_payload("f1.intercept", phone="573001234567"))
    await process_whatsapp_webhook(payload, app.state.db_sessionmaker)
    assert await rows(InboxJob) == [], "El número normalizado debe interceptarse como asesor"
    assert await rows(Customer) == []
    assert len(await audits("STAFF_INBOUND_RECEIVED")) == 1


async def test_f5_post_patch_warn_if_customer_has_conversations(client):
    async with app.state.db_sessionmaker.begin() as session:
        customer = Customer(phone_number="+573001234567", full_name="Cliente de prueba")
        session.add(customer)
        await session.flush()
        session.add(Conversation(customer_id=customer.id, channel="WHATSAPP", state="BOT_ACTIVE"))
    headers = await login_headers(client, "90000000")
    result = await client.post(
        "/admin/notification-recipients",
        headers=headers,
        json={"display_name": "Asesor", "phone_number": "3001234567"},
    )
    assert result.status_code == 201, result.text
    assert result.json().get("warning") == WARNING
    patched = await client.patch(
        f"/admin/notification-recipients/{result.json()['id']}",
        headers=headers,
        json={"display_name": "Nombre corregido"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json().get("warning") == WARNING
    async with app.state.db_sessionmaker() as session:
        assert await session.scalar(select(Conversation.id)) is not None


async def test_f5_without_customer_conversations_has_no_warning(client):
    result = await client.post(
        "/admin/notification-recipients",
        headers=await login_headers(client, "90000000"),
        json={"display_name": "Asesor", "phone_number": "+573001234567"},
    )
    assert result.status_code == 201, result.text
    assert not result.json().get("warning")
