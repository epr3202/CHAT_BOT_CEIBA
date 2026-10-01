from httpx import AsyncClient

from tests.booking_backend.helpers import START
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_plan


async def test_g3_agent_reads_only_active_plans_and_availability(client: AsyncClient):
    active = await seed_plan()
    inactive = await seed_plan(code="INACTIVE", active=False)
    headers = await login_headers(client, "80000000")
    plans = await client.get("/admin/plans", headers=headers)
    assert plans.status_code == 200
    assert [row["plan_id"] for row in plans.json()] == [str(active.plan_id)]
    availability = await client.get(
        "/admin/reservations/availability",
        headers=headers,
        params={
            "plan_id": str(active.plan_id),
            "starts_at": START.isoformat(),
        },
    )
    assert availability.status_code == 200
    for url in ["/admin/reservations", "/admin/payment-evidence"]:
        assert (await client.get(url, headers=headers)).status_code == 403
    assert (
        await client.patch(
            f"/admin/plans/{active.plan_id}", headers=headers, json={"name": "Cambio"}
        )
    ).status_code == 403
    admin = await client.get("/admin/plans", headers=await login_headers(client, "90000000"))
    assert {row["plan_id"] for row in admin.json()} == {str(active.plan_id), str(inactive.plan_id)}
