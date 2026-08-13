from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


@dataclass(frozen=True)
class EventDateTriplet:
    event_date: date | None
    event_month: str | None
    event_date_type: str
    event_date_raw: str

    @property
    def date_resolved(self) -> bool:
        return (
            self.event_date is not None
            or self.event_month is not None
            or self.event_date_type in {"FLEXIBLE", "UNKNOWN"}
        )


def validate_event_date_triplet(
    event_date: date | None,
    event_month: str | None,
    event_date_type: str,
    event_date_raw: str,
) -> EventDateTriplet:
    if not event_date_raw.strip():
        raise ValueError("MISSING_EVENT_DATE_RAW")
    if event_date_type == "EXACT" and event_date is None:
        raise ValueError("INVALID_DATE_TRIPLET")
    if event_date is not None and event_date_type != "EXACT":
        raise ValueError("INVALID_DATE_TRIPLET")
    if event_date_type == "APPROXIMATE" and (event_date is not None or event_month is None):
        raise ValueError("INVALID_DATE_TRIPLET")
    if event_date_type == "FLEXIBLE" and event_date is not None:
        raise ValueError("INVALID_DATE_TRIPLET")
    if event_date_type == "UNKNOWN" and (event_date is not None or event_month is not None):
        raise ValueError("INVALID_DATE_TRIPLET")
    if event_month is not None and not re.fullmatch(r"\d{4}-\d{2}", event_month):
        raise ValueError("INVALID_DATE")
    return EventDateTriplet(event_date, event_month, event_date_type, event_date_raw)


def validate_event_date_not_past(value: date, today: date) -> None:
    if value < today:
        raise ValueError("PAST_DATE")


def parse_customer_date_expression(raw_value: str, today: date) -> EventDateTriplet:
    normalized = raw_value.strip().casefold()
    if not normalized:
        raise ValueError("INVALID_DATE")
    if "todavía no" in normalized or "todavia no" in normalized or "no sé" in normalized:
        return validate_event_date_triplet(None, None, "UNKNOWN", raw_value)

    month = next((month for name, month in MONTHS.items() if name in normalized), None)
    explicit_year_match = re.search(r"\b(20\d{2})\b", normalized)
    day_match = re.search(r"\b(\d{1,2})\b", normalized)
    if month is None and (weekday := _weekday_in(normalized)):
        days_ahead = (weekday - today.weekday()) % 7
        if days_ahead == 0 or "proximo" in _strip_accents(normalized):
            days_ahead = 7 if days_ahead == 0 else days_ahead
        parsed = today + timedelta(days=days_ahead)
        return validate_event_date_triplet(parsed, None, "EXACT", raw_value)
    if month is None and day_match:
        day = int(day_match.group(1))
        parsed = _next_future_date_for_day(day, today)
        return validate_event_date_triplet(parsed, None, "EXACT", raw_value)
    if month is None:
        raise ValueError("INVALID_DATE")
    year = int(explicit_year_match.group(1)) if explicit_year_match else _infer_year(month, today)
    if day_match:
        day = int(day_match.group(1))
        try:
            parsed = date(year, month, day)
        except ValueError as error:
            raise ValueError("INVALID_CALENDAR_DATE") from error
        if not explicit_year_match and parsed < today:
            parsed = date(year + 1, month, day)
        validate_event_date_not_past(parsed, today)
        return validate_event_date_triplet(parsed, None, "EXACT", raw_value)

    event_month = f"{year:04d}-{month:02d}"
    if explicit_year_match and event_month < f"{today.year:04d}-{today.month:02d}":
        raise ValueError("PAST_DATE")
    date_type = "FLEXIBLE" if "cualquier" in normalized else "APPROXIMATE"
    return validate_event_date_triplet(None, event_month, date_type, raw_value)


def _infer_year(month: int, today: date) -> int:
    if month < today.month:
        return today.year + 1
    return today.year


def _weekday_in(normalized: str) -> int | None:
    normalized_without_accents = _strip_accents(normalized)
    for name, weekday in WEEKDAYS.items():
        if _strip_accents(name) in normalized_without_accents:
            return weekday
    return None


def _next_future_date_for_day(day: int, today: date) -> date:
    month = today.month
    year = today.year
    while True:
        try:
            candidate = date(year, month, day)
        except ValueError:
            month += 1
            if month == 13:
                month = 1
                year += 1
            continue
        if candidate >= today:
            return candidate
        month += 1
        if month == 13:
            month = 1
            year += 1


def _strip_accents(value: str) -> str:
    import unicodedata

    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
