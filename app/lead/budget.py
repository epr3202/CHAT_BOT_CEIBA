from __future__ import annotations

import re
from decimal import Decimal

REFERENCE_BUDGET_COP = Decimal("4000000")

_NUMBER_WORDS = {
    "un": Decimal(1),
    "uno": Decimal(1),
    "una": Decimal(1),
    "dos": Decimal(2),
    "tres": Decimal(3),
    "cuatro": Decimal(4),
    "cinco": Decimal(5),
    "seis": Decimal(6),
    "siete": Decimal(7),
    "ocho": Decimal(8),
    "nueve": Decimal(9),
    "diez": Decimal(10),
    "once": Decimal(11),
    "doce": Decimal(12),
    "medio": Decimal("0.5"),
    "media": Decimal("0.5"),
}


def parse_cop_amount(raw_value: str) -> Decimal:
    normalized = raw_value.strip().casefold()
    if not normalized:
        raise ValueError("INVALID_NUMBER")
    if "-" in normalized or normalized.startswith("menos "):
        raise ValueError("INVALID_NUMBER")

    compact = normalized.replace("$", "").replace("cop", "").strip()
    compact = compact.replace(",", ".")
    if match := re.search(r"(\d+(?:\.\d+)?)\s*m\b", compact):
        return _positive_amount(Decimal(match.group(1)) * Decimal(1_000_000))

    if "millon" in compact or "millón" in compact or "millones" in compact:
        before = re.split(r"millones?|millón", compact, maxsplit=1)[0].strip()
        amount = _parse_spanish_number(before)
        if "medio" in compact or "media" in compact:
            amount += Decimal("0.5")
        return _positive_amount(amount * Decimal(1_000_000))

    digits = re.sub(r"[^\d.]", "", compact)
    if digits:
        amount = Decimal(digits)
        if amount < Decimal(1000) and "." in digits:
            amount *= Decimal(1_000_000)
        return _positive_amount(amount)

    raise ValueError("INVALID_NUMBER")


def calculate_budget_range(amount: Decimal | None) -> str:
    if amount is None:
        return "NOT_PROVIDED"
    if amount < REFERENCE_BUDGET_COP:
        return "BELOW_REFERENCE"
    if amount < Decimal("12000000"):
        return "REFERENCE_RANGE"
    return "PREMIUM"


def _parse_spanish_number(value: str) -> Decimal:
    cleaned = value.replace("y", " ")
    total = Decimal(0)
    for token in cleaned.split():
        if token in _NUMBER_WORDS:
            total += _NUMBER_WORDS[token]
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            total += Decimal(token)
    if total <= 0:
        raise ValueError("INVALID_NUMBER")
    return total


def _positive_amount(amount: Decimal) -> Decimal:
    if amount <= 0:
        raise ValueError("INVALID_NUMBER")
    return amount.quantize(Decimal("1"))
