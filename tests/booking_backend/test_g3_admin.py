from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.calendar.adapter import FakeCalendarAdapter
from tests.booking_backend.helpers import START
from tests.booking_backend.test_integration import client  # noqa: F401
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation


@pytest.mark.parametrize("case", ["available", "outside_hours", "calendar_down"])
async def test_g3_availability_empty_window_and_provider_failure(
    client: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    fake = FakeCalendarAdapter(raise_on={"list_events"} if case == "calendar_down" else set())
    monkeypatch.setattr("app.admin.routes.get_calendar_adapter", lambda _settings: fake)
    row = await seed_reservation(starts_at=START, ends_at=START + timedelta(hours=3))
    start = START if case != "outside_hours" else START.replace(hour=10)
    response = await client.get(
        "/admin/reservations/availability",
        params={"plan_id": str(row.plan_id), "starts_at": start.isoformat()},
        headers=await login_headers(client, "90000000"),
    )
    assert response.status_code == (503 if case == "calendar_down" else 200)
    if case != "calendar_down":
        assert response.json()["available"] is (case == "available")
        assert response.json()["blockers"] == []
        assert response.json()["window"] == {
            "ok": case == "available",
            "reason": None if case == "available" else "OUTSIDE_HOURS",
        }
