"""Balance-reminder fixtures keep clock and reservation confirmation explicit."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.audit.models import AuditEvent
from app.config.settings import Settings
from app.customer.models import Customer
from app.main import app
from app.reservation.models import Reservation
from tests.b1a_contracts import require_symbol
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation

START = datetime(2026, 10, 11, 0, tzinfo=UTC)  # October 10, 19:00 in Bogotá.
EARLY = datetime(2026, 10, 7, 15, tzinfo=UTC)
DUE = datetime(2026, 10, 9, 15, tzinfo=UTC)
DUE_AT = START - timedelta(days=1)
RESERVED_AT = START - timedelta(days=7)


def reminder_contract() -> tuple[Any, Any, Any]:
    scheduler = require_symbol("app.reservation.reminders", "enqueue_balance_reminders")
    process = require_symbol(
        "app.notifications.customer_worker", "process_customer_notifications_once"
    )
    model = require_symbol("app.notifications.models", "CustomerNotification")
    assert "balance_overdue_at" in Reservation.__table__.columns
    for field in (
        "reservation_id",
        "customer_id",
        "kind",
        "phone_number",
        "params",
        "template_name",
        "status",
        "claim_token",
        "claimed_at",
        "last_error_code",
        "provider_message_id",
        "sent_at",
    ):
        assert field in model.__table__.columns, f"B4: falta customer_notification.{field}"
    return scheduler, process, model


def config(**changes: Any) -> Settings:
    for field in (
        "balance_reminders_enabled",
        "booking_reminder_days_before",
        "booking_reminder_time",
        "customer_template_balance_reminder_name",
        "staff_template_overdue_name",
    ):
        assert field in Settings.model_fields, f"B4: falta Settings.{field}"
    values = dict(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/ceiba_test",
        META_APP_SECRET="test",
        META_ACCESS_TOKEN="test",
        META_PHONE_NUMBER_ID="balance-test",
        OPENROUTER_API_KEY="test",
        BALANCE_REMINDERS_ENABLED=True,
        BOOKING_REMINDER_DAYS_BEFORE=3,
        BOOKING_REMINDER_TIME="10:00",
        CUSTOMER_TEMPLATE_BALANCE_REMINDER_NAME="recordatorio_saldo_reserva",
        STAFF_NOTIFICATIONS_ENABLED=True,
        STAFF_TEMPLATE_OVERDUE_NAME="aviso_saldo_vencido",
    )
    values.update(changes)
    return Settings(**values)


async def reserved(*, reserved_at: datetime = RESERVED_AT, **changes: Any) -> Reservation:
    values = dict(
        starts_at=START,
        ends_at=START + timedelta(hours=3),
        price_cop=400000,
        amount_paid_cop=200000,
        payment_kind="DEPOSIT",
        balance_due_at=DUE_AT,
        created_at=reserved_at - timedelta(hours=1),
        updated_at=reserved_at,
    )
    values.update(changes)
    row = await seed_reservation("RESERVED", **values)
    async with app.state.db_sessionmaker.begin() as session:
        customer = await session.get(Customer, row.customer_id)
        customer.full_name = "Ana María"
        session.add(
            AuditEvent(
                actor="Asesor B4",
                action="RESERVATION_STATUS_CHANGED",
                entity="reservation",
                old_value={
                    "status": "PAYMENT_REVIEW",
                    "reservation_id": str(row.reservation_id),
                },
                new_value={"status": "RESERVED", "reservation_id": str(row.reservation_id)},
                reason="Anticipo confirmado por asesor",
                request_id="b4-reserved-fixture",
                created_at=reserved_at,
            )
        )
    return row


async def entries(model: Any) -> list[Any]:
    async with app.state.db_sessionmaker() as session:
        return list(await session.scalars(select(model).order_by(model.id)))


async def reload_reservation(row: Reservation) -> Reservation:
    async with app.state.db_sessionmaker() as session:
        return await session.get(Reservation, row.reservation_id)


async def pay_in_full(row: Reservation) -> None:
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, row.reservation_id)
        saved.amount_paid_cop = saved.price_cop
        saved.payment_kind = "FULL"
        saved.balance_due_at = None
        saved.balance_overdue_at = None
