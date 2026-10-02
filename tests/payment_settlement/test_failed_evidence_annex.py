"""F2: failed downloads cannot become payments; decisions remain auditable."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.admin import routes
from app.audit.models import AuditEvent
from app.channel.models import Outbox
from app.main import app
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from app.reservation.settlement import accept_payment
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation


@pytest.mark.parametrize("linked", [False, True])
async def test_failed_permanent_accept_409_without_side_effects(client, monkeypatch, linked):
    reservation = await seed_reservation(status="PAYMENT_REVIEW") if linked else None
    evidence = await seed_evidence(
        download_status="FAILED_PERMANENT",
        **({"reservation_id": reservation.reservation_id} if reservation else {}),
    )

    async def forbidden_calendar(*args, **kwargs):
        pytest.fail("A failed download must be rejected before consulting Calendar")

    monkeypatch.setattr(routes, "fetch_booking_context", forbidden_calendar)
    headers = await login_headers(client, "90000000")
    async with app.state.db_sessionmaker() as session:
        before_audits = list(await session.scalars(select(AuditEvent.id).order_by(AuditEvent.id)))
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=headers,
        json={"amount_cop": 125000},
    )
    assert response.status_code == 409, response.text
    assert "descarga" in response.json()["detail"].lower()
    async with app.state.db_sessionmaker() as session:
        stored = await session.get(PaymentEvidence, evidence.id)
        assert stored.review_status == "PENDING_REVIEW"
        assert stored.amount_cop is None and stored.reviewed_by_agent_id is None
        assert list(await session.scalars(select(Outbox))) == []
        assert list(await session.scalars(select(AuditEvent.id).order_by(AuditEvent.id))) == (
            before_audits
        )
        if reservation:
            stored_reservation = await session.get(Reservation, reservation.reservation_id)
            assert stored_reservation.status == "PAYMENT_REVIEW"
            assert stored_reservation.amount_paid_cop == 0


async def test_failed_permanent_service_accept_is_rejected(client):
    evidence = await seed_evidence(download_status="FAILED_PERMANENT")
    async with app.state.db_sessionmaker() as session, session.begin():
        stored = await session.get(PaymentEvidence, evidence.id, with_for_update=True)
        with pytest.raises(ValueError, match="descarga"):
            await accept_payment(
                session,
                evidence=stored,
                amount_cop=125000,
                actor="Admin B2",
                note=None,
                request_id="failed-download",
                calendar_blockers=[],
            )
        assert stored.review_status == "PENDING_REVIEW"


async def test_failed_permanent_human_rejection_keeps_d5_audits(client: AsyncClient):
    evidence = await seed_evidence(download_status="FAILED_PERMANENT")
    note = "No se pudo descargar el comprobante. Envía una nueva imagen."
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        headers=(await login_headers(client, "90000000")) | {"X-Request-ID": "failed-rejection"},
        json={"note": note, "customer_reason": note},
    )
    assert response.status_code == 200, response.text
    async with app.state.db_sessionmaker() as session:
        audits = list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.entity == "payment_evidence")
                .order_by(AuditEvent.id)
            )
        )
        assert [row.action for row in audits] == [
            "PAYMENT_EVIDENCE_REJECTED",
            "PAYMENT_EVIDENCE_REVIEWED",
        ]
        assert all(
            row.actor == "Admin B2" and row.request_id == "failed-rejection" and row.reason == note
            for row in audits
        )
        assert all(row.new_value["evidence_id"] == evidence.id for row in audits)
        assert (
            audits[1].new_value["customer_notification"]
            == (response.json()["customer_notification"])
        )


async def test_suppressed_outbox_reason_in_admin_timeline(client: AsyncClient):
    evidence = await seed_evidence()
    async with app.state.db_sessionmaker() as session, session.begin():
        row = Outbox(
            conversation_id=evidence.conversation_id,
            message_id=evidence.message_id,
            channel="WHATSAPP",
            recipient_phone_number="573000000222",
            payload={"type": "text", "text": {"body": "Respuesta aprobada"}},
            status="SUPPRESSED",
            delivery_reason="AUTOMATION_PAUSED",
        )
        session.add(row)
        await session.flush()
        outbox_id = row.id
    response = await client.get(
        f"/admin/conversations/{evidence.conversation_id}/messages",
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 200, response.text
    message = next(row for row in response.json() if row["id"] == f"outbox-{outbox_id}")
    assert message.get("delivery_reason") == "AUTOMATION_PAUSED"
