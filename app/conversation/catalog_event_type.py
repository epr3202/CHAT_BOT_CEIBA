from __future__ import annotations

import re
import unicodedata

# Source of truth: docs/conversation/entities.md, section 7.1.
CATALOG_EVENT_TYPE_LABELS: dict[str, tuple[str, ...]] = {
    "WEDDING": ("boda", "matrimonio"),
    "CIVIL_WEDDING": ("boda civil", "matrimonio civil", "ceremonia civil"),
    "PROPOSAL": ("propuesta", "propuesta de matrimonio", "pedida de mano"),
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
    "OTHER": ("otro", "otro tipo de evento"),
}

_TERMINAL_PUNCTUATION = ".,;:!?"


def normalize_catalog_event_type_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    collapsed = re.sub(r"\s+", " ", without_accents.strip())
    return collapsed.rstrip(_TERMINAL_PUNCTUATION).rstrip()


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
