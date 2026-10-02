from sqlalchemy import select
from starlette.requests import Request

from app.admin.routes import notify_payment_after_commit
from app.audit.models import AuditEvent
from app.channel.models import Outbox
from app.conversation.models import KnowledgeEntry
from app.main import app
from app.payment.models import PaymentEvidence
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence


async def test_f4_rejection_without_customer_reason_defers_and_audits(client):
    evidence = await seed_evidence(review_status="REJECTED")
    async with app.state.db_sessionmaker.begin() as session:
        session.add(
            KnowledgeEntry(
                code="RESP-PAYMENT-005",
                version=100,
                category="Pagos",
                question_summary="Rechazo",
                answer_template="No validamos el pago. {rejection_reason_customer_safe}",
                allowed_variables=["rejection_reason_customer_safe"],
                status="APPROVED",
            )
        )
    request = Request({"type": "http", "app": app})
    try:
        result = await notify_payment_after_commit(request, evidence.id, "REJECTED", "f4")
    except (ValueError, TypeError) as error:
        raise AssertionError(
            "El rechazo sin motivo visible debe diferirse sin excepción"
        ) from error
    assert result == "DEFERRED"
    async with app.state.db_sessionmaker() as session:
        assert await session.scalar(select(Outbox)) is None
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "PAYMENT_NOTIFICATION_SKIPPED")
        )
        assert audit is not None
        assert audit.reason == "Rechazo sin motivo visible para el cliente"
        assert (await session.get(PaymentEvidence, evidence.id)).customer_reason is None
