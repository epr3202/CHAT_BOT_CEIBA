from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.main import app
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence


async def test_g3_c2_accept_has_exactly_two_payment_evidence_audits(client: AsyncClient):
    evidence = await seed_evidence()
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(client, "90000000"),
        json={"amount_cop": 125000, "note": "Validado"},
    )
    assert response.status_code == 200
    async with app.state.db_sessionmaker() as session:
        rows = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.entity == "payment_evidence"))
        )
    assert [row.action for row in rows] == [
        "PAYMENT_EVIDENCE_ACCEPTED",
        "PAYMENT_EVIDENCE_REVIEWED",
    ]
    assert rows[0].new_value["amount_cop"] == 125000
    assert rows[1].new_value["result"] == "NO_RESERVATION"
    assert rows[1].new_value["customer_notification"] == response.json()["customer_notification"]
