from datetime import date

import httpx
import respx

from app.scheduling.availability import AvailabilityService
from tests.integration.helpers import reset_test_database
from tests.test_slice2b2_gcal_adapter_adversarial import BASE_URL, adapter


async def test_incomplete_busy_interval_does_not_offer_a_visit() -> None:
    store = await reset_test_database()
    service = AvailabilityService(
        sessionmaker=store, calendar_adapter=adapter(), freebusy_calendar_ids=["visitas"]
    )
    with respx.mock() as router:
        router.post(BASE_URL + "/freeBusy").mock(
            return_value=httpx.Response(
                200,
                json={"calendars": {"visitas": {"busy": [{"start": "2026-11-24T09:00:00-05:00"}]}}},
            )
        )
        result = await service.available_slots(date(2026, 11, 24), today=date(2026, 11, 20))
        hours = [s.start_time.isoformat(timespec="minutes") for s in result.slots]
        assert not hours, (hours, result.response_code)
        assert result.response_code == "RESP-CALENDAR-ERROR-001" and result.requires_review
