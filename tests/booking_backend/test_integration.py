from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit.models import AuditEvent
from app.calendar.adapter import FakeCalendarAdapter
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.main import app
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.booking_backend.helpers import START, settings, symbol
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
)
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation
from tests.test_w2b_payment_evidence_adversarial import (
    JPEG_SHA256,
    NORMALIZED_PHONE,
    ClassifierCalls,
    route_payment_image,
)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("GOOGLE_FREEBUSY_CALENDAR_IDS", "a,b")
    monkeypatch.setenv("CALENDAR_ADAPTER", "fake")
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin B1b", document_id="90000000", role="ADMIN")
    await bootstrap_agent(name="Agente B1b", document_id="80000000", role="AGENT")
    try:
        async for test_client in app_client():
            yield test_client
    finally:
        await cleanup_test_environment()


async def test_r4_create_persists_without_commit(client: AsyncClient) -> None:
    create = symbol("app.reservation.booking", "create_pending_reservation")
    seeded = await seed_reservation()
    async with app.state.db_sessionmaker() as session:
        async with session.begin():
            selected = await session.get(Plan, seeded.plan_id)
            event = await session.get(Event, seeded.event_id)
            result = await create(
                session,
                lead=await session.get(Lead, seeded.lead_id),
                event=event,
                plan=selected,
                conversation=await session.get(Conversation, seeded.conversation_id),
                customer=await session.get(Customer, seeded.customer_id),
                starts_at=START,
                actor="SYSTEM",
                request_id="r4-db",
            )
            await session.flush()
            result_id = result.reservation_id
            assert session.in_transaction()
            await session.rollback()
    async with app.state.db_sessionmaker() as session:
        assert await session.get(Reservation, result_id) is None
        assert (await session.get(Event, seeded.event_id)).plan_id is None


@pytest.mark.parametrize("case", ["pending", "none", "latest", "other_conversation"])
async def test_r5_attach_persisted(client: AsyncClient, case: str) -> None:
    attach = symbol("app.reservation.booking", "attach_payment_evidence")
    evidence = await seed_evidence()
    expected = None
    if case != "none":
        first = await seed_reservation(
            conversation_id=evidence.conversation_id, created_at=START - timedelta(days=2)
        )
        expected = first
        if case == "latest":
            expected = await seed_reservation(
                conversation_id=evidence.conversation_id, created_at=START - timedelta(days=1)
            )
        elif case == "other_conversation":
            expected = None
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(PaymentEvidence, evidence.id)
        if case == "other_conversation":
            saved.conversation_id = (await seed_reservation()).conversation_id
            saved.lead_id = first.lead_id
            # A conversation always wins over a matching lead.
            other = await session.scalar(
                select(Reservation).where(Reservation.conversation_id == saved.conversation_id)
            )
            other.status = "CANCELLED"
        result = await attach(session, saved, request_id="r5-db")
        assert (result.reservation_id if result else None) == (
            expected.reservation_id if expected else None
        )
        assert saved.reservation_id == (expected.reservation_id if expected else None)
        await attach(session, saved, request_id="r5-repeat")
    async with app.state.db_sessionmaker() as session:
        audits = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "RESERVATION_STATUS_CHANGED")
            )
        )
        assert len(audits) == (1 if expected else 0)
        if expected:
            row = await session.get(Reservation, expected.reservation_id)
            assert row.status == "PAYMENT_REVIEW" and row.amount_paid_cop == 0
            assert row.hold_expires_at is None
            assert (audits[0].actor, audits[0].reason) == ("SYSTEM", "Comprobante recibido")


async def test_r5_real_payment_flow_links_reservation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = await seed_reservation()
    sm = app.state.db_sessionmaker
    async with sm.begin() as session:
        customer = await session.get(Customer, reservation.customer_id)
        customer.phone_number = NORMALIZED_PHONE
        conversation = await session.get(Conversation, reservation.conversation_id)
        conversation.active_lead_id = reservation.lead_id
    evidence = await route_payment_image(
        sm,
        ClassifierCalls(),
        monkeypatch,
        message_id="wamid.b1b1.real",
        media_id="b1b1-test",
        declared_sha256=JPEG_SHA256,
    )
    assert evidence.reservation_id == reservation.reservation_id
    async with sm() as session:
        assert (
            await session.get(Reservation, reservation.reservation_id)
        ).status == "PAYMENT_REVIEW"


async def test_r8_fetch_closes_db_transaction_before_calendar(client: AsyncClient) -> None:
    fetch = symbol("app.reservation.availability", "fetch_booking_context")
    row = await seed_reservation("RESERVED", starts_at=START, ends_at=START + timedelta(hours=3))
    async with app.state.db_sessionmaker.begin() as session:
        selected = await session.get(Plan, row.plan_id)
        selected.exclusive = True
    # Expiring-on-commit session detects accidental lazy I/O after the read transaction.
    engine = app.state.db_sessionmaker.kw["bind"]
    async with async_sessionmaker(engine, expire_on_commit=True)() as session:

        class Spy(FakeCalendarAdapter):
            async def list_events(self, start: Any, end: Any, calendar_ids: Any) -> list:
                assert not session.in_transaction(), "Calendar no puede ejecutarse dentro de TX"
                assert list(calendar_ids) == ["a", "b"]
                assert (start, end) == (START, START + timedelta(hours=3))
                self.called = True
                return []

        spy = Spy()
        result = await fetch(
            session,
            plan=selected,
            starts_at=START,
            ends_at=START + timedelta(hours=3),
            calendar=spy,
            settings=settings(),
        )
        assert spy.called and not session.in_transaction()
        assert not result.available
        assert [(b.kind, b.ref) for b in result.blockers] == [
            ("RESERVED_EXCLUSIVE", str(row.reservation_id))
        ]


async def test_r7_admin_availability_real_blockers(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCalendarAdapter()
    assert callable(getattr(fake, "add_event", None)), "B1b-1: falta add_event"
    event = fake.add_event("a", "EXCLUSIVIDAD", START, START + timedelta(hours=3))
    monkeypatch.setattr(
        "app.admin.routes.get_calendar_adapter", lambda _settings: fake, raising=False
    )
    row = await seed_reservation("RESERVED", starts_at=START, ends_at=START + timedelta(hours=3))
    async with app.state.db_sessionmaker.begin() as session:
        (await session.get(Plan, row.plan_id)).exclusive = True
    response = await client.get(
        "/admin/reservations/availability",
        params={"plan_id": str(row.plan_id), "starts_at": START.isoformat()},
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["available"] is False
    assert {(b["kind"], b["ref"]) for b in data["blockers"]} == {
        ("CALENDAR_EXCLUSIVE", event.event_id),
        ("RESERVED_EXCLUSIVE", str(row.reservation_id)),
    }
    assert data["deposit_amount_cop"] == 125000
    assert data["window"] == {"ok": True, "reason": None}
    assert data["starts_at"] and data["ends_at"]


@pytest.mark.parametrize(
    "case,status", [("agent", 200), ("missing", 404), ("inactive", 422), ("naive", 422)]
)
async def test_r7_admin_errors(client: AsyncClient, case: str, status: int) -> None:
    assert "/admin/reservations/availability" in app.openapi()["paths"], (
        "B1b-1: falta la ruta estática de disponibilidad"
    )
    row = await seed_reservation()
    if case == "inactive":
        async with app.state.db_sessionmaker.begin() as session:
            (await session.get(Plan, row.plan_id)).active = False
    response = await client.get(
        "/admin/reservations/availability",
        params={
            "plan_id": str(uuid4() if case == "missing" else row.plan_id),
            "starts_at": (START.replace(tzinfo=None) if case == "naive" else START).isoformat(),
        },
        headers=await login_headers(client, "80000000" if case == "agent" else "90000000"),
    )
    assert response.status_code == status, response.text
