from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.calendar.adapter import FakeCalendarAdapter
from app.channel.models import Message, MessageProviderStatus
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.main import app
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    await configure_test_environment(monkeypatch)
    await bootstrap_agent()
    await bootstrap_agent("Otro", "88888888", role="AGENT")
    async for client in app_client():
        yield client
    await cleanup_test_environment()


async def test_opening_is_scoped_to_operator_thread_and_incoming_message(
    client: AsyncClient,
) -> None:
    admin = await login_headers(client)
    other = await login_headers(client, "88888888")
    async with app.state.db_sessionmaker() as session, session.begin():
        customer = Customer(phone_number="573000000001")
        session.add(customer)
        await session.flush()
        threads = [
            Conversation(customer_id=customer.id, channel="WHATSAPP", state="BOT_ACTIVE")
            for _ in range(2)
        ]
        session.add_all(threads)
        await session.flush()
        messages = [
            Message(
                customer_id=customer.id,
                conversation_id=threads[thread].id,
                channel="WHATSAPP",
                direction=direction,
                message_type="text",
                content={"text": {"body": "Mensaje de prueba"}},
                external_message_id=f"panel-{i}",
            )
            for i, (thread, direction) in enumerate(
                [(0, "INBOUND"), (0, "OUTBOUND"), (1, "INBOUND")]
            )
        ]
        session.add_all(messages)
        await session.flush()
        session.add(
            MessageProviderStatus(
                message_id=messages[1].id,
                provider_message_id="panel-1",
                status="read",
                provider_timestamp=datetime.now(UTC),
                payload={},
            )
        )
        tid = threads[0].id
        mid, outbound, foreign = [m.id for m in messages]
    path = f"/admin/conversations/{tid}/messages"
    rows = (await client.get(path, headers=admin)).json()
    assert rows[0]["opened_by_me"] is False
    assert rows[1]["read_by_contact"] is True
    for _ in range(2):
        response = await client.post(path + "/opened", headers=admin, json={"message_ids": [mid]})
        assert response.status_code == 204
    assert (await client.get(path, headers=admin)).json()[0]["opened_by_me"] is True
    assert (await client.get(path, headers=other)).json()[0]["opened_by_me"] is False
    for invalid in (foreign, outbound):
        assert (
            await client.post(path + "/opened", headers=other, json={"message_ids": [mid, invalid]})
        ).status_code == 422
    assert (await client.get(path, headers=other)).json()[0]["opened_by_me"] is False
    for headers, count in [(admin, 0), (other, 1)]:
        inbox = (await client.get("/admin/conversations", headers=headers)).json()
        assert next(row["unopened_count"] for row in inbox if row["id"] == tid) == count


async def test_calendar_requires_admin_and_includes_descriptions(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeCalendarAdapter()
    adapter.add_event(
        "room",
        "Reserva",
        datetime(2027, 1, 3, 14, tzinfo=UTC),
        datetime(2027, 1, 3, 17, tzinfo=UTC),
        "Descripción de la reserva",
    )
    monkeypatch.setattr("app.admin.routes.get_calendar_adapter", lambda settings: adapter)
    adapter.add_event(
        "private",
        "Otro calendario",
        datetime(2027, 1, 3, 14, tzinfo=UTC),
        datetime(2027, 1, 3, 17, tzinfo=UTC),
        "Solo ocupación",
    )
    monkeypatch.setattr(app.state.settings, "google_calendar_id", "room")
    monkeypatch.setattr(app.state.settings, "google_freebusy_calendar_ids", "room,private")
    path = "/admin/calendar/events?start=2027-01-01&end=2027-02-01"
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(path, headers=await login_headers(client, "88888888"))
    ).status_code == 403
    headers = await login_headers(client)
    response = await client.get(path, headers=headers)
    assert response.status_code == 200
    assert [e["description"] for e in response.json()] == ["Descripción de la reserva"]
    assert (
        await client.get(path.replace("2027-02-01", "2028-02-01"), headers=headers)
    ).status_code == 422
    adapter.raise_on.add("list_events")
    assert (await client.get(path, headers=headers)).status_code == 503

    def missing_configuration(settings: object) -> None:
        raise ValueError("Missing calendar configuration")

    monkeypatch.setattr("app.admin.routes.get_calendar_adapter", missing_configuration)
    assert (await client.get(path, headers=headers)).status_code == 503


async def test_search_finds_contact_beyond_first_page(client: AsyncClient) -> None:
    from datetime import timedelta

    headers = await login_headers(client)
    async with app.state.db_sessionmaker() as session, session.begin():
        customers = [
            Customer(
                phone_number=f"57320000{i:04d}",
                full_name="Contacto histórico" if i == 0 else f"Ejemplo {i}",
            )
            for i in range(201)
        ]
        session.add_all(customers)
        await session.flush()
        start = datetime(2026, 10, 1, tzinfo=UTC)
        session.add_all(
            [
                Conversation(
                    customer_id=c.id,
                    channel="WHATSAPP",
                    state="BOT_ACTIVE",
                    last_message_at=start + timedelta(minutes=i),
                )
                for i, c in enumerate(customers)
            ]
        )
    url = "/admin/conversations"
    first = await client.get(url, headers=headers, params={"limit": 200})
    assert first.status_code == 200
    assert all(r["customer_name"] != "Contacto histórico" for r in first.json())
    result = await client.get(url, headers=headers, params={"q": "histórico"})
    assert result.status_code == 200
    assert [r["customer_name"] for r in result.json()] == ["Contacto histórico"]
