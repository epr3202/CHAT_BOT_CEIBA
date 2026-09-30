from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.b1a_contracts import EXPECTED_PLANS
from tests.booking_backend.helpers import START, plan, settings, symbol

MODULE = "app.reservation.booking"


@pytest.mark.parametrize("same_date", [False, True])
async def test_r4_create_fields_audits_and_no_commit(same_date: bool) -> None:
    create = symbol(MODULE, "create_pending_reservation")
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    selected = plan()
    lead = Lead(lead_id=uuid4())
    event = Event(
        event_id=uuid4(),
        lead_id=lead.lead_id,
        event_type=selected.event_type,
        event_date=START.date() if same_date else None,
        event_date_type="EXACT" if same_date else "UNKNOWN",
    )
    reservation = await create(
        session,
        lead=lead,
        event=event,
        plan=selected,
        conversation=Conversation(id=10),
        customer=Customer(id=20),
        starts_at=START,
        actor="SYSTEM",
        request_id="r4",
    )
    assert isinstance(reservation, Reservation)
    assert (
        reservation.lead_id,
        reservation.event_id,
        reservation.plan_id,
        reservation.conversation_id,
        reservation.customer_id,
    ) == (lead.lead_id, event.event_id, selected.plan_id, 10, 20)
    assert (reservation.starts_at, reservation.ends_at) == (START, START + timedelta(hours=3))
    assert reservation.price_cop == 250000 and reservation.amount_paid_cop == 0
    assert reservation.status == "PAYMENT_PENDING" and reservation.calendar_status == "NONE"
    assert reservation.hold_expires_at is None and reservation.external_calendar_id is None
    assert event.plan_id == selected.plan_id
    assert event.event_date == START.date() and event.event_date_type == "EXACT"
    audits = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuditEvent)
    ]
    assert {a.action for a in audits} == (
        {"RESERVATION_CREATED"} if same_date else {"RESERVATION_CREATED", "EVENT_DATE_CAPTURED"}
    )
    created = next(a for a in audits if a.action == "RESERVATION_CREATED")
    assert created.entity == "reservation" and created.actor == "SYSTEM"
    assert created.request_id == "r4" and created.reason
    assert created.new_value["reservation_id"] == str(reservation.reservation_id)
    assert created.new_value["plan_code"] == selected.code
    assert created.new_value["price_cop"] == 250000
    assert created.new_value["starts_at"]
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("changes", [{"active": False}, {"event_type": "PROPOSAL"}])
async def test_r4_reject_invalid_plan(changes: dict) -> None:
    create = symbol(MODULE, "create_pending_reservation")
    error = symbol(MODULE, "InvalidBookingPlan")
    assert issubclass(error, ValueError)
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    with pytest.raises(error):
        await create(
            session,
            lead=Lead(lead_id=uuid4()),
            event=Event(event_type="ROMANTIC_DINNER"),
            plan=plan(**changes),
            conversation=Conversation(id=1),
            customer=Customer(id=1),
            starts_at=START,
            actor="SYSTEM",
            request_id="r4-invalid",
        )
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "name,price,expected",
    [
        *[(name, values[1], values[1] // 2) for name, values in EXPECTED_PLANS.items()],
        ("impar", 333000, 167000),
    ],
)
def test_r4_deposit_seed_and_rounding(name: str, price: int, expected: int) -> None:
    deposit = symbol(MODULE, "deposit_amount")
    assert deposit(price) == expected
    assert deposit(plan(name=name, price_cop=price)) == expected


async def test_r5_already_linked_is_noop() -> None:
    attach = symbol(MODULE, "attach_payment_evidence")
    session = AsyncMock(spec=AsyncSession)
    evidence = PaymentEvidence(reservation_id=uuid4())
    original = evidence.reservation_id
    await attach(session, evidence, request_id="r5-linked")
    assert evidence.reservation_id == original
    session.execute.assert_not_called()
    session.scalar.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_settings_defaults() -> None:
    config = settings()
    expected = {
        "self_service_booking_enabled": False,
        "booking_exclusivity_keyword": "exclusividad",
        "booking_hours_start": "12:00",
        "booking_hours_end": "21:00",
        "booking_min_lead_days": 1,
        "booking_deposit_percent": 50,
    }
    assert {key: getattr(config, key, None) for key in expected} == expected
