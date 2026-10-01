from datetime import timedelta
from itertools import product
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.calendar.adapter import CalendarUnavailableError, FakeCalendarAdapter
from app.main import app
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.availability import BookingBlocker
from app.reservation.models import Reservation
from tests.b1a_contracts import STATUSES, VALID_TRANSITIONS, require_symbol
from tests.booking_backend.helpers import START, settings
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import (
    seed_evidence,
    seed_plan,
    seed_reservation,
)

MODULE = "app.reservation.settlement"


@pytest.mark.parametrize("old,new", list(product(STATUSES, repeat=2)))
async def test_a_r1_matrix(old: str, new: str) -> None:
    transition = require_symbol("app.reservation.service", "transition_reservation")
    reservation = Reservation(status=old)
    session = Mock(spec=AsyncSession)
    allowed = VALID_TRANSITIONS | {("PAYMENT_REVIEW", "PAYMENT_PENDING")}
    if (old, new) in allowed:
        await transition(session, reservation, new, actor="Admin", reason="B2", request_id="r1")
        assert reservation.status == new
    else:
        with pytest.raises(ValueError):
            await transition(session, reservation, new, actor="Admin", reason="B2", request_id="r1")


async def accept(evidence_id: int, amount: int, blockers: list | None = None):
    function = require_symbol(MODULE, "accept_payment")
    async with app.state.db_sessionmaker.begin() as session:
        evidence = await session.get(PaymentEvidence, evidence_id)
        result = await function(
            session,
            evidence=evidence,
            amount_cop=amount,
            actor="Admin B2",
            note="Verificado",
            request_id="r2",
            calendar_blockers=blockers or [],
        )
    return result


async def test_a_r2_no_reservation(client: AsyncClient) -> None:
    evidence = await seed_evidence()
    result = await accept(evidence.id, 100000)
    assert result.kind == "NO_RESERVATION" and result.reservation is None
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(PaymentEvidence, evidence.id)).review_status == "ACCEPTED"
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "PAYMENT_EVIDENCE_ACCEPTED")
        )
        assert audit.new_value["amount_cop"] == 100000
        assert audit.new_value["note"] == "Verificado"


@pytest.mark.parametrize(
    "amount,kind,payment_kind",
    [
        (50000, "PARTIAL", None),
        (125000, "RESERVED", "DEPOSIT"),
        (250000, "RESERVED", "FULL"),
    ],
)
async def test_a_r2_amounts(client: AsyncClient, amount: int, kind: str, payment_kind: str) -> None:
    row = await seed_reservation(
        "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
    )
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    result = await accept(evidence.id, amount)
    assert result.kind == kind
    assert result.reservation.amount_paid_cop == amount
    assert result.reservation.status == ("PAYMENT_PENDING" if kind == "PARTIAL" else "RESERVED")
    assert result.reservation.payment_kind == payment_kind
    assert result.reservation.balance_due_at == (
        START - timedelta(days=1) if payment_kind == "DEPOSIT" else None
    )
    assert result.missing_cop == max(0, 125000 - amount)


async def test_a_r2_two_deposits(client: AsyncClient) -> None:
    row = await seed_reservation(
        "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
    )
    first = await seed_evidence(reservation_id=row.reservation_id)
    assert (await accept(first.id, 50000)).kind == "PARTIAL"
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, row.reservation_id)
        saved.status = "PAYMENT_REVIEW"  # Second inbound evidence has already linked the request.
    second = await seed_evidence(reservation_id=row.reservation_id)
    result = await accept(second.id, 75000)
    assert result.kind == "RESERVED" and result.reservation.amount_paid_cop == 125000
    assert result.reservation.payment_kind == "DEPOSIT"


@pytest.mark.parametrize("amount", [0, -1])
async def test_a_r2_invalid_amount_has_no_effect(amount: int) -> None:
    function = require_symbol(MODULE, "accept_payment")
    session = AsyncMock(spec=AsyncSession)
    evidence = PaymentEvidence(review_status="PENDING_REVIEW")
    with pytest.raises(ValueError):
        await function(
            session,
            evidence=evidence,
            amount_cop=amount,
            actor="Admin",
            note=None,
            request_id="invalid",
            calendar_blockers=[],
        )
    assert evidence.review_status == "PENDING_REVIEW"
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "exclusive,other_exclusive,blocked",
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
async def test_a_r2_fresh_overlap(
    client: AsyncClient,
    exclusive: bool,
    other_exclusive: bool,
    blocked: bool,
) -> None:
    row = await seed_reservation(
        "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
    )
    other = await seed_reservation("RESERVED", starts_at=START, ends_at=START + timedelta(hours=3))
    async with app.state.db_sessionmaker.begin() as session:
        (await session.get(Plan, row.plan_id)).exclusive = exclusive
        (await session.get(Plan, other.plan_id)).exclusive = other_exclusive
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    result = await accept(evidence.id, 125000)
    assert result.kind == ("CONFLICT" if blocked else "RESERVED")
    assert result.reservation.amount_paid_cop == 125000
    assert result.reservation.status == ("PAYMENT_REVIEW" if blocked else "RESERVED")
    assert bool(result.blockers) is blocked


async def test_a_r2_calendar_conflict(client: AsyncClient) -> None:
    row = await seed_reservation("PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    result = await accept(evidence.id, 125000, [BookingBlocker("CALENDAR_EXCLUSIVE", "external")])
    assert result.kind == "CONFLICT" and result.reservation.status == "PAYMENT_REVIEW"
    assert result.blockers == [BookingBlocker("CALENDAR_EXCLUSIVE", "external")]


@pytest.mark.parametrize("linked", [True, False])
async def test_a_r3_reject(client: AsyncClient, linked: bool) -> None:
    function = require_symbol(MODULE, "reject_payment")
    row = await seed_reservation("PAYMENT_REVIEW") if linked else None
    evidence = await seed_evidence(reservation_id=row.reservation_id if row else None)
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(PaymentEvidence, evidence.id)
        await function(
            session, evidence=saved, actor="Admin B2", note="No legible", request_id="r3"
        )
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(PaymentEvidence, evidence.id)).review_status == "REJECTED"
        if row:
            assert (await session.get(Reservation, row.reservation_id)).status == "PAYMENT_PENDING"


@pytest.mark.parametrize("exclusive", [True, False])
async def test_a_r4_sync_release_reconcile(
    client: AsyncClient,
    calendar: FakeCalendarAdapter,
    exclusive: bool,
) -> None:
    sync = require_symbol(MODULE, "sync_reservation_calendar")
    release = require_symbol(MODULE, "release_reservation_calendar")
    row = await seed_reservation("RESERVED", starts_at=START, ends_at=START + timedelta(hours=3))
    async with app.state.db_sessionmaker.begin() as session:
        (await session.get(Plan, row.plan_id)).exclusive = exclusive
    kwargs = dict(calendar=calendar, sessionmaker=app.state.db_sessionmaker, settings=settings())
    await sync(row.reservation_id, **kwargs)
    await sync(row.reservation_id, **kwargs)
    event = await calendar.get_event(row.reservation_id.hex)
    assert event.summary.startswith("Ritual del Corazón — Cliente B1a")
    assert ("exclusividad" in event.summary) is exclusive
    assert str(row.reservation_id) in event.description
    assert "250000" in event.description
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(Reservation, row.reservation_id)
        assert saved.external_calendar_id == row.reservation_id.hex
        assert saved.calendar_status == "CONFIRMED"
    await release(row.reservation_id, **kwargs)
    await release(row.reservation_id, **kwargs)  # Missing external event is harmless.
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(Reservation, row.reservation_id)
        assert saved.calendar_status == "NONE" and saved.external_calendar_id is None
        actions = list(await session.scalars(select(AuditEvent.action)))
        assert "CALENDAR_EVENT_CREATED" in actions and "CALENDAR_EVENT_DELETED" in actions


async def test_a_r4_failure_preserves_reserved(client: AsyncClient) -> None:
    sync = require_symbol(MODULE, "sync_reservation_calendar")
    row = await seed_reservation("RESERVED")
    with pytest.raises(CalendarUnavailableError):
        await sync(
            row.reservation_id,
            calendar=FakeCalendarAdapter(raise_on={"create"}),
            sessionmaker=app.state.db_sessionmaker,
            settings=settings(),
        )
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(Reservation, row.reservation_id)
        assert saved.status == "RESERVED" and saved.calendar_status == "NONE"


@pytest.mark.parametrize("mode", ["RESERVED", "PARTIAL", "CONFLICT", "DOWN"])
async def test_a_r5_accept_http(
    client: AsyncClient,
    calendar: FakeCalendarAdapter,
    mode: str,
) -> None:
    row = await seed_reservation(
        "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
    )
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    if mode == "CONFLICT":
        calendar.add_event("business-main", "exclusividad", START, START + timedelta(hours=3))
    if mode == "DOWN":
        calendar.raise_on.add("create")
    headers = await login_headers(client, "90000000")
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=headers,
        json={"amount_cop": 50000 if mode == "PARTIAL" else 125000},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["result"] == ("RESERVED" if mode == "DOWN" else mode)
    assert data["evidence"]["review_status"] == "ACCEPTED"
    if mode in {"DOWN", "RESERVED"}:
        assert data["calendar_synced"] is (mode == "RESERVED")
    if mode == "DOWN":
        calendar.raise_on.clear()
        response = await client.post(
            f"/admin/reservations/{row.reservation_id}/sync-calendar", headers=headers
        )
        assert response.status_code == 200 and response.json()["calendar_synced"] is True
    detail = await client.get(f"/admin/reservations/{row.reservation_id}", headers=headers)
    assert detail.json()["deposit_amount_cop"] == 125000
    assert detail.json()["missing_cop"] == (75000 if mode == "PARTIAL" else 0)
    assert detail.json()["evidences"][0]["amount_cop"] == (50000 if mode == "PARTIAL" else 125000)


async def test_a_r5_manual_create_validation(client: AsyncClient, calendar: FakeCalendarAdapter):
    selected = await seed_plan()
    body = dict(
        phone="+573000000222",
        full_name="Cliente manual",
        plan_id=str(selected.plan_id),
        starts_at=START.isoformat(),
    )
    headers = await login_headers(client, "80000000")
    response = await client.post("/admin/reservations", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] is None
    assert response.json()["deposit_amount_cop"] == 125000
    assert response.json()["status"] == "PAYMENT_PENDING" and calendar.create_call_count == 0
    naive = dict(body, starts_at=START.replace(tzinfo=None).isoformat())
    assert (
        await client.post("/admin/reservations", headers=headers, json=naive)
    ).status_code == 422
    calendar.add_event("business-main", "exclusividad", START, START + timedelta(hours=3))
    blocked = await client.post("/admin/reservations", headers=headers, json=body)
    assert blocked.status_code == 409 and blocked.json()["detail"]["blockers"]


@pytest.mark.parametrize("status", STATUSES)
async def test_a_r5_schedule(client: AsyncClient, calendar: FakeCalendarAdapter, status: str):
    row = await seed_reservation(status, starts_at=START, ends_at=START + timedelta(hours=3))
    headers = await login_headers(client, "90000000")
    new = START + timedelta(days=1)
    if status == "RESERVED":
        sync = require_symbol(MODULE, "sync_reservation_calendar")
        await sync(
            row.reservation_id,
            calendar=calendar,
            sessionmaker=app.state.db_sessionmaker,
            settings=settings(),
        )
    response = await client.patch(
        f"/admin/reservations/{row.reservation_id}/schedule",
        headers=headers,
        json={"starts_at": new.isoformat()},
    )
    assert response.status_code == (409 if status in {"EXPIRED", "CANCELLED"} else 200)
    if status == "RESERVED":
        assert (await calendar.get_event(row.reservation_id.hex)).start == new
        assert calendar.updated_event_ids == [row.reservation_id.hex]


@pytest.mark.parametrize("path,method", [("schedule", "PATCH"), ("sync-calendar", "POST")])
async def test_a_r5_roles(client: AsyncClient, path: str, method: str) -> None:
    row = await seed_reservation()
    response = await client.request(
        method,
        f"/admin/reservations/{row.reservation_id}/{path}",
        headers=await login_headers(client, "80000000"),
        json={"starts_at": START.isoformat()} if method == "PATCH" else None,
    )
    assert response.status_code == 403


async def test_a_r5_cancel_release(client: AsyncClient, calendar: FakeCalendarAdapter) -> None:
    sync = require_symbol(MODULE, "sync_reservation_calendar")
    row = await seed_reservation("RESERVED")
    await sync(
        row.reservation_id,
        calendar=calendar,
        sessionmaker=app.state.db_sessionmaker,
        settings=settings(),
    )
    response = await client.post(
        f"/admin/reservations/{row.reservation_id}/cancel",
        headers=await login_headers(client, "90000000"),
        json={"note": "Cancelada por cliente"},
    )
    assert response.status_code == 200 and response.json()["calendar_synced"] is True
    assert calendar.deleted_event_ids == [row.reservation_id.hex]


async def test_a_r6_expiration(client: AsyncClient) -> None:
    expire = require_symbol(MODULE, "expire_pending_reservations")
    rows = [
        await seed_reservation(status, starts_at=START, ends_at=START + timedelta(hours=3))
        for status in STATUSES
    ]
    await seed_reservation(
        "PAYMENT_PENDING",
        starts_at=START + timedelta(days=2),
        ends_at=START + timedelta(days=2, hours=3),
    )
    assert await expire(app.state.db_sessionmaker, START + timedelta(hours=1)) == 1
    assert await expire(app.state.db_sessionmaker, START + timedelta(hours=1)) == 0
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(Reservation, rows[0].reservation_id)).status == "EXPIRED"
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.reason == "Fecha vencida sin pago")
        )
        assert audit.actor == "SYSTEM"
    assert Path("scripts/expire_reservations.py").is_file()
    assert "expire_pending_reservations" in Path("app/channel/worker.py").read_text()


async def test_a_r7_calendar_outside_transactions(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from app.admin import routes

    class Spy(FakeCalendarAdapter):
        async def create_event(self, *args, **kwargs):
            async with app.state.db_sessionmaker() as session:
                transactions = await session.scalar(
                    __import__("sqlalchemy").text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() AND xact_start IS NOT NULL"
                    )
                )
                assert transactions == 0
            return await super().create_event(*args, **kwargs)

    monkeypatch.setattr(routes, "get_calendar_adapter", lambda settings: Spy())
    row = await seed_reservation(
        "PAYMENT_REVIEW", starts_at=START, ends_at=START + timedelta(hours=3)
    )
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(client, "90000000"),
        json={"amount_cop": 125000},
    )
    assert response.status_code == 200 and response.json()["calendar_synced"] is True


def test_a_r8_migration_lineage_nullable() -> None:
    revisions = {
        r.revision: r for r in ScriptDirectory.from_config(Config("alembic.ini")).walk_revisions()
    }
    assert "20260930_0030" in revisions
    assert revisions["20260930_0030"].down_revision == "20260930_0029"
    assert Reservation.__table__.c.conversation_id.nullable
