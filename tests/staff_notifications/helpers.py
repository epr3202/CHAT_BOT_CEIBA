from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.audit.models import AuditEvent
from app.main import app
from tests.b1a_contracts import require_symbol

NOW = datetime(2026, 10, 2, 15, tzinfo=UTC)
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


async def outbox(target: Any, **changes: Any) -> Any:
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
