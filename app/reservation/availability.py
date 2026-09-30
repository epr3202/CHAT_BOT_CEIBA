"""D3 booking reads. Pending requests and evidence never hold a time slot."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from unicodedata import combining, normalize
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.calendar.adapter import CalendarAdapter, CalendarEvent, CalendarUnavailableError
from app.config.settings import Settings
from app.plan.models import Plan
from app.reservation.models import Reservation

BOGOTA = ZoneInfo("America/Bogota")


@dataclass(frozen=True)
class BookingBlocker:
    kind: Literal["CALENDAR_EXCLUSIVE", "RESERVED_EXCLUSIVE", "RESERVED_CONFLICT"]
    ref: str


@dataclass(frozen=True)
class BookingAvailability:
    available: bool
    blockers: list[BookingBlocker]


@dataclass(frozen=True)
class BookingWindow:
    ok: bool
    reason: Literal[
        "TIMEZONE_REQUIRED", "INVALID_RANGE", "CROSSES_MIDNIGHT", "OUTSIDE_HOURS", "MIN_LEAD_DAYS"
    ] | None = None


def _normalized(value: str) -> str:
    return "".join(char for char in normalize("NFKD", value.casefold())
                   if not combining(char)).strip()


def evaluate_booking_availability(
    *, plan: Plan, starts_at: datetime, ends_at: datetime,
    calendar_events: list[CalendarEvent], reservations: list[Reservation],
    exclusivity_keyword: str,
) -> BookingAvailability:
    """Pure D3 intersection with exclusive ends; reservation.plan must be loaded."""
    keyword = _normalized(exclusivity_keyword)
    if not keyword:
        raise ValueError("The booking exclusivity keyword must not be empty")
    blockers = [
        BookingBlocker("CALENDAR_EXCLUSIVE", event.event_id)
        for event in calendar_events
        if event.start < ends_at and starts_at < event.end
        and keyword in _normalized(f"{event.summary} {event.description or ''}")
    ]
    for reservation in reservations:
        if (reservation.status != "RESERVED" or reservation.starts_at >= ends_at
                or starts_at >= reservation.ends_at):
            continue
        if reservation.plan.exclusive:
            blockers.append(BookingBlocker("RESERVED_EXCLUSIVE", str(reservation.reservation_id)))
        elif plan.exclusive:
            blockers.append(BookingBlocker("RESERVED_CONFLICT", str(reservation.reservation_id)))
    return BookingAvailability(not blockers, blockers)


def validate_booking_window(
    starts_at: datetime, ends_at: datetime, settings: Settings, *, today: date | None = None,
) -> BookingWindow:
    """Calendar-day lead time in Bogotá, with an injectable date for deterministic callers."""
    if starts_at.utcoffset() is None or ends_at.utcoffset() is None:
        return BookingWindow(False, "TIMEZONE_REQUIRED")
    if ends_at <= starts_at:
        return BookingWindow(False, "INVALID_RANGE")
    start, end = starts_at.astimezone(BOGOTA), ends_at.astimezone(BOGOTA)
    if start.date() != end.date():
        return BookingWindow(False, "CROSSES_MIDNIGHT")
    if (start.time() < time.fromisoformat(settings.booking_hours_start)
            or end.time() > time.fromisoformat(settings.booking_hours_end)):
        return BookingWindow(False, "OUTSIDE_HOURS")
    today = today if today is not None else datetime.now(BOGOTA).date()
    if start.date() < today + timedelta(days=settings.booking_min_lead_days):
        return BookingWindow(False, "MIN_LEAD_DAYS")
    return BookingWindow(True)


async def fetch_booking_context(
    session: AsyncSession, *, plan: Plan, starts_at: datetime, ends_at: datetime,
    calendar: CalendarAdapter, settings: Settings,
) -> BookingAvailability:
    """Own a short read transaction, release it, then read Calendar.

    The caller supplies an idle, dedicated session and a loaded/detached plan.
    Never commit or roll back a caller's transaction. B1b-2 must defer this read
    through inbox_effects (DeferredAgendaCall/AgendaResults): after the inbox
    transaction exits, load the plan in a separate session, detach it and call
    here with an idle session. Replay only the resulting value, not ORM objects.
    This snapshot is advisory; B2 must revalidate before accepting payment.
    """
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise ValueError("Booking context requires an idle session without pending writes")
    ids = [value.strip() for value in settings.google_freebusy_calendar_ids.split(",")
           if value.strip()]
    if not ids:
        raise CalendarUnavailableError("No calendars configured for booking availability")
    async with session.begin():
        reservations = list(await session.scalars(
            select(Reservation).options(joinedload(Reservation.plan)).where(
                Reservation.status == "RESERVED", Reservation.starts_at < ends_at,
                Reservation.ends_at > starts_at,
            ).order_by(Reservation.starts_at, Reservation.reservation_id)
        ))
        # Freeze the read objects before commit, including expire_on_commit=True sessions.
        # A detached graph ensures the pure evaluator cannot perform any lazy SQL.
        for reservation in reservations:
            if reservation.plan in session:
                session.expunge(reservation.plan)
            session.expunge(reservation)
        if plan in session:
            session.expunge(plan)
    events = await calendar.list_events(starts_at, ends_at, ids)
    return evaluate_booking_availability(
        plan=plan, starts_at=starts_at, ends_at=ends_at, calendar_events=events,
        reservations=reservations, exclusivity_keyword=settings.booking_exclusivity_keyword,
    )
