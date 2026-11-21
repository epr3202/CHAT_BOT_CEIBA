from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.booking_conversation.test_duplicate_reserved_guard_g2 import (
    approved_duplicate as approved_duplicate,
)
from tests.booking_conversation.test_duplicate_reserved_guard_g2 import (
    existing_booking,
    latest,
    send,
)
from tests.visit_booking_guard.helpers import Harness

pytestmark = pytest.mark.usefixtures("approved_duplicate")


async def test_can_book_when_new_request_ends_at_reserved_start(harness: Harness) -> None:
    await existing_booking(harness)
    await send(harness, "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 12:00")
    assert (await latest(harness)).pending_action == "CONFIRM_BOOKING"


async def test_manual_request_rechecks_confirmed_customer(
    harness: Harness, api: AsyncClient
) -> None:
    from app.customer.models import Customer
    from tests.integration.helpers import login_headers

    reserved = await existing_booking(harness)
    (customer,) = await harness.rows(Customer)
    headers = await login_headers(api, "90000000")
    response = await api.post(
        "/admin/reservations",
        headers=headers,
        json={
            "phone": customer.phone_number,
            "starts_at": reserved.starts_at.isoformat(),
            "plan_id": str(reserved.plan_id),
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["blockers"] == [
        {"kind": "RESERVED_CONFLICT", "ref": str(reserved.reservation_id)}
    ]


async def test_manual_availability_checks_entire_reserved_plan_interval(
    harness: Harness,
    api: AsyncClient,
) -> None:
    from tests.integration.helpers import login_headers

    reserved = await existing_booking(harness, other_customer=True)
    headers = await login_headers(api, "90000000")
    for minutes, expected in [
        (-180, True),
        (-179, False),
        (0, False),
        (30, False),
        (179, False),
        (180, True),
    ]:
        starts = (reserved.starts_at + timedelta(minutes=minutes)).isoformat()
        params = {"plan_id": str(reserved.plan_id), "starts_at": starts}
        response = await api.get("/admin/reservations/availability", headers=headers, params=params)
        assert response.status_code == 200
        assert response.json()["available"] is expected, (minutes, response.json())
        assert response.json()["blockers"] == (
            [] if expected else [{"kind": "RESERVED_CONFLICT", "ref": str(reserved.reservation_id)}]
        )
    response = await api.post(
        "/admin/reservations",
        headers=headers,
        json={
            "plan_id": str(reserved.plan_id),
            "starts_at": reserved.starts_at.isoformat(),
            "phone": "+573000001777",
        },
    )
    assert response.status_code == 409
