from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from structlog.contextvars import bound_contextvars, merge_contextvars
from structlog.testing import capture_logs

from app.audit.models import AuditEvent
from app.config.settings import get_settings
from app.handoff.models import Handoff
from app.orchestrator import booking_flow
from app.orchestrator.booking_flow import BookingAgendaService
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.availability_lodging.helpers import AGENDA_ERROR, START, get_plan, seed_booking
from tests.booking_conversation.helpers import code, draft_of
from tests.visit_booking_guard.helpers import BOGOTA, Harness


async def test_R_calendar_error_is_typed_and_logged(harness: Harness) -> None:
    plan = await get_plan(harness)
    harness.calendar.raise_on.add("list_events")
    request_id = str(uuid4())
    with (
        bound_contextvars(request_id=request_id),
        capture_logs(processors=[merge_contextvars]) as logs,
    ):
        result = await BookingAgendaService(harness.db, get_settings()).booking_availability(
            plan.plan_id, START, plan.duration_minutes
        )
    assert result is not None, "CalendarUnavailableError debe producir BookingAvailabilityFailure"
    assert type(result).__name__ == "BookingAvailabilityFailure"
    assert result.reason == "CALENDAR_UNAVAILABLE"
    assert result.error_class == "CalendarUnavailableError"
    errors = [entry for entry in logs if entry.get("log_level") == "error"]
    assert any(
        entry.get("request_id") == request_id
        and entry.get("plan_code") == plan.code
        and entry.get("starts_at") in {START, START.isoformat()}
        and entry.get("error_class") == "CalendarUnavailableError"
        for entry in errors
    ), errors
    assert all("fake calendar listing failed" not in str(entry) for entry in errors)


@pytest.mark.parametrize("cause", ["PLAN_INACTIVE", "PLAN_MISMATCH"])
async def test_R_invalid_plan_returns_failure(harness: Harness, cause: str) -> None:
    plan = await get_plan(harness)
    if cause == "PLAN_INACTIVE":
        async with harness.db.begin() as session:
            (await session.get(Plan, plan.plan_id)).active = False
    result = await BookingAgendaService(harness.db, get_settings()).booking_availability(
        plan.plan_id, START, plan.duration_minutes + (1 if cause == "PLAN_MISMATCH" else 0)
    )
    assert result is not None, f"Se requiere Failure({cause})"
    assert type(result).__name__ == "BookingAvailabilityFailure"
    assert result.reason == cause
    assert hasattr(result, "error_class")


async def test_R_case_A_failure_audits_overrides_and_preserves_draft(harness: Harness) -> None:
    plan = await seed_booking(harness)
    assert (plan.event_type, plan.code, START) == (
        "PROPOSAL",
        "PETALOS_ESTRELLAS",
        datetime(2026, 11, 17, 19, tzinfo=BOGOTA),
    )
    before = draft_of(await harness.conversation())
    harness.calendar.raise_on.add("list_events")
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    failures = [
        a for a in await harness.rows(AuditEvent) if a.action == "BOOKING_AVAILABILITY_FAILED"
    ]
    observed = {
        "codes": harness.codes,
        "draft_keys": sorted(getattr(await harness.conversation(), "booking_draft", None) or {}),
        "handoff_reasons": [row.reason for row in await harness.rows(Handoff)],
    }
    assert len(failures) == 1, f"Falta BOOKING_AVAILABILITY_FAILED; observado: {observed}"
    failure = failures[0]
    assert (failure.entity, failure.reason) == ("conversation", "CALENDAR_UNAVAILABLE")
    assert set(failure.new_value) == {
        "plan_code",
        "starts_at",
        "duration_minutes",
        "error_class",
        "request_id",
    }
    assert failure.new_value["plan_code"] == plan.code
    assert failure.new_value["duration_minutes"] == 180
    assert failure.new_value["error_class"] == "CalendarUnavailableError"
    assert str(failure.request_id) == str(failure.new_value["request_id"])
    assert harness.codes == [AGENDA_ERROR]
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert draft_of(conversation) == before
    assert [row.reason for row in await harness.rows(Handoff)] == ["SYSTEM_ERROR"]
    assert await harness.rows(Reservation) == []
    assert harness.calendar.created_event_ids == []


async def test_V_low_confidence_handoff_still_clears_draft(harness: Harness) -> None:
    await seed_booking(harness, pending="SELECT_BOOKING_TIME")
    await harness.send("???")
    await harness.send("???")
    await harness.assert_completed()
    assert (await harness.conversation()).booking_draft is None
    assert [row.reason for row in await harness.rows(Handoff)] == ["LOW_CONFIDENCE"]


async def test_R_weekend_only_tuesday_asks_date(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = await seed_booking(harness)
    assert START.weekday() == 1
    reasons = []
    original = booking_flow.validate_booking_window

    def observe(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        reasons.append(result.reason)
        return result

    monkeypatch.setattr(booking_flow, "validate_booking_window", observe)
    async with harness.db.begin() as session:
        (await session.scalar(select(Plan).where(Plan.plan_id == plan.plan_id))).weekend_only = True
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    assert "WEEKEND_ONLY" in reasons
    assert harness.codes == [code("DATETIME")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_DATETIME"
    assert await harness.rows(Handoff) == []


async def test_V_regular_plan_tuesday_continues(harness: Harness) -> None:
    await seed_booking(harness)
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("CONFIRM")]
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert await harness.rows(Reservation) == []
