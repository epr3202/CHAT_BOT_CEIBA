"""B4 contract extension: a later payment deadline clears the old overdue marker."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.admin import routes
from tests.booking_balance.b4_helpers import reload_reservation, reserved
from tests.integration.helpers import login_headers
from tests.staff_notifications.helpers import audits

NOW = datetime(2026, 10, 9, 18, tzinfo=UTC)
OLD_START = datetime(2026, 10, 10, 17, tzinfo=UTC)
NEW_START = datetime(2026, 10, 17, 17, tzinfo=UTC)


class RescheduleClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


async def test_rescheduling_to_future_deadline_clears_overdue_and_keeps_reserved(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_due = OLD_START - timedelta(days=1)
    row = await reserved(
        reserved_at=NOW - timedelta(days=7),
        starts_at=OLD_START,
        ends_at=OLD_START + timedelta(hours=3),
        balance_due_at=old_due,
        balance_overdue_at=NOW,
    )
    headers = await login_headers(client, "90000000")
    # FastAPI resolves deferred endpoint annotations on its first request.
    monkeypatch.setattr(routes, "datetime", RescheduleClock)
    before = await client.get(
        "/admin/reservations", params={"balance_status": "overdue"}, headers=headers
    )
    assert before.status_code == 200
    assert [item["reservation_id"] for item in before.json()] == [str(row.reservation_id)]

    response = await client.patch(
        f"/admin/reservations/{row.reservation_id}/schedule",
        json={"starts_at": NEW_START.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    saved = await reload_reservation(row)
    assert saved.status == "RESERVED"
    assert saved.balance_overdue_at is None
    assert saved.balance_due_at == NEW_START - timedelta(days=1)
    assert saved.amount_paid_cop == 200000 and saved.payment_kind == "DEPOSIT"
    overdue = await client.get(
        "/admin/reservations", params={"balance_status": "overdue"}, headers=headers
    )
    assert overdue.status_code == 200 and overdue.json() == []
    pending = await client.get(
        "/admin/reservations", params={"balance_status": "pending"}, headers=headers
    )
    assert pending.status_code == 200
    assert [item["reservation_id"] for item in pending.json()] == [str(row.reservation_id)]

    rescheduled = await audits("RESERVATION_RESCHEDULED")
    assert len(rescheduled) == 1
    audit = rescheduled[0]
    assert audit.old_value["balance_due_at"] == old_due.isoformat()
    assert audit.old_value["balance_overdue_at"] == NOW.isoformat()
    assert audit.new_value["balance_due_at"] == (NEW_START - timedelta(days=1)).isoformat()
    assert audit.new_value["balance_overdue_at"] is None
    assert all(
        event.new_value.get("status") != "CANCELLED"
        for event in await audits("RESERVATION_STATUS_CHANGED")
    )
