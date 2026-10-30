from datetime import datetime, timedelta
from importlib import import_module
from typing import Any

from sqlalchemy import select

from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.clock import BOOKING_NOW
from tests.visit_booking_guard.helpers import BOGOTA, Harness

# Literal case A remains fixed to its own clock, independent of the system date.
NOW = BOOKING_NOW + timedelta(days=21, hours=6, minutes=10)
START = (NOW + timedelta(days=28)).astimezone(BOGOTA).replace(hour=19, minute=0)
AVAILABLE = "RESP-AVAILABILITY-AVAILABLE-001"
LODGING = "RESP-ACCOMMODATION-ROMANTIC-001"
AGENDA_ERROR = "RESP-BOOKING-AGENDA-ERROR-001"
CONFIRM_AVAILABILITY = "CONFIRM_AVAILABILITY_BOOKING"
NEW_TEMPLATES = {
    LODGING: ("plan_name",),
    AVAILABLE: ("plan_name", "date", "time"),
    AGENDA_ERROR: ("plan_name", "date", "time"),
}


def symbol(module: str, name: str, fallback: Any = None) -> Any:
    try:
        loaded = import_module(module)
    except ModuleNotFoundError as exc:
        assert exc.name != module, f"G2: falta {module}"
        raise
    value = getattr(loaded, name, fallback)
    assert value is not None, f"G2: falta {module}.{name}"
    return value


async def get_plan(harness: Harness, code: str = "PETALOS_ESTRELLAS") -> Plan:
    return next(plan for plan in await harness.rows(Plan) if plan.code == code)


async def seed_booking(
    harness: Harness,
    *,
    code: str = "PETALOS_ESTRELLAS",
    pending: str | None = "SELECT_BOOKING_DATETIME",
    full_name: str | None = "Cliente Sintético",
    inquiry: bool = False,
    catalog: bool = False,
    starts_at: datetime = START,
) -> Plan:
    plan = await get_plan(harness, code)
    await harness.seed(event_type=plan.event_type, pending=pending, full_name=full_name)
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        row = await session.get(Conversation, conversation.id)
        row.booking_draft = {
            "plan_id": str(plan.plan_id),
            "plan_code": plan.code,
            "date": starts_at.date().isoformat(),
            "time": starts_at.strftime("%H:%M"),
            "date_confirmation": False,
            **({"inquiry_only": True} if inquiry else {}),
        }
        if catalog:
            row.last_question_code = (
                "RESP-EVENTS-PROPOSAL-001"
                if plan.event_type == "PROPOSAL"
                else "RESP-EVENTS-ROMANTIC-001"
            )
    return plan


async def pending_request(harness: Harness, plan: Plan) -> Reservation:
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        customer = await session.get(Customer, conversation.customer_id)
        event = await session.scalar(
            select(Event).where(Event.lead_id == conversation.active_lead_id)
        )
        reservation = Reservation(
            customer_id=customer.id,
            conversation_id=conversation.id,
            lead_id=conversation.active_lead_id,
            event_id=event.event_id,
            plan_id=plan.plan_id,
            starts_at=START,
            ends_at=START + timedelta(minutes=plan.duration_minutes),
            price_cop=plan.price_cop,
            amount_paid_cop=0,
            status="PAYMENT_PENDING",
            calendar_status="NONE",
        )
        session.add(reservation)
        await session.flush()
        return reservation


def require_overnight_columns() -> None:
    assert {"overnight", "checkin_from", "checkout_time"} <= set(Plan.__table__.columns.keys()), (
        "G2: faltan columnas del plan con pernoctación"
    )


def require_inquiry_pending() -> None:
    assert CONFIRM_AVAILABILITY in symbol("app.conversation.pending_actions", "PENDING_ACTIONS"), (
        "G2: falta CONFIRM_AVAILABILITY_BOOKING"
    )
