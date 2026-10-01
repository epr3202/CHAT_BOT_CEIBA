import asyncio
import os
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.calendar.adapter import CalendarUnavailableError, FakeCalendarAdapter
from app.main import app
from app.plan.models import Plan
from app.reservation.models import Reservation
from app.reservation.settlement import sync_reservation_calendar
from tests.booking_backend.helpers import START, settings
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation


@pytest.mark.parametrize("amount", [None, 0, -1, True, 1.5])
async def test_g3_positive_integer_amount_required(client: AsyncClient, amount: object) -> None:
    row = await seed_evidence()
    response = await client.post(
        f"/admin/payment-evidence/{row.id}/accept",
        headers=await login_headers(client, "90000000"),
        json={"amount_cop": amount},
    )
    assert response.status_code == 422


async def test_g3_concurrent_exclusive_acceptance_serializes(
    client: AsyncClient,
    calendar: FakeCalendarAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        await seed_reservation(
            "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
        )
        for _ in range(2)
    ]
    async with app.state.db_sessionmaker.begin() as session:
        for row in rows:
            (await session.get(Plan, row.plan_id)).exclusive = True
    evidences = [await seed_evidence(reservation_id=row.reservation_id) for row in rows]
    barrier = asyncio.Event()
    calls = 0
    original = calendar.list_events

    async def concurrent_snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=10)
        return await original(*args, **kwargs)

    monkeypatch.setattr(calendar, "list_events", concurrent_snapshot)
    headers = await login_headers(client, "90000000")
    responses = await asyncio.gather(
        *[
            client.post(
                f"/admin/payment-evidence/{e.id}/accept",
                headers=headers,
                json={"amount_cop": 125000},
            )
            for e in evidences
        ]
    )
    assert all(r.status_code == 200 for r in responses)
    assert {r.json()["result"] for r in responses} == {"RESERVED", "CONFLICT"}
    async with app.state.db_sessionmaker() as session:
        saved = list(await session.scalars(select(Reservation)))
        assert sum(r.status == "RESERVED" for r in saved) == 1
        assert all(r.amount_paid_cop == 125000 for r in saved)


async def test_g3_timeout_after_create_reconciles_same_id(client: AsyncClient) -> None:
    row = await seed_reservation("RESERVED")
    calendar = FakeCalendarAdapter(timeout_after_create=True)
    kwargs = dict(calendar=calendar, sessionmaker=app.state.db_sessionmaker, settings=settings())
    with pytest.raises(CalendarUnavailableError):
        await sync_reservation_calendar(row.reservation_id, **kwargs)
    await sync_reservation_calendar(row.reservation_id, **kwargs)
    assert calendar.created_event_ids == [row.reservation_id.hex]
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(Reservation, row.reservation_id)).calendar_status == "CONFIRMED"


async def test_g3_reserved_update_failure_retains_request_and_retry(
    client: AsyncClient,
    calendar: FakeCalendarAdapter,
) -> None:
    row = await seed_reservation("RESERVED", starts_at=START, ends_at=START + timedelta(hours=3))
    await sync_reservation_calendar(
        row.reservation_id,
        calendar=calendar,
        sessionmaker=app.state.db_sessionmaker,
        settings=settings(),
    )
    calendar.raise_on.add("update")
    headers = await login_headers(client, "90000000")
    response = await client.patch(
        f"/admin/reservations/{row.reservation_id}/schedule",
        headers=headers,
        json={"starts_at": (START + timedelta(days=1)).isoformat()},
    )
    assert response.status_code == 200 and response.json()["calendar_synced"] is False
    assert response.json()["status"] == "RESERVED" and response.json()["calendar_status"] == "NONE"
    calendar.raise_on.clear()
    retried = await client.post(
        f"/admin/reservations/{row.reservation_id}/sync-calendar", headers=headers
    )
    assert retried.json()["calendar_synced"] is True
    async with app.state.db_sessionmaker() as session:
        assert await session.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "RESERVATION_RESCHEDULED")
        )


async def test_g3_reject_http_and_repeat(client: AsyncClient) -> None:
    row = await seed_reservation("PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    headers = await login_headers(client, "90000000")
    url = f"/admin/payment-evidence/{evidence.id}/reject"
    assert (await client.post(url, headers=headers, json={"note": "Ilegible"})).status_code == 200
    assert (await client.post(url, headers=headers, json={"note": "Ilegible"})).status_code == 409
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(Reservation, row.reservation_id)).status == "PAYMENT_PENDING"


def test_g3_expiration_script_executable() -> None:
    assert os.access(Path("scripts/expire_reservations.py"), os.X_OK)
