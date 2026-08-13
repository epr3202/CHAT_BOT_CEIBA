from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.event.validation import (
    parse_customer_date_expression,
    validate_event_date_not_past,
    validate_event_date_triplet,
)
from app.lead.budget import calculate_budget_range, parse_cop_amount
from app.orchestrator.slot_filling import CaptureProgress, select_next_question


def test_date_triplet_invariant_accepts_entities_table_cases() -> None:
    exact = validate_event_date_triplet(date(2026, 12, 12), None, "EXACT", "12 de diciembre")
    approximate = validate_event_date_triplet(None, "2026-12", "APPROXIMATE", "en diciembre")
    flexible = validate_event_date_triplet(
        None, "2027-02", "FLEXIBLE", "cualquier sábado de febrero"
    )
    unknown = validate_event_date_triplet(None, None, "UNKNOWN", "todavía no sé")

    assert exact.date_resolved
    assert approximate.date_resolved
    assert flexible.date_resolved
    assert unknown.date_resolved


@pytest.mark.parametrize(
    ("event_date", "event_month", "event_date_type", "raw"),
    [
        (None, None, "EXACT", "12 de diciembre"),
        (date(2026, 12, 12), "2026-12", "APPROXIMATE", "en diciembre"),
        (date(2026, 12, 12), None, "FLEXIBLE", "cualquier sábado"),
        (None, "2026-12", "UNKNOWN", "todavía no sé"),
    ],
)
def test_date_triplet_invariant_rejects_inconsistent_combinations(
    event_date: date | None,
    event_month: str | None,
    event_date_type: str,
    raw: str,
) -> None:
    with pytest.raises(ValueError, match="INVALID_DATE_TRIPLET"):
        validate_event_date_triplet(event_date, event_month, event_date_type, raw)


def test_tc_collect_015_select_next_question_order_and_skips() -> None:
    assert select_next_question(CaptureProgress()) == "COLLECT_EVENT_TYPE"
    assert select_next_question(CaptureProgress(event_type="WEDDING")) == "COLLECT_GUEST_COUNT"
    assert (
        select_next_question(CaptureProgress(event_type="WEDDING", guest_count=45))
        == "COLLECT_EVENT_DATE"
    )
    assert (
        select_next_question(
            CaptureProgress(event_type="WEDDING", guest_count=45, date_resolved=True)
        )
        == "COLLECT_CUSTOMER_NAME"
    )
    assert (
        select_next_question(
            CaptureProgress(
                event_type="WEDDING",
                guest_count=45,
                date_resolved=True,
                full_name="Natalia",
            )
        )
        == "COLLECT_BUDGET"
    )
    assert (
        select_next_question(
            CaptureProgress(
                event_type="WEDDING",
                guest_count=45,
                date_resolved=True,
                full_name="Natalia",
                budget_data_status="DECLINED",
            )
        )
        == "COLLECT_SERVICES"
    )
    assert (
        select_next_question(
            CaptureProgress(
                event_type="WEDDING",
                guest_count=45,
                date_resolved=True,
                full_name="Natalia",
                budget_data_status="DECLINED",
                services_requested=True,
            )
        )
        is None
    )


def test_tc_collect_015_name_needing_confirmation_blocks_minimums() -> None:
    assert (
        select_next_question(
            CaptureProgress(
                event_type="WEDDING",
                guest_count=45,
                date_resolved=True,
                full_name="Natalia",
                full_name_needs_confirmation=True,
                budget_data_status="PROVIDED",
                services_requested=True,
            )
        )
        == "COLLECT_CUSTOMER_NAME"
    )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("10 millones", Decimal("10000000")),
        ("dos millones y medio", Decimal("2500000")),
        ("2.5M", Decimal("2500000")),
    ],
)
def test_parse_cop_amount(raw_value: str, expected: Decimal) -> None:
    assert parse_cop_amount(raw_value) == expected


@pytest.mark.parametrize("raw_value", ["", "-1000000", "menos dos millones"])
def test_parse_cop_amount_rejects_invalid_or_negative_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="INVALID_NUMBER"):
        parse_cop_amount(raw_value)


def test_budget_range_reference_calculation() -> None:
    assert calculate_budget_range(None) == "NOT_PROVIDED"
    assert calculate_budget_range(Decimal("2500000")) == "BELOW_REFERENCE"
    assert calculate_budget_range(Decimal("4000000")) == "REFERENCE_RANGE"
    assert calculate_budget_range(Decimal("12000000")) == "PREMIUM"


def test_date_validators_reject_past_and_invalid_calendar_dates() -> None:
    with pytest.raises(ValueError, match="PAST_DATE"):
        validate_event_date_not_past(date(2026, 1, 1), today=date(2026, 8, 13))
    with pytest.raises(ValueError, match="INVALID_CALENDAR_DATE"):
        parse_customer_date_expression("31 de febrero", today=date(2026, 8, 13))


def test_date_parser_infers_year_only_from_clear_context() -> None:
    approximate = parse_customer_date_expression("en diciembre", today=date(2026, 8, 13))
    flexible = parse_customer_date_expression(
        "cualquier sábado de febrero", today=date(2026, 8, 13)
    )

    assert approximate.event_month == "2026-12"
    assert approximate.event_date_type == "APPROXIMATE"
    assert flexible.event_month == "2027-02"
    assert flexible.event_date_type == "FLEXIBLE"


def test_date_parser_respects_explicit_year_for_approximate_month() -> None:
    approximate = parse_customer_date_expression("marzo de 2027", today=date(2026, 8, 13))

    assert approximate.event_month == "2027-03"
    assert approximate.event_date_type == "APPROXIMATE"


def test_date_parser_respects_explicit_year_for_exact_date() -> None:
    exact = parse_customer_date_expression(
        "12 de diciembre de 2027",
        today=date(2026, 8, 13),
    )

    assert exact.event_date == date(2027, 12, 12)
    assert exact.event_date_type == "EXACT"


def test_date_parser_rejects_explicit_past_year() -> None:
    with pytest.raises(ValueError, match="PAST_DATE"):
        parse_customer_date_expression("marzo de 2020", today=date(2026, 8, 13))
