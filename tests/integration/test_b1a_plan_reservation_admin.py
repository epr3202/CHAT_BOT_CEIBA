"""R2-R5: persisted admin contracts, without running conversational flows."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.main import app
from app.payment.models import PaymentEvidence
from tests.b1a_contracts import EXPECTED_PLANS, STATUSES, require_symbol
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
    login_headers,
)

START = datetime(2026, 10, 10, 14, tzinfo=UTC)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    await configure_test_environment(monkeypatch)
    await bootstrap_agent(name="Admin B1a", document_id="90000000", role="ADMIN")
    await bootstrap_agent(name="Asesor B1a", document_id="80000000", role="AGENT")
    try:
        async for test_client in app_client():
            yield test_client
    finally:
        await cleanup_test_environment()


async def seed_plan(**changes: Any) -> Any:
    model = require_symbol("app.plan.models", "Plan")
    values = dict(
        code="RITUAL_CORAZON",
        name="Ritual del Corazón",
        event_type="ROMANTIC_DINNER",
        price_cop=250000,
        duration_minutes=180,
        exclusive=False,
        weekend_only=False,
        active=True,
        sort_order=1,
    )
    values.update(changes)
    async with app.state.db_sessionmaker.begin() as session:
        plan = model(**values)
        session.add(plan)
        await session.flush()
    return plan


async def seed_reservation(status: str = "PAYMENT_PENDING", **changes: Any) -> Any:
    model = require_symbol("app.reservation.models", "Reservation")
    plan = await seed_plan(code=f"TEST_{uuid4().hex}")
    async with app.state.db_sessionmaker.begin() as session:
        customer = Customer(
            phone_number=f"+573{uuid4().int % 1_000_000_000:09d}",
            full_name="Cliente B1a",
        )
        session.add(customer)
        await session.flush()
        conversation = Conversation(customer_id=customer.id, channel="WHATSAPP", state="NEW")
        lead = Lead(customer_id=customer.id, channel="WHATSAPP")
        session.add_all([conversation, lead])
        await session.flush()
        event = Event(lead_id=lead.lead_id, event_type=plan.event_type)
        session.add(event)
        await session.flush()
        values = dict(
            lead_id=lead.lead_id,
            event_id=event.event_id,
            plan_id=plan.plan_id,
            conversation_id=conversation.id,
            customer_id=customer.id,
            status=status,
            starts_at=START,
            ends_at=START + timedelta(minutes=180),
            price_cop=plan.price_cop,
            amount_paid_cop=0,
            calendar_status="NONE",
        )
        values.update(changes)
        reservation = model(**values)
        session.add(reservation)
        await session.flush()
    return reservation


async def seed_evidence(**changes: Any) -> PaymentEvidence:
    async with app.state.db_sessionmaker.begin() as session:
        customer = Customer(phone_number=f"+573{uuid4().int % 1_000_000_000:09d}")
        session.add(customer)
        await session.flush()
        conversation = Conversation(customer_id=customer.id, channel="WHATSAPP", state="NEW")
        session.add(conversation)
        await session.flush()
        message = Message(
            external_message_id=f"b1a-{uuid4().hex}",
            conversation_id=conversation.id,
            customer_id=customer.id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="image",
            content={"caption": "Comprobante"},
        )
        session.add(message)
        await session.flush()
        evidence = PaymentEvidence(
            conversation_id=conversation.id,
            customer_id=customer.id,
            message_id=message.id,
            media_id="test-b1a",
            mime_type="image/jpeg",
            declared_sha256="0" * 64,
            **changes,
        )
        session.add(evidence)
        await session.flush()
    return evidence


async def reservation_audits() -> list[AuditEvent]:
    async with app.state.db_sessionmaker() as session:
        return list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "RESERVATION_STATUS_CHANGED")
            )
        )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/admin/plans/{id}", {"price_cop": 300000}),
        ("GET", "/admin/reservations", None),
        ("GET", "/admin/reservations/{id}", None),
        ("POST", "/admin/reservations/{id}/cancel", {"note": "Cancelación solicitada"}),
    ],
)
async def test_r4_agent_forbidden_on_every_endpoint(
    client: AsyncClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    headers = await login_headers(client, "80000000")
    response = await client.request(method, path.format(id=uuid4()), headers=headers, json=body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", ["/admin/plans", "/admin/reservations"])
async def test_r4_admin_can_read_empty_lists(client: AsyncClient, path: str) -> None:
    response = await client.get(path, headers=await login_headers(client, "90000000"))
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_r4_patch_all_allowed_fields_audits_old_new_and_persists(client: AsyncClient) -> None:
    plan = await seed_plan()
    changes = dict(
        name="Plan actualizado",
        price_cop=275000,
        duration_minutes=210,
        exclusive=True,
        weekend_only=True,
        active=False,
        sort_order=9,
    )
    old = {key: getattr(plan, key) for key in changes}
    headers = await login_headers(client, "90000000")
    response = await client.patch(f"/admin/plans/{plan.plan_id}", headers=headers, json=changes)
    assert response.status_code == 200, response.text
    assert {key: response.json()[key] for key in changes} == changes
    listed = await client.get("/admin/plans", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["plan_id"] == str(plan.plan_id)
    assert listed.json()[0]["active"] is False
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(type(plan), plan.plan_id)
        assert {key: getattr(saved, key) for key in changes} == changes
        events = list(await session.scalars(select(AuditEvent).where(AuditEvent.entity == "plan")))
        assert len(events) == 1
        audit = events[0]
        assert {key: audit.old_value[key] for key in changes} == old
        assert {key: audit.new_value[key] for key in changes} == changes
        assert audit.actor == "Admin B1a"
        assert audit.reason.strip()


@pytest.mark.parametrize(
    "body",
    [
        {"code": "OTHER_CODE"},
        {"event_type": "PROPOSAL"},
        {"plan_id": str(uuid4())},
        {"unknown_field": True},
        {"price_cop": 300000, "code": "CANNOT_CHANGE"},
    ],
)
async def test_r4_patch_rejects_forbidden_fields(client: AsyncClient, body: dict[str, Any]) -> None:
    plan = await seed_plan()
    response = await client.patch(
        f"/admin/plans/{plan.plan_id}", json=body, headers=await login_headers(client, "90000000")
    )
    assert response.status_code == 422, response.text
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(type(plan), plan.plan_id)
        assert (saved.code, saved.event_type, saved.price_cop) == (
            "RITUAL_CORAZON",
            "ROMANTIC_DINNER",
            250000,
        )
        audits = await session.scalars(select(AuditEvent).where(AuditEvent.entity == "plan"))
        assert list(audits) == []


async def test_r4_plans_have_no_create_or_delete_endpoint(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    assert (await client.get("/admin/plans", headers=headers)).status_code == 200
    assert (await client.post("/admin/plans", headers=headers, json={})).status_code == 405
    assert (await client.delete(f"/admin/plans/{uuid4()}", headers=headers)).status_code == 405


@pytest.mark.parametrize("event_type", ["WEDDING", "UNKNOWN"])
async def test_r2_database_rejects_invalid_plan_type_bypassing_orm(
    client: AsyncClient,
    event_type: str,
) -> None:
    model = require_symbol("app.plan.models", "Plan")
    async with app.state.db_sessionmaker() as session:
        with pytest.raises(IntegrityError) as failure:
            await session.execute(
                insert(model.__table__).values(
                    plan_id=uuid4(),
                    code="INVALID",
                    name="Inválido",
                    event_type=event_type,
                    price_cop=1,
                    duration_minutes=180,
                    sort_order=0,
                )
            )
        assert failure.value.orig.sqlstate == "23514"  # CHECK, not enum/type or NOT NULL
        await session.rollback()


async def test_r2_database_enforces_unique_plan_code(client: AsyncClient) -> None:
    plan = await seed_plan()
    async with app.state.db_sessionmaker() as session:
        with pytest.raises(IntegrityError) as failure:
            await session.execute(
                insert(type(plan).__table__).values(
                    plan_id=uuid4(),
                    code=plan.code,
                    name="Duplicado",
                    event_type="PROPOSAL",
                    price_cop=1,
                    duration_minutes=180,
                    sort_order=0,
                )
            )
        assert failure.value.orig.sqlstate == "23505"
        await session.rollback()


async def test_r3_seed_eight_plans_and_preserve_admin_price_on_second_run(
    client: AsyncClient,
) -> None:
    load = require_symbol("scripts.load_plans", "load_plans")
    model = require_symbol("app.plan.models", "Plan")
    await load(app.state.db_sessionmaker)
    async with app.state.db_sessionmaker() as session:
        plans = list(await session.scalars(select(model)))
    assert len(plans) == 8
    assert {
        plan.name: (
            plan.event_type,
            plan.price_cop,
            plan.duration_minutes,
            plan.exclusive,
            plan.weekend_only,
        )
        for plan in plans
    } == EXPECTED_PLANS
    assert all(plan.active for plan in plans)
    assert len({plan.code for plan in plans}) == 8
    target = next(plan for plan in plans if plan.name == "Ritual del Corazón")
    assert target.code == "RITUAL_CORAZON"
    headers = await login_headers(client, "90000000")
    patched = await client.patch(
        f"/admin/plans/{target.plan_id}",
        headers=headers,
        json={"price_cop": 321000, "active": False},
    )
    assert patched.status_code == 200, patched.text
    async with app.state.db_sessionmaker() as session:
        before = {
            plan.code: {c.name: getattr(plan, c.name) for c in model.__table__.columns}
            for plan in await session.scalars(select(model))
        }
    await load(app.state.db_sessionmaker)
    async with app.state.db_sessionmaker() as session:
        after = {
            plan.code: {c.name: getattr(plan, c.name) for c in model.__table__.columns}
            for plan in await session.scalars(select(model))
        }
    assert after == before, "El segundo seed no debe modificar ni timestamps ni ediciones"


async def test_r4_list_filters_status_from_to_and_detail(client: AsyncClient) -> None:
    rows = [
        await seed_reservation(
            status,
            starts_at=START + timedelta(days=index),
            ends_at=START + timedelta(days=index, hours=3),
        )
        for index, status in enumerate(STATUSES)
    ]
    headers = await login_headers(client, "90000000")
    cases = [
        ({}, rows),
        ({"status": "RESERVED"}, [rows[2]]),
        ({"from": (START + timedelta(hours=1)).isoformat()}, rows[1:]),
        ({"to": (START + timedelta(days=3, hours=1)).isoformat()}, rows[:4]),
        (
            {
                "from": (START + timedelta(hours=1)).isoformat(),
                "to": (START + timedelta(days=3, hours=1)).isoformat(),
                "status": "RESERVED",
            },
            [rows[2]],
        ),
    ]
    for params, expected in cases:
        response = await client.get("/admin/reservations", headers=headers, params=params)
        assert response.status_code == 200, response.text
        assert {item["reservation_id"] for item in response.json()} == {
            str(item.reservation_id) for item in expected
        }
    row = rows[0]
    response = await client.get(f"/admin/reservations/{row.reservation_id}", headers=headers)
    assert response.status_code == 200, response.text
    detail = response.json()
    for key in ("reservation_id", "lead_id", "event_id", "plan_id"):
        assert detail[key] == str(getattr(row, key))
    assert detail["conversation_id"] == row.conversation_id
    assert detail["customer_id"] == row.customer_id
    assert detail["price_cop"] == 250000
    assert detail["amount_paid_cop"] == 0
    assert detail["payment_kind"] is None
    assert detail["hold_expires_at"] is None
    assert detail["external_calendar_id"] is None
    assert detail["calendar_status"] == "NONE"
    assert datetime.fromisoformat(detail["starts_at"]) == START
    assert datetime.fromisoformat(detail["ends_at"]) == START + timedelta(hours=3)


@pytest.mark.parametrize("status", STATUSES)
async def test_r4_cancel_respects_matrix_and_audits_once(client: AsyncClient, status: str) -> None:
    row = await seed_reservation(status)
    headers = await login_headers(client, "90000000")
    response = await client.post(
        f"/admin/reservations/{row.reservation_id}/cancel",
        headers=headers,
        json={"note": "Cliente solicita cancelar"},
    )
    allowed = status in {"PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED"}
    assert response.status_code == (200 if allowed else 409), response.text
    audits = await reservation_audits()
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(type(row), row.reservation_id)
        assert saved.status == ("CANCELLED" if allowed else status)
    if allowed:
        assert response.json()["status"] == "CANCELLED"
        assert len(audits) == 1
        assert audits[0].old_value["status"] == status
        assert audits[0].new_value["status"] == "CANCELLED"
        assert audits[0].actor == "Admin B1a"
        assert audits[0].reason == "Cliente solicita cancelar"
        repeated = await client.post(
            f"/admin/reservations/{row.reservation_id}/cancel",
            headers=headers,
            json={"note": "Reintento"},
        )
        assert repeated.status_code == 409
        assert len(await reservation_audits()) == 1
    else:
        assert audits == []


@pytest.mark.parametrize("body", [{}, {"note": ""}, {"note": "  "}])
async def test_r4_cancel_requires_nonempty_note(client: AsyncClient, body: dict[str, str]) -> None:
    row = await seed_reservation()
    response = await client.post(
        f"/admin/reservations/{row.reservation_id}/cancel",
        json=body,
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 422, response.text
    assert await reservation_audits() == []
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(type(row), row.reservation_id)).status == "PAYMENT_PENDING"


async def test_r5_evidence_reservation_fk_nullable_valid_and_invalid(client: AsyncClient) -> None:
    assert "reservation_id" in PaymentEvidence.__table__.c
    row = await seed_reservation()
    empty = await seed_evidence()
    linked = await seed_evidence(reservation_id=row.reservation_id)
    assert empty.reservation_id is None
    assert linked.reservation_id == row.reservation_id
    with pytest.raises(IntegrityError) as failure:
        await seed_evidence(reservation_id=uuid4())
    assert failure.value.orig.sqlstate == "23503"


@pytest.mark.parametrize("action,status", [("accept", "ACCEPTED"), ("reject", "REJECTED")])
async def test_r5_existing_review_without_reservation_is_unchanged(
    client: AsyncClient,
    action: str,
    status: str,
) -> None:
    # Must be green on G2: do not depend on the new column/model being present.
    evidence = await seed_evidence()
    headers = await login_headers(client, "90000000")
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/{action}",
        headers=headers,
        json={"note": "Revisión manual", **({"amount_cop": 50000} if action == "accept" else {})},
    )
    assert response.status_code == 200, response.text
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(PaymentEvidence, evidence.id)
        assert saved.review_status == status
        assert saved.review_note == "Revisión manual"
        assert saved.reviewed_by_agent_id is not None
        assert saved.reviewed_at is not None
        audits = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "PAYMENT_EVIDENCE_REVIEWED")
            )
        )
        assert len(audits) == 1
    repeated = await client.post(
        f"/admin/payment-evidence/{evidence.id}/{action}",
        headers=headers,
        json={"note": "Reintento", **({"amount_cop": 50000} if action == "accept" else {})},
    )
    assert repeated.status_code == 409


@pytest.mark.parametrize("action", ["accept", "reject"])
async def test_r5_b2_review_returns_linked_reservation_to_pending(
    client: AsyncClient,
    action: str,
) -> None:
    row = await seed_reservation("PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/{action}",
        headers=await login_headers(client, "90000000"),
        json={"note": "Revisión manual", **({"amount_cop": 50000} if action == "accept" else {})},
    )
    assert response.status_code == 200, response.text
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(type(row), row.reservation_id)
        assert saved.status == "PAYMENT_PENDING"
        assert saved.amount_paid_cop == (50000 if action == "accept" else 0)
        assert saved.calendar_status == "NONE"
    assert len(await reservation_audits()) == 1
