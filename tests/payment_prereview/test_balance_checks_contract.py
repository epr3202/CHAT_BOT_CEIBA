"""Declared D5 contract extension: an AI balance proposal compares the unpaid total."""

from datetime import UTC, datetime

import pytest

from app.payment.review import evaluate_receipt
from app.reservation.models import Reservation
from tests.payment_prereview.test_contracts import configured, extraction

NOW = datetime(2026, 10, 1, 15, tzinfo=UTC)


@pytest.mark.parametrize("amount,expected", [(100000, "WARN"), (200000, "OK")])
def test_reserved_receipt_amount_compares_balance_instead_of_already_paid_deposit(
    monkeypatch: pytest.MonkeyPatch, amount: int, expected: str
) -> None:
    settings = configured(monkeypatch)
    reservation = Reservation(
        status="RESERVED", price_cop=400000, amount_paid_cop=200000, created_at=NOW
    )
    checks, _, proposed_amount = evaluate_receipt(
        extraction(amount_cop=amount),
        reservation=reservation,
        settings=settings,
        previous_references=set(),
        now=NOW,
    )
    assert next(check for check in checks if check.code == "AMOUNT").result == expected
    assert proposed_amount == amount
