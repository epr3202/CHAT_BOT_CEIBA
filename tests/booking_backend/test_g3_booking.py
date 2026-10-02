from datetime import UTC, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import app.models_registry  # noqa: F401
from app.calendar.adapter import CalendarUnavailableError, FakeCalendarAdapter
from app.config.settings import get_settings
from app.payment.models import PaymentEvidence
from app.reservation.availability import fetch_booking_context, validate_booking_window
from app.reservation.booking import attach_payment_evidence, deposit_amount
from app.reservation.models import Reservation
from tests.booking_backend.helpers import START, plan, settings


@pytest.mark.parametrize(
    "changes",
    [
        {"BOOKING_HOURS_START": "24:00"},
        {"BOOKING_HOURS_END": "12:00"},
        {"BOOKING_HOURS_START": "23:00"},
        {"BOOKING_MIN_LEAD_DAYS": -1},
        {"BOOKING_DEPOSIT_PERCENT": 0},
        {"BOOKING_DEPOSIT_PERCENT": 101},
        {"BOOKING_EXCLUSIVITY_KEYWORD": " "},
    ],
)
def test_g3_reject_invalid_configuration(changes: dict) -> None:
    with pytest.raises(ValidationError):
        settings(**changes)


def test_g3_deposit_uses_configured_percentage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKING_DEPOSIT_PERCENT", "33")
    get_settings.cache_clear()
    try:
        assert deposit_amount(333001) == 110000
    finally:
        get_settings.cache_clear()


def test_g3_window_naive_and_configured_lead_days() -> None:
    assert validate_booking_window(START.replace(tzinfo=None), START, settings()).reason == (
        "TIMEZONE_REQUIRED"
    )
    result = validate_booking_window(
        START,
        START + timedelta(hours=3),
        settings(BOOKING_MIN_LEAD_DAYS=3),
        today=START.date() - timedelta(days=2),
    )
    assert result.reason == "MIN_LEAD_DAYS"
    assert validate_booking_window(
        START.astimezone(UTC),
        START + timedelta(hours=3),
        settings(),
        today=START.date() - timedelta(days=1),
    ).ok


async def test_g3_evidence_customer_link_without_conversation() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    row = Reservation(reservation_id=uuid4(), status="PAYMENT_PENDING")
    session.scalar.return_value = row
    evidence = PaymentEvidence(customer_id=123, lead_id=uuid4(), conversation_id=None)
    result = await attach_payment_evidence(session, evidence, request_id="fallback")
    assert result is row and row.status == "PAYMENT_REVIEW"
    assert evidence.reservation_id == row.reservation_id
    query = session.scalar.call_args.args[0]
    assert "reservation.customer_id =" in str(query)
    assert evidence.customer_id in query.compile().params.values()
    assert "reservation.lead_id =" not in str(query)
    session.commit.assert_not_called()


async def test_g3_context_rejects_caller_transaction_without_ending_it() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction = Mock(return_value=True)
    with pytest.raises(ValueError, match="idle session"):
        await fetch_booking_context(
            session,
            plan=plan(),
            starts_at=START,
            ends_at=START + timedelta(hours=3),
            calendar=FakeCalendarAdapter(),
            settings=settings(),
        )
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.execute.assert_not_called()


async def test_g3_no_calendar_configuration_is_not_available() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction = Mock(return_value=False)
    session.new = session.dirty = session.deleted = set()
    config = settings().model_copy(update={"google_freebusy_calendar_ids": ""})
    with pytest.raises(CalendarUnavailableError):
        await fetch_booking_context(
            session,
            plan=plan(),
            starts_at=START,
            ends_at=START + timedelta(hours=3),
            calendar=FakeCalendarAdapter(),
            settings=config,
        )
