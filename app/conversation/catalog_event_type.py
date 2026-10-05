from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

# Fixed-price plans do not require a customer budget during event capture.
FIXED_PRICE_EVENT_TYPES = {"ROMANTIC_DINNER", "PROPOSAL"}

# Source of truth: docs/conversation/entities.md, section 7.1.
CATALOG_EVENT_TYPE_LABELS: dict[str, tuple[str, ...]] = {
    "WEDDING": ("boda", "matrimonio"),
    "CIVIL_WEDDING": ("boda civil", "matrimonio civil", "ceremonia civil"),
    "PROPOSAL": (
        "propuesta",
        "propuesta de matrimonio",
        "pedida de mano",
        "pedida de noviazgo",
        "pedidas de noviazgo",
        "pedir noviazgo",
        "pedirle noviazgo",
        "propuesta de noviazgo",
        "noviazgo",
        "pedidas de mano",
        "quieres ser mi",
        "pedirle matrimonio",
        "pedir la mano",
        "pedirle la mano",
        "proponerle matrimonio",
        "anillo de compromiso",
        "fiesta de compromiso",
        "celebracion de compromiso",
    ),
    "BIRTHDAY": ("cumpleaños",),
    "GRADUATION": ("graduación", "grado"),
    "ANNIVERSARY": ("aniversario",),
    "ROMANTIC_DINNER": (
        "cena romántica",
        "plan romántico",
        "planes románticos",
        "los planes románticos",
    ),
    "CORPORATE_EVENT": ("evento corporativo", "evento empresarial"),
    "FAMILY_EVENT": ("evento familiar", "reunión familiar"),
    "BAPTISM": ("bautizo", "bautismo"),
    "FIRST_COMMUNION": ("primera comunión",),
    "BABY_SHOWER": ("baby shower",),
    "WORKSHOP": ("taller",),
    "POOL_DAY": ("día de piscina", "pasadía de piscina"),
    "PRIVATE_DINNER": ("cena privada",),
    "GENDER_REVEAL": ("revelación de género", "revelacion de genero", "gender reveal"),
    "OTHER": ("otro", "otro tipo de evento"),
}


def normalize_catalog_event_type_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in without_accents
    )
    return " ".join(without_punctuation.split())


_EVENT_TYPE_BY_NORMALIZED_LABEL = {
    normalize_catalog_event_type_label(label): event_type
    for event_type, labels in CATALOG_EVENT_TYPE_LABELS.items()
    for label in labels
}


def resolve_catalog_event_type_label(message_text: str) -> str | None:
    normalized = normalize_catalog_event_type_label(message_text)
    if not normalized:
        return None
    return _EVENT_TYPE_BY_NORMALIZED_LABEL.get(normalized)


@dataclass(frozen=True)
class CatalogEventTypeMention:
    event_type: str
    matched_label: str
    start: int
    end: int


def _catalog_event_type_mentions(message_text: str) -> list[CatalogEventTypeMention]:
    normalized = normalize_catalog_event_type_label(message_text)
    matches = [
        CatalogEventTypeMention(event_type, label, match.start(), match.end())
        for event_type, labels in CATALOG_EVENT_TYPE_LABELS.items()
        for label in labels
        for match in re.finditer(
            rf"(?<!\w){re.escape(normalize_catalog_event_type_label(label))}(?!\w)",
            normalized,
        )
    ]
    # A longer phrase owns its span; independent mentions keep their own type.
    return [
        match
        for match in matches
        if not any(
            other.start <= match.start
            and match.end <= other.end
            and (other.start, other.end) != (match.start, match.end)
            for other in matches
        )
    ]


def resolve_catalog_event_type_match(message_text: str) -> CatalogEventTypeMention | None:
    matches = _catalog_event_type_mentions(message_text)
    if len({match.event_type for match in matches}) != 1:
        return None
    return max(matches, key=lambda match: (match.end - match.start, -match.start))


def resolve_catalog_event_type_mention(text: str) -> str | None:
    match = resolve_catalog_event_type_match(text)
    return match.event_type if match is not None else None


def resolve_fixed_price_information_match(message_text: str) -> CatalogEventTypeMention | None:
    # Product preserves PROPOSAL priority in fixed-price information, including
    # mixed romantic/proposal phrases. Matching and labels still have one source.
    proposals = [
        match
        for match in _catalog_event_type_mentions(message_text)
        if match.event_type == "PROPOSAL"
    ]
    return max(proposals, key=lambda match: (match.end - match.start, -match.start), default=None)


def resolve_fixed_price_information_type(message_text: str) -> Literal["PROPOSAL"] | None:
    return "PROPOSAL" if resolve_fixed_price_information_match(message_text) is not None else None
