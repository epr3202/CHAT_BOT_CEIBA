from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import Request, Response
from google.oauth2.service_account import Credentials

from app.calendar.adapter import (
    AlreadyExistsError,
    BusyInterval,
    CalendarEvent,
    CalendarUnavailableError,
    EventNotFoundError,
    ExternalEventRef,
)

BOGOTA = ZoneInfo("America/Bogota")
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
GOOGLE_EVENT_ID_PATTERN = re.compile(r"^[0-9a-v]{5,1024}$")
TOKEN_REFRESH_MARGIN = timedelta(seconds=300)


class GoogleCalendarAdapter:
    def __init__(
        self,
        calendar_id: str,
        service_account_file: str,
        http_client: httpx.AsyncClient | None = None,
        token_provider: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self.calendar_id = calendar_id
        self.service_account_file = service_account_file
        self._http_client = http_client or httpx.AsyncClient(timeout=10.0)
        self._token_provider = token_provider or self._get_default_token
        self._credentials: Credentials | None = None

    async def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_ids: Iterable[str],
    ) -> list[CalendarEvent]:
        """Read each configured calendar completely; never return partial availability."""
        if start.utcoffset() is None or end.utcoffset() is None or start >= end:
            raise ValueError("Calendar event listing requires an aware, increasing interval")
        events: list[CalendarEvent] = []
        for calendar_id in dict.fromkeys(calendar_ids):
            params = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
            }
            seen_tokens: set[str] = set()
            while True:
                url = httpx.URL(
                    f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/"
                    f"{quote(calendar_id, safe='')}/events",
                    params=params,
                )
                response = await self._request("GET", str(url), operation="list")
                try:
                    data = response.json()
                    if (
                        not isinstance(data, dict)
                        or data.get("error")
                        or data.get("errors")
                        or not isinstance(data.get("items"), list)
                    ):
                        raise ValueError("Missing calendar event collection")
                    for item in data["items"]:
                        if not isinstance(item, dict):
                            raise ValueError("Malformed calendar event")
                        if item.get("status") == "cancelled":
                            continue
                        event = _listed_event(
                            item, calendar_id, data.get("timeZone", "America/Bogota")
                        )
                        if event.start < end and start < event.end:
                            events.append(event)
                    token = data.get("nextPageToken")
                    if token is None:
                        break
                    if not isinstance(token, str) or not token or token in seen_tokens:
                        raise ValueError("Invalid or repeated calendar page token")
                    seen_tokens.add(token)
                    params["pageToken"] = token
                except (ValueError, TypeError, KeyError) as exc:
                    raise CalendarUnavailableError(
                        f"Google Calendar events response malformed for calendar: {calendar_id}"
                    ) from exc
        return sorted(events, key=lambda event: (event.start, event.calendar_id, event.event_id))

    async def get_busy_intervals(
        self,
        target_date: date,
        calendar_ids: Iterable[str],
    ) -> list[BusyInterval]:
        requested_calendar_ids = list(calendar_ids)
        payload = {
            "timeMin": datetime.combine(target_date, time.min, tzinfo=BOGOTA).isoformat(),
            "timeMax": datetime.combine(target_date, time.max, tzinfo=BOGOTA)
            .replace(microsecond=0)
            .isoformat(),
            "timeZone": "America/Bogota",
            "items": [{"id": calendar_id} for calendar_id in requested_calendar_ids],
        }
        response = await self._request("POST", f"{GOOGLE_CALENDAR_API_BASE_URL}/freeBusy", payload)
        data = response.json()
        calendars = data.get("calendars", {})
        if not isinstance(calendars, dict):
            raise CalendarUnavailableError("Google Calendar freebusy response is malformed")

        intervals: list[BusyInterval] = []
        for calendar_id in requested_calendar_ids:
            calendar_data = calendars.get(calendar_id)
            if not isinstance(calendar_data, dict):
                raise CalendarUnavailableError(
                    f"Google Calendar freebusy response missing calendar: {calendar_id}"
                )
            if calendar_data.get("errors"):
                raise CalendarUnavailableError(
                    f"Google Calendar freebusy error for calendar: {calendar_id}"
                )
            busy_items = calendar_data.get("busy", [])
            if not isinstance(busy_items, list):
                raise CalendarUnavailableError(
                    f"Google Calendar freebusy response malformed for calendar: {calendar_id}"
                )
            intervals.extend(
                BusyInterval(
                    start=_parse_google_datetime(item["start"]),
                    end=_parse_google_datetime(item["end"]),
                )
                for item in busy_items
                if isinstance(item, dict) and "start" in item and "end" in item
            )
        return intervals

    async def create_event(
        self,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> ExternalEventRef:
        _validate_event_id(event_id)
        response = await self._request(
            "POST",
            self._events_url(),
            _event_write_payload(
                event_id=event_id,
                summary=summary,
                start=start,
                end=end,
                description=description,
            ),
            operation="create",
        )
        return _event_ref_from_response(response.json())

    async def update_event(
        self,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> ExternalEventRef:
        _validate_event_id(event_id)
        response = await self._request(
            "PATCH",
            self._event_url(event_id),
            _event_write_payload(
                summary=summary,
                start=start,
                end=end,
                description=description,
            ),
            operation="update",
        )
        return _event_ref_from_response(response.json())

    async def delete_event(self, event_id: str) -> None:
        _validate_event_id(event_id)
        await self._request("DELETE", self._event_url(event_id), operation="delete")

    async def get_event(self, event_id: str) -> ExternalEventRef:
        _validate_event_id(event_id)
        response = await self._request("GET", self._event_url(event_id), operation="get")
        data = response.json()
        if data.get("status") == "cancelled":
            raise EventNotFoundError(f"Google Calendar event is cancelled: {event_id}")
        return _event_ref_from_response(data)

    async def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        *,
        operation: str = "freebusy",
    ) -> httpx.Response:
        try:
            response = await self._http_client.request(
                method,
                url,
                json=payload,
                headers={"Authorization": f"Bearer {await self._token_provider()}"},
            )
        except httpx.TransportError as exc:
            raise CalendarUnavailableError("Google Calendar transport error") from exc
        _raise_for_calendar_status(response, operation=operation)
        return response

    async def _get_default_token(self) -> str:
        try:
            if self._credentials is None:
                self._credentials = await asyncio.to_thread(
                    Credentials.from_service_account_file,
                    self.service_account_file,
                    scopes=[CALENDAR_SCOPE],
                )
            if self._credentials.token is None or self._token_needs_refresh(self._credentials):
                await asyncio.to_thread(self._credentials.refresh, UrllibRequest())
        except Exception as exc:
            raise CalendarUnavailableError(
                "Google Calendar credentials are unavailable or unreadable"
            ) from exc

        if not self._credentials.token:
            raise CalendarUnavailableError("Google Calendar credentials did not produce a token")
        return self._credentials.token

    def _token_needs_refresh(self, credentials: Credentials) -> bool:
        if not credentials.valid:
            return True
        expiry = credentials.expiry
        if expiry is None:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry - datetime.now(UTC) < TOKEN_REFRESH_MARGIN

    def _events_url(self) -> str:
        return f"{GOOGLE_CALENDAR_API_BASE_URL}/calendars/{quote(self.calendar_id, safe='')}/events"

    def _event_url(self, event_id: str) -> str:
        return f"{self._events_url()}/{quote(event_id, safe='')}"


def _listed_event(data: dict[str, Any], calendar_id: str, timezone: str) -> CalendarEvent:
    """Keep all-day exclusivity visible, using the provider calendar's timezone."""

    def boundary(key: str) -> datetime:
        value = data[key]
        if not isinstance(value, dict):
            raise ValueError("Invalid calendar event boundary")
        if "dateTime" in value:
            if not isinstance(value["dateTime"], str):
                raise ValueError("Invalid calendar datetime")
            result = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            if result.utcoffset() is None:
                result = result.replace(tzinfo=ZoneInfo(value.get("timeZone", timezone)))
            return result
        return datetime.combine(
            date.fromisoformat(value["date"]), time.min, tzinfo=ZoneInfo(timezone)
        )

    event_id = data["id"]
    summary, description = data.get("summary", ""), data.get("description")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(summary, str)
        or (description is not None and not isinstance(description, str))
    ):
        raise ValueError("Invalid calendar event metadata")
    start, end = boundary("start"), boundary("end")
    if end <= start:
        raise ValueError("Invalid calendar event interval")
    return CalendarEvent(event_id, calendar_id, summary, description, start, end)


def _validate_event_id(event_id: str) -> None:
    if not GOOGLE_EVENT_ID_PATTERN.fullmatch(event_id):
        raise ValueError("Google Calendar event_id must match ^[0-9a-v]{5,1024}$")


def _event_write_payload(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    event_id: str | None = None,
    description: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "summary": summary,
        "start": {
            "dateTime": _as_bogota(start).isoformat(),
            "timeZone": "America/Bogota",
        },
        "end": {
            "dateTime": _as_bogota(end).isoformat(),
            "timeZone": "America/Bogota",
        },
    }
    if event_id is not None:
        payload["id"] = event_id
    if description is not None:
        payload["description"] = description
    return payload


def _event_ref_from_response(data: dict[str, Any]) -> ExternalEventRef:
    return ExternalEventRef(
        event_id=str(data["id"]),
        summary=str(data.get("summary", "")),
        start=_parse_google_datetime(_event_datetime(data, "start")),
        end=_parse_google_datetime(_event_datetime(data, "end")),
        description=str(data["description"]) if data.get("description") is not None else None,
    )


def _event_datetime(data: dict[str, Any], key: str) -> str:
    container = data.get(key, {})
    if not isinstance(container, dict):
        raise CalendarUnavailableError(f"Google Calendar event response missing {key}")
    value = container.get("dateTime")
    if not isinstance(value, str):
        raise CalendarUnavailableError(f"Google Calendar event response missing {key}.dateTime")
    return value


def _parse_google_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BOGOTA)
    return parsed.astimezone(BOGOTA)


def _as_bogota(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=BOGOTA)
    return value.astimezone(BOGOTA)


def _raise_for_calendar_status(response: httpx.Response, *, operation: str) -> None:
    status_code = response.status_code
    if status_code < 400:
        return

    if status_code in {401, 403}:
        raise CalendarUnavailableError("Google Calendar credential/permission error")
    if status_code == 429 or status_code >= 500:
        raise CalendarUnavailableError(f"Google Calendar unavailable: HTTP {status_code}")
    if operation == "create" and status_code in {409, 410}:
        raise AlreadyExistsError("Google Calendar event already exists or id is burned")
    if operation in {"delete", "get", "update"} and status_code in {404, 410}:
        raise EventNotFoundError("Google Calendar event not found")

    raise CalendarUnavailableError(f"Google Calendar request failed: HTTP {status_code}")


class UrllibResponse(Response):
    def __init__(self, status: int, headers: dict[str, str], data: bytes) -> None:
        self._status = status
        self._headers = headers
        self._data = data

    @property
    def status(self) -> int:
        return self._status

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @property
    def data(self) -> bytes:
        return self._data


class UrllibRequest(Request):
    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> Response:
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or 10) as response:
                return UrllibResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    data=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return UrllibResponse(
                status=exc.code,
                headers=dict(exc.headers.items()),
                data=exc.read(),
            )
        except OSError as exc:
            raise google_auth_exceptions.TransportError(str(exc)) from exc
