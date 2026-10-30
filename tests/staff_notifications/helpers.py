from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.main import app
from app.payment.models import PaymentEvidence
from tests.b1a_contracts import require_symbol
from tests.clock import BALANCE_NOW
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation

NOW = BALANCE_NOW
PHONE = "+573000000123"


def models() -> tuple[Any, Any]:
    return (
        require_symbol("app.notifications.models", "NotificationRecipient"),
        require_symbol("app.notifications.models", "StaffOutbox"),
    )


async def recipient(**changes: Any) -> Any:
    model, _ = models()
    async with app.state.db_sessionmaker.begin() as session:
        row = model(
            display_name="Asesor de prueba",
            phone_number=changes.pop("phone_number", PHONE),
            **changes,
        )
        session.add(row)
        await session.flush()
    return row


async def outbox(target: Any, *, with_source: bool = False, **changes: Any) -> Any:
    _, model = models()
    values = dict(
        recipient_id=target.id,
        event_kind="EVIDENCE_RECEIVED",
        source_entity="payment_evidence",
        source_id="123",
        params=["Cliente", "Plan", "7 de octubre a las 7:00 p. m.", "$125.000"],
        created_at=NOW,
        next_attempt_at=NOW,
    )
    values.update(changes)
    if with_source:
        # PR49 validates the domain source before delivery. Window/retry tests
        # need a real pending receipt; inbound-silence tests intentionally do not.
        reservation = await seed_reservation(status="PAYMENT_REVIEW")
        async with app.state.db_sessionmaker.begin() as session:
            message = Message(
                external_message_id=f"staff-source-{uuid4()}",
                conversation_id=reservation.conversation_id,
                customer_id=reservation.customer_id,
                channel="WHATSAPP",
                direction="INBOUND",
                message_type="image",
                content={},
            )
            session.add(message)
            await session.flush()
            evidence = PaymentEvidence(
                conversation_id=reservation.conversation_id,
                customer_id=reservation.customer_id,
                message_id=message.id,
                reservation_id=reservation.reservation_id,
                media_id="synthetic-staff-source",
                mime_type="image/jpeg",
                declared_sha256="0" * 64,
                review_status="PENDING_REVIEW",
            )
            session.add(evidence)
            await session.flush()
            values["source_id"] = str(evidence.id)
    async with app.state.db_sessionmaker.begin() as session:
        row = model(**values)
        session.add(row)
        await session.flush()
    return row


async def rows(model: Any) -> list[Any]:
    async with app.state.db_sessionmaker() as session:
        return list(await session.scalars(select(model).order_by(model.id)))


async def audits(action: str) -> list[AuditEvent]:
    async with app.state.db_sessionmaker() as session:
        return list(await session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


async def fresh(target: Any, hours: float = 1) -> None:
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(type(target), target.id)
        saved.last_inbound_at = NOW - timedelta(hours=hours)
