"""Pure semantic boundary for the nine conversational entity families."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, get_args

from pydantic import ValidationError

from app.ai.schemas import EntityName, ExtractedEntity, IntentClassification
from app.conversation.services_catalog import match_requested_services, service_catalog_codes
from app.event.event_type import normalize_event_type
from app.event.validation import (
    EventDateTriplet,
    parse_customer_date_expression,
    validate_event_date_triplet,
)
from app.lead.budget import _parse_spanish_number, parse_cop_amount

ENTITY_NAMES = frozenset(get_args(EntityName))
MAX_INTEGER = 2**31 - 1
MAX_BUDGET = Decimal("9999999999.99")
EntityValue = str | int | bool | Decimal | EventDateTriplet | tuple[int, int] | tuple[str, ...]


@dataclass(frozen=True)
class Rejection:
    entity: str
    code: str
    value_type: str
    correction: bool = False


@dataclass(frozen=True)
class Accepted:
    entity: ExtractedEntity
    value: EntityValue
    warnings: tuple[Rejection, ...] = ()

    def canonical(self) -> ExtractedEntity:
        value: Any = self.value
        if isinstance(value, EventDateTriplet):
            value = dict(event_date=value.event_date.isoformat() if value.event_date else None,
                         event_month=value.event_month, event_date_type=value.event_date_type,
                         event_date_raw=value.event_date_raw)
        elif self.entity.entity == "guest_count_range":
            value = dict(min=value[0], max=value[1])
        elif isinstance(value, tuple):
            value = list(value)
        elif isinstance(value, Decimal):
            value = str(value)
        return self.entity.model_copy(update={"normalized_value": value})


@dataclass(frozen=True)
class EntityBatch:
    accepted: tuple[Accepted, ...]
    rejected: tuple[Rejection, ...]


class InvalidEntity(ValueError):
    """Only deliberately raised boundary errors carry these static codes."""


def _fail(code: str) -> None:
    raise InvalidEntity(code)


def technical_type(value: object) -> str:
    # Do not use a user-controlled class name, repr or value in diagnostics.
    for kind in (type(None), bool, str, int, float, list, dict, Decimal):
        if type(value) is kind:
            return "null" if value is None else kind.__name__
    return "unsupported"


def rejection(entity: ExtractedEntity, code: str) -> Rejection:
    name = (
        entity.entity if isinstance(entity.entity, str) and entity.entity in ENTITY_NAMES
        else "UNKNOWN"
    )
    return Rejection(name, code, technical_type(entity.normalized_value),
                     entity.quality_status == "CORRECTED")


def text_value(value: object, *, name: bool = False) -> str:
    if not isinstance(value, str):
        _fail("INVALID_TEXT_TYPE")
    if "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _fail("UNREPRESENTABLE_TEXT")
    result = " ".join(value.split()) if name else value.strip()
    if not result:
        _fail("REQUIRED_VALUE_MISSING")
    if name and (not 2 <= len(result) <= 120 or not any(c.isalpha() for c in result)):
        _fail("INVALID_NAME")
    return result


def validated_name(value: object) -> str | None:
    try:
        return text_value(value, name=True)
    except InvalidEntity:
        return None


def integer_value(value: object) -> int:
    if type(value) is bool:
        _fail("INVALID_INTEGER_TYPE")
    if isinstance(value, str):
        if not re.fullmatch(r"[+]?\d+", value.strip(), flags=re.ASCII):
            _fail("INVALID_INTEGER_FORMAT")
        digits = value.strip().lstrip("+").lstrip("0") or "0"
        if len(digits) > 10:
            _fail("INTEGER_OVERFLOW")
        value = int(digits)
    elif type(value) is float:
        if not math.isfinite(value) or not value.is_integer():
            _fail("INVALID_INTEGER_FORMAT")
        if not 0 < value <= MAX_INTEGER:
            _fail("INTEGER_OUT_OF_RANGE")
        value = int(value)
    if type(value) is not int:
        _fail("INVALID_INTEGER_TYPE")
    if not 0 < value <= MAX_INTEGER:
        _fail("INTEGER_OUT_OF_RANGE")
    return value


def amount_value(value: object, raw: str) -> Decimal:
    if type(value) is bool or (
        value is not None and not isinstance(value, (str, int, float, Decimal))
    ):
        _fail("INVALID_BUDGET_TYPE")
    if type(value) is float and not math.isfinite(value):
        _fail("NONFINITE_BUDGET")
    source = value if value is not None else raw
    try:
        if value is not None and (
            not isinstance(source, str) or re.fullmatch(r"[+]?\d+(?:\.\d+)?", source.strip())
        ):
            amount = Decimal(str(source))
        else:
            text = text_value(source).casefold()
            if "-" in text or text.startswith("menos "):
                _fail("BUDGET_OUT_OF_RANGE")
            if any(currency in text for currency in ("usd", "eur", "dolar", "dólar", "euro")):
                _fail("UNSUPPORTED_CURRENCY")
            text = re.sub(r"\bpalos?\b", "millones", text)
            text = re.sub(r"\d{1,3}(?:\.\d{3}){2,}", lambda m: m[0].replace(".", ""), text)
            # The existing COP parser handles the approved colloquial forms.
            amount = parse_cop_amount(text)
            # Mirror only the parser's exact Decimal arithmetic, before its integer
            # quantization, so a supported phrase cannot silently lose cents.
            compact = text.replace("$", "").replace("cop", "").strip().replace(",", ".")
            millions = re.search(r"(\d+(?:\.\d+)?)\s*m\b", compact)
            if millions:
                amount = Decimal(millions[1]) * 1_000_000
            elif any(word in compact for word in ("millon", "millón", "millones")):
                before = re.split(r"millones?|millón", compact, maxsplit=1)[0].strip()
                exact = _parse_spanish_number(before)
                if "medio" in compact or "media" in compact:
                    exact += Decimal("0.5")
                amount = exact * 1_000_000
            else:
                digits = re.sub(r"[^\d.]", "", compact)
                if digits:
                    amount = Decimal(digits)
                    if amount < 1000 and "." in digits:
                        amount *= 1_000_000
    except (InvalidOperation, ValueError) as error:
        if isinstance(error, InvalidEntity):
            raise
        _fail("INVALID_BUDGET_FORMAT")
    if not amount.is_finite():
        _fail("NONFINITE_BUDGET")
    if not 0 < amount <= MAX_BUDGET:
        _fail("BUDGET_OUT_OF_RANGE")
    if amount != amount.quantize(Decimal("0.01")):
        _fail("BUDGET_PRECISION_LOSS")
    return amount


def date_value(value: object, raw: str, today: date) -> EventDateTriplet:
    if not raw and isinstance(value, dict):
        raw = value.get("event_date_raw", "")
    raw = text_value(raw)
    if len(raw) > 200:
        _fail("DATE_RAW_OVERFLOW")
    if value is not None and not isinstance(value, (str, dict)):
        _fail("INVALID_DATE_TYPE")
    try:
        if isinstance(value, dict):
            if set(value) - {"event_date", "event_month", "event_date_type", "event_date_raw"}:
                _fail("UNKNOWN_DATE_KEY")
            kind = value.get("event_date_type")
            if not isinstance(kind, str) or kind not in {
                "EXACT", "APPROXIMATE", "FLEXIBLE", "UNKNOWN"
            }:
                _fail("INVALID_DATE_DISCRIMINATOR")
            day, month = value.get("event_date"), value.get("event_month")
            if day is not None and not isinstance(day, str):
                _fail("INVALID_DATE_TYPE")
            if month is not None:
                if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
                    _fail("INVALID_MONTH")
                date.fromisoformat(month + "-01")
            if kind == "EXACT" and month is not None:
                _fail("INCOHERENT_DATE_TRIPLET")
            proposed_raw = value.get("event_date_raw", raw)
            text_value(proposed_raw)
            if len(proposed_raw) > 200:
                _fail("DATE_RAW_OVERFLOW")
            triplet = validate_event_date_triplet(
                date.fromisoformat(day) if day else None, month, kind, raw)
            if kind in {"UNKNOWN", "FLEXIBLE"} and month is None:
                return triplet
        elif isinstance(value, str) and value:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    _fail("INVALID_DATE")
                triplet = parse_date_raw(raw, today)
            else:
                triplet = validate_event_date_triplet(parsed, None, "EXACT", raw)
        else:
            triplet = parse_date_raw(raw, today)
        # Preserve the existing explicit reanchoring of customer dates without a year.
        if not re.search(r"\b\d{4}\b", raw):
            triplet = parse_date_raw(raw, today)
        if triplet.event_date is not None and triplet.event_date < today:
            _fail("DATE_IN_PAST")
        if triplet.event_month is not None and triplet.event_month < today.strftime("%Y-%m"):
            _fail("DATE_IN_PAST")
        return triplet
    except (ValueError, OverflowError) as error:
        if isinstance(error, InvalidEntity):
            raise
        _fail("INVALID_DATE")


def parse_date_raw(raw: str, today: date) -> EventDateTriplet:
    # The old day-only parser loops until it finds a valid month. Impossible days
    # must be rejected before calling it, without changing its legitimate reanchoring.
    day = re.search(r"\b(\d{1,2})\b", raw)
    if day and not 1 <= int(day[1]) <= 31:
        _fail("INVALID_DATE")
    return parse_customer_date_expression(raw, today)


def decode_entities(
    classification: IntentClassification,
) -> tuple[list[ExtractedEntity], list[Rejection]]:
    decoded: list[ExtractedEntity] = []
    rejected: list[Rejection] = []
    typed = classification.extracted_entities
    if not isinstance(typed, list):
        return [], [Rejection("UNKNOWN", "INVALID_ENVELOPE", technical_type(typed))]
    for item in typed:
        data = item.model_dump(warnings=False) if isinstance(item, ExtractedEntity) else item
        try:
            decoded.append(ExtractedEntity.model_validate(data, strict=True))
        except ValidationError:
            rejected.append(Rejection("UNKNOWN", "INVALID_ENVELOPE", technical_type(item)))
    legacy = classification.entities
    if not isinstance(legacy, dict):
        return decoded, [*rejected, Rejection("UNKNOWN", "INVALID_LEGACY", technical_type(legacy))]
    for name, value in legacy.items():
        if not isinstance(name, str) or name not in ENTITY_NAMES:
            rejected.append(Rejection("UNKNOWN", "UNKNOWN_LEGACY_ENTITY", technical_type(value)))
            continue
        if isinstance(value, dict) and any(
            key in value for key in (
                "raw_value", "raw", "normalized_value", "normalized", "quality_status"
            )
        ):
            data = dict(entity=name, raw_value=value.get("raw_value", value.get("raw", "")),
                        normalized_value=value.get("normalized_value", value.get("normalized")),
                        quality_status=value.get("quality_status", "PROVIDED"),
                        confidence=value.get("confidence", 0.9),
                        needs_confirmation=value.get("needs_confirmation", False),
                        validation_errors=value.get("validation_errors", []))
            if set(value) - {"raw_value", "raw", "normalized_value", "normalized", "quality_status",
                             "confidence", "needs_confirmation", "validation_errors"}:
                rejected.append(Rejection(name, "UNKNOWN_LEGACY_KEY", "dict"))
                continue
        else:
            data = dict(entity=name, raw_value=value if isinstance(value, str) else "",
                        normalized_value=value, quality_status="PROVIDED", confidence=0.9)
        try:
            decoded.append(ExtractedEntity.model_validate(data, strict=True))
        except ValidationError:
            rejected.append(Rejection(name, "INVALID_LEGACY_ENVELOPE", technical_type(value)))
    return decoded, rejected


def validate_entity(entity: ExtractedEntity, today: date) -> Accepted:
    try:
        entity = ExtractedEntity.model_validate(entity.model_dump(warnings=False), strict=True)
    except ValidationError:
        _fail("INVALID_ENTITY_ENVELOPE")
    if "\x00" in entity.raw_value or any(0xD800 <= ord(c) <= 0xDFFF for c in entity.raw_value):
        _fail("UNREPRESENTABLE_TEXT")
    warnings: list[Rejection] = []
    if entity.quality_status == "INVALID":
        _fail("SOURCE_INVALID")
    value = entity.normalized_value
    name = entity.entity
    if name == "full_name":
        result: EntityValue = text_value(
            value if value is not None else entity.raw_value, name=True
        )
    elif name == "event_type":
        result = normalize_event_type(text_value(value if value is not None else entity.raw_value))
        if result is None:
            _fail("UNSUPPORTED_EVENT_TYPE")
    elif name == "guest_count":
        result = integer_value(value if value is not None else entity.raw_value)
    elif name == "guest_count_range":
        if not isinstance(value, dict) or set(value) != {"min", "max"}:
            _fail("INVALID_RANGE_SHAPE")
        low, high = integer_value(value["min"]), integer_value(value["max"])
        if low > high:
            _fail("RANGE_INVERTED")
        result = (low, high)
    elif name == "event_date":
        result = date_value(value, entity.raw_value, today)
    elif name == "estimated_budget":
        result = amount_value(value, entity.raw_value)
    elif name == "budget_declined":
        if type(value) is not bool:
            _fail("INVALID_DECLINED_TYPE")
        result = value
    elif name == "requested_services":
        if value is None:
            value = [entity.raw_value]
        if not isinstance(value, list) or not value:
            _fail("INVALID_SERVICES_SHAPE")
        codes = []
        for item in value:
            if isinstance(item, dict):
                if set(item) != {"service_code", "status"} or item["status"] != "REQUESTED":
                    _fail("INVALID_SERVICE_OBJECT")
                item = item["service_code"]
            text = text_value(item)
            matches = [text.upper()] if text.upper() in service_catalog_codes() else (
                match_requested_services(text) or [])
            if not matches:
                warnings.append(rejection(entity, "UNSUPPORTED_SERVICE_ITEM"))
            codes.extend(code for code in matches if code not in codes)
        if not codes:
            _fail("NO_SUPPORTED_SERVICE")
        result = tuple(codes)
    elif name == "special_requests":
        result = text_value(value if value is not None else entity.raw_value)
    else:
        _fail("UNSUPPORTED_ENTITY")
    if name != "full_name" and (
        entity.needs_confirmation or entity.quality_status in {"INFERRED", "PENDING_CONFIRMATION"}
    ):
        _fail("ENTITY_NEEDS_CONFIRMATION")
    return Accepted(entity, result, tuple(warnings))


def comparable_value(value: EntityValue) -> object:
    if isinstance(value, EventDateTriplet):
        return value.event_date, value.event_month, value.event_date_type
    return value


def validate_entities(classification: IntentClassification, today: date) -> EntityBatch:
    decoded, rejected = decode_entities(classification)
    by_name: dict[str, Accepted] = {}
    blocked = {r.entity for r in rejected}
    for entity in decoded:
        try:
            accepted = validate_entity(entity, today)
        except InvalidEntity as error:
            rejected.append(rejection(entity, str(error)))
            blocked.add(entity.entity)
            continue
        rejected.extend(accepted.warnings)
        previous = by_name.get(entity.entity)
        if previous is not None and (
            comparable_value(previous.value) != comparable_value(accepted.value)
            or previous.entity.needs_confirmation != entity.needs_confirmation
        ):
            rejected.append(rejection(entity, "CONFLICTING_REPRESENTATIONS"))
            blocked.add(entity.entity)
        by_name[entity.entity] = previous or accepted
    count, bounds = by_name.get("guest_count"), by_name.get("guest_count_range")
    if count and bounds:
        if bounds.value != (count.value, count.value):
            rejected.append(rejection(count.entity, "CONFLICTING_GUEST_REPRESENTATIONS"))
            blocked.update(("guest_count", "guest_count_range"))
        else:
            by_name.pop("guest_count_range")
    amount, declined = by_name.get("estimated_budget"), by_name.get("budget_declined")
    if amount and declined and declined.value:
        rejected.append(rejection(amount.entity, "CONFLICTING_BUDGET_REPRESENTATIONS"))
        blocked.update(("estimated_budget", "budget_declined"))
    return EntityBatch(tuple(a for n, a in by_name.items() if n not in blocked), tuple(rejected))
