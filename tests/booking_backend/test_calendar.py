from datetime import timedelta

import httpx
import pytest
import respx

from app.calendar.adapter import CalendarUnavailableError, FakeCalendarAdapter
from tests.booking_backend.helpers import START, symbol
from tests.test_slice2b2_gcal_adapter_adversarial import BASE_URL, adapter


async def test_r3_fake_range_calendars_order() -> None:
    fake = FakeCalendarAdapter()
    assert callable(getattr(fake, "add_event", None)), "B1b-1: falta add_event"
    late = fake.add_event("b", "Tarde", START + timedelta(hours=1), START + timedelta(hours=2))
    early = fake.add_event("a", "Temprano", START, START + timedelta(hours=1), "detalle")
    fake.add_event("c", "Otro calendario", START, START + timedelta(hours=1))
    fake.add_event("a", "Borde", START - timedelta(hours=1), START)
    result = await fake.list_events(START, START + timedelta(hours=3), iter(["a", "b"]))
    assert result == [early, late]
    assert early.description == "detalle"
    assert isinstance(early, symbol("app.calendar.adapter", "CalendarEvent"))


def payload(event_id: str, hour: int = 0) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": "exclusividad",
        "description": "detalle",
        "start": {"dateTime": (START + timedelta(hours=hour)).isoformat()},
        "end": {"dateTime": (START + timedelta(hours=hour + 1)).isoformat()},
    }


@respx.mock
async def test_r3_google_pagination_each_calendar_and_query() -> None:
    google = adapter()
    assert callable(getattr(google, "list_events", None)), "B1b-1: falta list_events"
    route = respx.get(f"{BASE_URL}/calendars/a/events").mock(
        side_effect=[
            httpx.Response(200, json={"items": [payload("one")], "nextPageToken": "next"}),
            httpx.Response(200, json={"items": [payload("two", 1)]}),
        ]
    )
    respx.get(f"{BASE_URL}/calendars/b/events").respond(200, json={"items": [payload("three")]})
    end = START + timedelta(hours=3)
    events = await google.list_events(START, end, iter(["a", "b"]))
    assert {(e.event_id, e.calendar_id) for e in events} == {
        ("one", "a"),
        ("two", "a"),
        ("three", "b"),
    }
    assert all(e.summary == "exclusividad" and e.description == "detalle" for e in events)
    assert [e.start for e in events] == sorted(e.start for e in events)
    for call in respx.calls:
        params = call.request.url.params
        assert params["timeMin"] == START.isoformat() and params["timeMax"] == end.isoformat()
        assert params["singleEvents"] == "true" and params["orderBy"] == "startTime"
    assert route.calls[1].request.url.params["pageToken"] == "next"


@pytest.mark.parametrize(
    "status,body", [(403, {}), (404, {}), (500, {}), (200, {"error": "denied"}), (200, {})]
)
@respx.mock
async def test_r3_google_error_or_missing_calendar_is_loud(status: int, body: dict) -> None:
    google = adapter()
    assert callable(getattr(google, "list_events", None)), "B1b-1: falta list_events"
    respx.get(f"{BASE_URL}/calendars/a/events").respond(200, json={"items": []})
    respx.get(f"{BASE_URL}/calendars/missing/events").respond(status, json=body)
    with pytest.raises(CalendarUnavailableError):
        await google.list_events(START, START + timedelta(hours=3), ["a", "missing"])
