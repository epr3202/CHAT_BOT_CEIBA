from __future__ import annotations

import inspect
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.calendar.adapter import (
    AlreadyExistsError,
    CalendarUnavailableError,
    EventNotFoundError,
    ExternalEventRef,
    FakeCalendarAdapter,
    get_calendar_adapter,
)
from app.calendar.google_adapter import GoogleCalendarAdapter
from app.config.settings import get_settings

BOGOTA = ZoneInfo("America/Bogota")
BASE_URL = "https://www.googleapis.com/calendar/v3"
CALENDAR_ID = "visitas"
WRITE_EVENTS_URL = f"{BASE_URL}/calendars/{CALENDAR_ID}/events"
EVENT_ID = "0abcde12345"
EVENT_URL = f"{WRITE_EVENTS_URL}/{EVENT_ID}"


def dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BOGOTA)


def event_payload(
    *,
    event_id: str = EVENT_ID,
    summary: str = "Visita comercial",
    start: datetime | None = None,
    end: datetime | None = None,
    status: str = "confirmed",
) -> dict[str, object]:
    return {
        "id": event_id,
        "summary": summary,
        "status": status,
        "start": {
            "dateTime": (start or dt(2026, 8, 18, 9)).isoformat(),
            "timeZone": "America/Bogota",
        },
        "end": {
            "dateTime": (end or dt(2026, 8, 18, 9, 45)).isoformat(),
            "timeZone": "America/Bogota",
        },
    }


def adapter(token_calls: list[str] | None = None) -> GoogleCalendarAdapter:
    calls = token_calls if token_calls is not None else []

    async def token_provider() -> str:
        calls.append("called")
        return "test-token"

    return GoogleCalendarAdapter(
        calendar_id=CALENDAR_ID,
        service_account_file="/tmp/nonexistent-service-account.json",
        token_provider=token_provider,
    )


def request_json(route: respx.Route) -> dict[str, object]:
    return json.loads(route.calls.last.request.content)


@pytest.mark.parametrize("operation", ["create", "update"])
@respx.mock
async def test_tc_gcal_description_is_sent_on_create_and_update(operation: str) -> None:
    method = getattr(adapter(), f"{operation}_event")
    assert "description" in inspect.signature(method).parameters
    url = WRITE_EVENTS_URL if operation == "create" else EVENT_URL
    route = (respx.post(url) if operation == "create" else respx.patch(url)).mock(
        return_value=httpx.Response(200, json=event_payload())
    )

    await method(
        EVENT_ID,
        "Visita",
        dt(2026, 8, 18, 9),
        dt(2026, 8, 18, 9, 45),
        description="Nombre del cliente: Natalia Pérez",
    )

    assert request_json(route)["description"] == "Nombre del cliente: Natalia Pérez"


@respx.mock
async def test_tc_gcal_001_freebusy_happy_path_returns_all_calendars_aware_intervals() -> None:
    route = respx.post(f"{BASE_URL}/freeBusy").mock(
        return_value=httpx.Response(
            200,
            json={
                "calendars": {
                    "write": {
                        "busy": [
                            {
                                "start": "2026-08-18T09:00:00-05:00",
                                "end": "2026-08-18T09:30:00-05:00",
                            }
                        ]
                    },
                    "main": {
                        "busy": [
                            {
                                "start": "2026-08-18T10:00:00-05:00",
                                "end": "2026-08-18T10:30:00-05:00",
                            }
                        ]
                    },
                }
            },
        )
    )

    intervals = await adapter().get_busy_intervals(date(2026, 8, 18), ["write", "main"])

    assert route.called
    assert len(intervals) == 2
    assert intervals[0].start == dt(2026, 8, 18, 9)
    assert intervals[1].start == dt(2026, 8, 18, 10)
    assert all(interval.start.tzinfo is not None for interval in intervals)


@respx.mock
async def test_tc_gcal_002_freebusy_calendar_errors_are_loud_with_calendar_id() -> None:
    respx.post(f"{BASE_URL}/freeBusy").mock(
        return_value=httpx.Response(
            200,
            json={
                "calendars": {
                    "write": {"busy": []},
                    "main": {"errors": [{"domain": "global", "reason": "notFound"}], "busy": []},
                }
            },
        )
    )

    with pytest.raises(CalendarUnavailableError, match="main"):
        await adapter().get_busy_intervals(date(2026, 8, 18), ["write", "main"])


@respx.mock
async def test_tc_gcal_003_freebusy_missing_requested_calendar_is_loud() -> None:
    respx.post(f"{BASE_URL}/freeBusy").mock(
        return_value=httpx.Response(200, json={"calendars": {"write": {"busy": []}}})
    )

    with pytest.raises(CalendarUnavailableError, match="main"):
        await adapter().get_busy_intervals(date(2026, 8, 18), ["write", "main"])


@respx.mock
async def test_tc_gcal_004_freebusy_request_uses_bogota_day_window_and_requested_ids() -> None:
    route = respx.post(f"{BASE_URL}/freeBusy").mock(
        return_value=httpx.Response(
            200,
            json={"calendars": {"write": {"busy": []}, "main": {"busy": []}}},
        )
    )

    await adapter().get_busy_intervals(date(2026, 8, 18), ["write", "main"])

    payload = request_json(route)
    assert payload["timeMin"] == "2026-08-18T00:00:00-05:00"
    assert payload["timeMax"] == "2026-08-18T23:59:59-05:00"
    assert payload["timeZone"] == "America/Bogota"
    assert payload["items"] == [{"id": "write"}, {"id": "main"}]


@pytest.mark.parametrize("status_code", [500, 429])
@respx.mock
async def test_tc_gcal_005_freebusy_5xx_and_429_are_unavailable(status_code: int) -> None:
    respx.post(f"{BASE_URL}/freeBusy").mock(return_value=httpx.Response(status_code))

    with pytest.raises(CalendarUnavailableError):
        await adapter().get_busy_intervals(date(2026, 8, 18), ["write"])


@respx.mock
async def test_tc_gcal_005b_freebusy_403_mentions_credentials_or_permissions() -> None:
    respx.post(f"{BASE_URL}/freeBusy").mock(return_value=httpx.Response(403))

    with pytest.raises(
        CalendarUnavailableError,
        match="credential|permission|credencial|permiso",
    ):
        await adapter().get_busy_intervals(date(2026, 8, 18), ["write"])


@respx.mock
async def test_tc_gcal_006_freebusy_timeout_is_unavailable() -> None:
    route = respx.post(f"{BASE_URL}/freeBusy").mock(
        side_effect=httpx.TimeoutException("timed out")
    )

    with pytest.raises(CalendarUnavailableError):
        await adapter().get_busy_intervals(date(2026, 8, 18), ["write"])
    assert route.call_count == 1


@respx.mock
async def test_tc_gcal_007_create_success_returns_ref_and_sends_id_and_timezone() -> None:
    route = respx.post(WRITE_EVENTS_URL).mock(
        return_value=httpx.Response(
            200,
            json=event_payload(
                event_id=EVENT_ID,
                summary="Visita",
                start=dt(2026, 8, 18, 9),
                end=dt(2026, 8, 18, 9, 45),
            ),
        )
    )

    event = await adapter().create_event(
        EVENT_ID,
        "Visita",
        dt(2026, 8, 18, 9),
        dt(2026, 8, 18, 9, 45),
    )

    payload = request_json(route)
    assert event == ExternalEventRef(
        event_id=EVENT_ID,
        summary="Visita",
        start=dt(2026, 8, 18, 9),
        end=dt(2026, 8, 18, 9, 45),
    )
    assert payload["id"] == EVENT_ID
    assert payload["start"]["timeZone"] == "America/Bogota"
    assert payload["end"]["timeZone"] == "America/Bogota"


@pytest.mark.parametrize("status_code", [409, 410])
@respx.mock
async def test_tc_gcal_008_009_create_409_and_410_are_already_exists(
    status_code: int,
) -> None:
    respx.post(WRITE_EVENTS_URL).mock(return_value=httpx.Response(status_code))

    with pytest.raises(AlreadyExistsError):
        await adapter().create_event(
            EVENT_ID,
            "Visita",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )


@respx.mock
async def test_tc_gcal_010_create_timeout_is_unavailable_without_retry() -> None:
    route = respx.post(WRITE_EVENTS_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(CalendarUnavailableError):
        await adapter().create_event(
            EVENT_ID,
            "Visita",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )
    assert route.call_count == 1


@pytest.mark.parametrize("invalid_event_id", ["0abcde-12345", "0ABCDE12345"])
@respx.mock
async def test_tc_gcal_011_create_invalid_event_id_fails_before_http(
    invalid_event_id: str,
) -> None:
    route = respx.post(WRITE_EVENTS_URL).mock(return_value=httpx.Response(200))

    with pytest.raises(ValueError):
        await adapter().create_event(
            invalid_event_id,
            "Visita",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )
    assert route.call_count == 0


@pytest.mark.parametrize("status_code", [404, 410])
@respx.mock
async def test_tc_gcal_012_delete_404_and_410_are_not_found(status_code: int) -> None:
    respx.delete(EVENT_URL).mock(return_value=httpx.Response(status_code))

    with pytest.raises(EventNotFoundError):
        await adapter().delete_event(EVENT_ID)


@respx.mock
async def test_tc_gcal_013_get_404_is_not_found() -> None:
    respx.get(EVENT_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(EventNotFoundError):
        await adapter().get_event(EVENT_ID)


@respx.mock
async def test_tc_gcal_014_get_cancelled_status_is_not_found() -> None:
    respx.get(EVENT_URL).mock(
        return_value=httpx.Response(200, json=event_payload(status="cancelled"))
    )

    with pytest.raises(EventNotFoundError):
        await adapter().get_event(EVENT_ID)


@respx.mock
async def test_tc_gcal_015_get_success_returns_external_event_ref() -> None:
    respx.get(EVENT_URL).mock(
        return_value=httpx.Response(
            200,
            json=event_payload(
                event_id=EVENT_ID,
                summary="Visita",
                start=dt(2026, 8, 18, 9),
                end=dt(2026, 8, 18, 9, 45),
            ),
        )
    )

    event = await adapter().get_event(EVENT_ID)

    assert event == ExternalEventRef(
        event_id=EVENT_ID,
        summary="Visita",
        start=dt(2026, 8, 18, 9),
        end=dt(2026, 8, 18, 9, 45),
    )


def test_tc_gcal_016_factory_google_with_complete_settings_returns_google_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_base_env(monkeypatch)
    monkeypatch.setenv("CALENDAR_ADAPTER", "google")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "visitas")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/tmp/service-account.json")
    get_settings.cache_clear()

    created = get_calendar_adapter(get_settings())

    assert isinstance(created, GoogleCalendarAdapter)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("missing_var", "expected_message"),
    [
        ("GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SERVICE_ACCOUNT_FILE"),
        ("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_ID"),
    ],
)
def test_tc_gcal_017_factory_google_missing_required_setting_names_variable(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
    expected_message: str,
) -> None:
    configure_base_env(monkeypatch)
    monkeypatch.setenv("CALENDAR_ADAPTER", "google")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "visitas")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/tmp/service-account.json")
    monkeypatch.setenv(missing_var, "")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match=expected_message):
        get_calendar_adapter(get_settings())
    get_settings.cache_clear()


def test_tc_gcal_018_factory_fake_still_returns_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_base_env(monkeypatch)
    monkeypatch.setenv("CALENDAR_ADAPTER", "fake")
    get_settings.cache_clear()

    created = get_calendar_adapter(get_settings())

    assert isinstance(created, FakeCalendarAdapter)
    get_settings.cache_clear()


@respx.mock
async def test_tc_gcal_019_token_provider_token_is_sent_as_bearer_header() -> None:
    token_calls: list[str] = []
    route = respx.get(EVENT_URL).mock(return_value=httpx.Response(200, json=event_payload()))

    await adapter(token_calls).get_event(EVENT_ID)

    assert token_calls == ["called"]
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
async def test_tc_gcal_020_patch_success_returns_ref_and_uses_timezone() -> None:
    route = respx.patch(EVENT_URL).mock(
        return_value=httpx.Response(
            200,
            json=event_payload(
                event_id=EVENT_ID,
                summary="Visita movida",
                start=dt(2026, 8, 19, 10),
                end=dt(2026, 8, 19, 10, 45),
            ),
        )
    )

    event = await adapter().update_event(
        EVENT_ID,
        "Visita movida",
        dt(2026, 8, 19, 10),
        dt(2026, 8, 19, 10, 45),
    )

    payload = request_json(route)
    assert route.calls.last.request.method == "PATCH"
    assert event.summary == "Visita movida"
    assert event.start == dt(2026, 8, 19, 10)
    assert payload["summary"] == "Visita movida"
    assert payload["start"]["timeZone"] == "America/Bogota"
    assert payload["end"]["timeZone"] == "America/Bogota"


@pytest.mark.parametrize("status_code", [404, 410])
@respx.mock
async def test_tc_gcal_021_patch_404_and_410_are_not_found(status_code: int) -> None:
    respx.patch(EVENT_URL).mock(return_value=httpx.Response(status_code))

    with pytest.raises(EventNotFoundError):
        await adapter().update_event(
            EVENT_ID,
            "Visita movida",
            dt(2026, 8, 19, 10),
            dt(2026, 8, 19, 10, 45),
        )


@respx.mock
async def test_tc_gcal_022_patch_timeout_is_unavailable_without_retry() -> None:
    route = respx.patch(EVENT_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(CalendarUnavailableError):
        await adapter().update_event(
            EVENT_ID,
            "Visita movida",
            dt(2026, 8, 19, 10),
            dt(2026, 8, 19, 10, 45),
        )
    assert route.call_count == 1


def configure_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba")
    monkeypatch.setenv("META_APP_SECRET", "test")
    monkeypatch.setenv("META_ACCESS_TOKEN", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
