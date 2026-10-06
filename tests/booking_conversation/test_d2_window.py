from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import Settings, get_settings
from app.plan.models import Plan
from app.reservation.availability import fetch_booking_context, validate_booking_window
from tests.booking_backend.helpers import START, plan, settings
from tests.integration.helpers import login_headers
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "hour,minute,close,ok,reason",
    [
        (21, 0, "24:00", True, None),
        (21, 30, "24:00", False, "OUTSIDE_HOURS"),
        (11, 30, "24:00", False, "OUTSIDE_HOURS"),
        (12, 0, "24:00", True, None),
        (21, 0, "23:59", False, "OUTSIDE_HOURS"),
    ],
)
def test_d2_midnight_window(hour, minute, close, ok, reason):
    assert "booking_latest_start" in Settings.model_fields, "Falta BOOKING_LATEST_START"
    config = settings(BOOKING_HOURS_END=close, BOOKING_LATEST_START="21:00")
    start = START.replace(hour=hour, minute=minute)
    result = validate_booking_window(
        start, start + timedelta(hours=3), config, today=START.date() - timedelta(days=5)
    )
    assert (result.ok, result.reason) == (ok, reason)


async def test_d2_calendar_conflict_after_23(harness):
    assert "booking_latest_start" in Settings.model_fields
    config = settings(BOOKING_HOURS_END="24:00", BOOKING_LATEST_START="21:00")
    selected = plan(exclusive=True)
    start = START.replace(hour=21)
    harness.calendar.add_event(
        "a",
        "Evento existente — exclusividad",
        start.replace(hour=23),
        start.replace(hour=23, minute=30),
    )
    async with harness.db() as session:
        result = await fetch_booking_context(
            session,
            plan=selected,
            starts_at=start,
            ends_at=start + timedelta(hours=3),
            calendar=harness.calendar,
            settings=config,
        )
    assert not result.available


async def test_d2_calendar_guard_rejects_other_engine_transaction(harness: Harness) -> None:
    engine = create_async_engine(harness.db.kw["bind"].url)
    start = START.replace(hour=21)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            with pytest.raises(AssertionError, match="Calendar called while a transaction is open"):
                await harness.calendar.list_events(start, start + timedelta(hours=3), ["a"])
            await connection.commit()
            assert (
                await harness.calendar.list_events(start, start + timedelta(hours=3), ["a"]) == []
            )
    finally:
        await engine.dispose()


async def test_d2_panel_manual_and_reschedule(api, harness, monkeypatch):
    assert "booking_latest_start" in Settings.model_fields
    monkeypatch.setenv("BOOKING_HOURS_END", "24:00")
    monkeypatch.setenv("BOOKING_LATEST_START", "21:00")
    get_settings.cache_clear()
    selected = (await harness.rows(Plan))[0]
    headers = await login_headers(api, "90000000")
    start = START.replace(hour=21)
    response = await api.post(
        "/admin/reservations",
        headers=headers,
        json={
            "phone": "+573000000222",
            "full_name": "Cliente manual",
            "plan_id": str(selected.plan_id),
            "starts_at": start.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    reservation = response.json()
    end = __import__("datetime").datetime.fromisoformat(reservation["ends_at"])
    assert end == start + timedelta(hours=3)
    shifted = start + timedelta(days=1)
    response = await api.patch(
        f"/admin/reservations/{reservation['reservation_id']}/schedule",
        headers=headers,
        json={"starts_at": shifted.isoformat()},
    )
    assert response.status_code == 200, response.text
    assert __import__("datetime").datetime.fromisoformat(response.json()["ends_at"]) == (
        shifted + timedelta(hours=3)
    )
