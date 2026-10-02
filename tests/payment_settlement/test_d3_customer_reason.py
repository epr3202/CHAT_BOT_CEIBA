import pytest
from sqlalchemy import select

from app.channel.models import Outbox
from app.conversation.models import KnowledgeEntry
from app.main import app
from app.payment.models import PaymentEvidence
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation


@pytest.mark.parametrize(
    "reason,error",
    [
        (None, "Escribe el motivo que verá el cliente"),
        ("  ", "Escribe el motivo que verá el cliente"),
        ("Mira https://x.co", "No incluyas enlaces en el motivo"),
        ("www.ejemplo.co", "No incluyas enlaces en el motivo"),
    ],
)
async def test_d3_requires_customer_reason_without_urls(client, reason, error):
    evidence = await seed_evidence()
    body = {"note": "Nota interna"}
    if reason is not None:
        body["customer_reason"] = reason
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        json=body,
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 422, response.text
    assert error in response.text
    async with app.state.db_sessionmaker() as session:
        assert (await session.get(PaymentEvidence, evidence.id)).review_status == "PENDING_REVIEW"


async def test_d3_internal_note_separate_and_visible_reason_sanitized(client):
    assert "customer_reason" in PaymentEvidence.__table__.c
    evidence = await seed_evidence()
    async with app.state.db_sessionmaker.begin() as session:
        session.add(
            KnowledgeEntry(
                code="RESP-PAYMENT-005",
                version=100,
                category="Pagos",
                question_summary="Rechazo",
                status="APPROVED",
                answer_template="No se pudo validar. {rejection_reason_customer_safe}",
                allowed_variables=["rejection_reason_customer_safe"],
            )
        )
    reason = "  Imagen\n borrosa\t " + "x" * 220
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        json={
            "note": "Nota privada del asesor",
            "customer_reason": reason,
        },
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 200, response.text
    async with app.state.db_sessionmaker() as session:
        saved = await session.get(PaymentEvidence, evidence.id)
        assert saved.review_note == "Nota privada del asesor"
        assert saved.customer_reason == " ".join(reason.split())[:200]
        row = await session.scalar(select(Outbox))
        assert row is not None and saved.customer_reason in row.payload["text"]["body"]
        assert "privada" not in row.payload["text"]["body"]


async def test_d3_linked_evidence_keeps_booking_rejection(client):
    row = await seed_reservation("PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=row.reservation_id)
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        json={
            "note": "Nota interna de reserva",
        },
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == 200, response.text
