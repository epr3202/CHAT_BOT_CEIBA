from datetime import timedelta

import httpx
import pytest
import respx

from app.calendar.adapter import CalendarUnavailableError
from tests.booking_backend.helpers import START
from tests.booking_backend.test_calendar import payload
from tests.test_slice2b2_gcal_adapter_adversarial import BASE_URL, adapter

URL = f"{BASE_URL}/calendars/a/events"


@respx.mock
async def test_g3_all_day_events_and_cancelled_instances() -> None:
    respx.get(URL).respond(200, json={"timeZone": "America/Bogota", "items": [
        {"id": "day", "summary": "Exclusividad", "start": {"date": "2030-10-10"},
         "end": {"date": "2030-10-11"}}, {"id": "deleted", "status": "cancelled"},
    ]})
    events = await adapter().list_events(START, START + timedelta(hours=3), ["a"])
    assert len(events) == 1
    assert events[0].start == START.replace(hour=0)
    assert events[0].end == START.replace(hour=0) + timedelta(days=1)


@pytest.mark.parametrize("item", [None, {}, {"id": "bad", "start": {"dateTime": 3}},
                                  {**payload("bad"), "end": {"date": "nonsense"}}])
@respx.mock
async def test_g3_malformed_events_fail_closed(item: object) -> None:
    respx.get(URL).respond(200, json={"items": [item]})
    with pytest.raises(CalendarUnavailableError):
        await adapter().list_events(START, START + timedelta(hours=3), ["a"])


@respx.mock
async def test_g3_repeated_page_token_fails_closed() -> None:
    route = respx.get(URL).respond(200, json={"items": [], "nextPageToken": "loop"})
    with pytest.raises(CalendarUnavailableError):
        await adapter().list_events(START, START + timedelta(hours=3), ["a"])
    assert route.call_count == 2


@respx.mock
async def test_g3_listing_transport_error_is_calendar_unavailable() -> None:
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(CalendarUnavailableError):
        await adapter().list_events(START, START + timedelta(hours=3), ["a"])
