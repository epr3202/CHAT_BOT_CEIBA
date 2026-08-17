from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, time

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.appointment.models import Appointment, BlockedDate, Holiday
from app.audit.models import AuditEvent
from app.channel.states import Channel
from app.customer.models import Customer
from app.lead.models import Lead
from app.main import app
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
)


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin", document_id="99999999", pin="123456", role="ADMIN")
    yield
    await cleanup_test_environment()


@pytest.fixture
async def client(test_environment: None) -> AsyncIterator[AsyncClient]:
    async for test_client in app_client():
        yield test_client


async def admin_headers(client: AsyncClient) -> dict[str, str]:
    return await login_headers(client, "99999999", "123456")


async def test_blocked_dates_crud_is_authenticated_and_audited(client: AsyncClient) -> None:
    headers = await admin_headers(client)

    created = await client.post(
        "/admin/blocked-dates",
        headers=headers,
        json={"blocked_date": "2026-08-18", "reason": "Mantenimiento"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["blocked_date"] == "2026-08-18"
    assert created.json()["reason"] == "Mantenimiento"

    updated = await client.patch(
        "/admin/blocked-dates/2026-08-18",
        headers=headers,
        json={"reason": "Evento interno"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["reason"] == "Evento interno"

    listed = await client.get("/admin/blocked-dates", headers=headers)
    assert listed.status_code == 200
    assert [row["blocked_date"] for row in listed.json()] == ["2026-08-18"]

    deleted = await client.delete("/admin/blocked-dates/2026-08-18", headers=headers)
    assert deleted.status_code == 204

    async with app.state.db_sessionmaker() as session:
        blocked = await session.get(BlockedDate, date(2026, 8, 18))
        actions = (
            await session.scalars(
                select(AuditEvent.action).where(AuditEvent.entity == "blocked_date")
            )
        ).all()

    assert blocked is None
    assert actions == [
        "BLOCKED_DATE_CREATED",
        "BLOCKED_DATE_UPDATED",
        "BLOCKED_DATE_DELETED",
    ]


async def test_manual_holiday_upsert_preserves_manual_source(client: AsyncClient) -> None:
    headers = await admin_headers(client)

    response = await client.post(
        "/admin/holidays",
        headers=headers,
        json={"holiday_date": "2026-08-18", "name": "Cierre especial"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "MANUAL"
    async with app.state.db_sessionmaker() as session:
        holiday = await session.get(Holiday, date(2026, 8, 18))
    assert holiday is not None
    assert holiday.source == "MANUAL"


async def test_list_appointments_for_day_orders_by_start_time(client: AsyncClient) -> None:
    headers = await admin_headers(client)
    visit_date = date(2026, 8, 18)
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number="+573001112233")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel=Channel.WHATSAPP, lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            session.add_all(
                [
                    Appointment(
                        customer_id=customer.id,
                        lead_id=lead.lead_id,
                        appointment_date=visit_date,
                        start_time=time(10),
                        attendee_count=2,
                        visit_reason="boda",
                        appointment_status="CONFIRMED",
                        external_calendar_id="event-10",
                    ),
                    Appointment(
                        customer_id=customer.id,
                        lead_id=lead.lead_id,
                        appointment_date=visit_date,
                        start_time=time(8),
                        attendee_count=1,
                        visit_reason="cumpleanos",
                        appointment_status="CONFIRMED",
                        external_calendar_id="event-8",
                    ),
                ]
            )

    response = await client.get(
        "/admin/appointments?appointment_date=2026-08-18",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert [row["start_time"] for row in response.json()] == ["08:00:00", "10:00:00"]
