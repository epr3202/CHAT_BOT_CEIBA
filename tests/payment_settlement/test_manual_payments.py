import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.calendar.adapter import FakeCalendarAdapter
from app.main import app
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation


def payment(amount: int, paid: int = 0) -> dict:
    return {
        "payment_id": str(uuid4()),
        "method": "CASH",
        "amount_cop": amount,
        "expected_paid_cop": paid,
        "note": "Caja del club",
    }


async def test_manual_balance_partial_full_and_replay(client: AsyncClient) -> None:
    row = await seed_reservation("RESERVED", amount_paid_cop=125000, payment_kind="DEPOSIT")
    url = f"/admin/reservations/{row.reservation_id}"
    headers = await login_headers(client, "90000000")
    data = payment(25000, 125000)
    replies = await asyncio.gather(
        *(client.post(f"{url}/payments", headers=headers, json=data) for _ in range(2))
    )
    assert [r.status_code for r in replies] == [200, 200]
    assert all(r.json()["reservation"]["amount_paid_cop"] == 150000 for r in replies)
    resp = await client.post(f"{url}/payments", headers=headers, json={**data, "method": "CARD"})
    assert resp.status_code == 409
    resp = await client.post(f"{url}/payments", headers=headers, json=payment(120000, 150000))
    assert resp.status_code == 409
    concurrent = payment(1000, 125000)
    assert (
        await client.post(f"{url}/payments", headers=headers, json=concurrent)
    ).status_code == 409
    final = {**payment(100000, 150000), "method": "NEQUI"}
    resp = await client.post(f"{url}/payments", headers=headers, json=final)
    assert resp.status_code == 200 and resp.json()["result"] == "BALANCE_PAID"
    detail = (await client.get(url, headers=headers)).json()
    assert detail["amount_paid_cop"] == detail["price_cop"] == 250000
    assert detail["payment_kind"] == "FULL" and detail["balance_due_at"] is None
    assert sorted(p["amount_cop"] for p in detail["manual_payments"]) == [25000, 100000]
    assert [p["method"] for p in detail["manual_payments"]] == ["NEQUI", "CASH"]
    assert all(
        p["recorded_by"] == "Admin B2" and p["created_at"] for p in detail["manual_payments"]
    )
    async with app.state.db_sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentEvidence)) == 0
        audits = list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.action == "RESERVATION_MANUAL_PAYMENT_RECORDED")
                .order_by(AuditEvent.id)
            )
        )
        assert len(audits) == 2
        assert audits[0].old_value["amount_paid_cop"] == 125000
        assert audits[0].new_value["amount_paid_cop"] == 150000


async def test_human_deposit_checks_availability_then_confirms(
    client: AsyncClient, calendar: FakeCalendarAdapter
) -> None:
    row = await seed_reservation()
    url = f"/admin/reservations/{row.reservation_id}"
    headers = await login_headers(client, "90000000")
    assert (await client.post(f"{url}/payments", headers=headers, json=payment(25000))).json()[
        "result"
    ] == "PARTIAL"
    data = payment(100000, 25000)
    calendar.add_event("business-main", "exclusividad", row.starts_at, row.ends_at)
    blocked = await client.post(f"{url}/payments", headers=headers, json=data)
    assert blocked.status_code == 409
    assert (await client.get(url, headers=headers)).json()["amount_paid_cop"] == 25000
    second = await seed_reservation()
    url = f"/admin/reservations/{second.reservation_id}/payments"
    # Schedule the second fixture outside the blocked interval.
    async with app.state.db_sessionmaker.begin() as session:
        fresh = await session.get(Reservation, second.reservation_id)
        fresh.starts_at += timedelta(days=2)
        fresh.ends_at += timedelta(days=2)
    deposit = payment(125000)
    calendar.raise_on.add("query")
    assert (await client.post(url, headers=headers, json=deposit)).status_code == 503
    calendar.raise_on.clear()
    confirmed = await client.post(url, headers=headers, json=deposit)
    assert confirmed.status_code == 200
    assert confirmed.json()["reservation"]["status"] == "RESERVED"
    assert confirmed.json()["calendar_synced"] is True
    assert confirmed.json()["reservation"]["calendar_status"] == "CONFIRMED"
    replay = await client.post(url, headers=headers, json=deposit)
    assert replay.json()["replayed"] and replay.json()["calendar_synced"] is True
    assert len(replay.json()["reservation"]["manual_payments"]) == 1


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELLED"])
async def test_reject_ineligible_and_unauthorized(client: AsyncClient, status: str) -> None:
    row = await seed_reservation(status)
    url = f"/admin/reservations/{row.reservation_id}/payments"
    args = payment(1000)
    assert (await client.post(url, json=args)).status_code == 401
    assert (
        await client.post(url, headers=await login_headers(client, "80000000"), json=args)
    ).status_code == 403
    headers = await login_headers(client, "90000000")
    assert (await client.post(url, headers=headers, json=args)).status_code == 409
    for changes in [{"amount_cop": 0}, {"amount_cop": 12.5}, {"method": "UNKNOWN"}]:
        assert (
            await client.post(url, headers=headers, json={**args, **changes})
        ).status_code == 422
