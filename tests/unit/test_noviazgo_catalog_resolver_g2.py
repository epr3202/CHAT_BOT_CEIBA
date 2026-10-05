from __future__ import annotations

import pytest

from app.conversation import catalog_event_type as catalog


@pytest.mark.parametrize(
    "text,expected",
    [
        ("pedida de noviazgo", "PROPOSAL"),
        ("Pedidas de noviazgo.", "PROPOSAL"),
        ("PEDIR NOVIAZGO", "PROPOSAL"),
        ("pedirle noviazgo", "PROPOSAL"),
        ("quiero ver el catálogo de pedidas de noviazgo", "PROPOSAL"),
        ("¿Quieres ser mi novia?", "PROPOSAL"),
        ("pedidas de mano", "PROPOSAL"),
        ("anillo de compromiso", "PROPOSAL"),
        ("boda civil", "CIVIL_WEDDING"),
        ("los planes románticos", "ROMANTIC_DINNER"),
        ("aniversario de noviazgo", None),
        ("no sé todavía", None),
        ("noviazgos", None),
        ("quiero algo para mi novia", None),
        ("catálogo: boda, civil", "CIVIL_WEDDING"),
        ("boda civil y cumpleaños", None),
        ("supernoviazgo", None),
    ],
)
def test_g2_7_phrase_resolver(text: str, expected: str | None) -> None:
    resolver = getattr(catalog, "resolve_catalog_event_type_mention", None)
    assert callable(resolver), "R2 must expose its phrase resolver before any import is required"
    assert resolver(text) == expected


@pytest.mark.parametrize(
    "event_type,label",
    [
        (event_type, label)
        for event_type, labels in catalog.CATALOG_EVENT_TYPE_LABELS.items()
        for label in labels
    ],
)
def test_g2_7_every_existing_label(event_type: str, label: str) -> None:
    resolver = getattr(catalog, "resolve_catalog_event_type_mention", None)
    assert callable(resolver), "R2 phrase resolver is missing"
    assert resolver(label) == event_type


@pytest.mark.parametrize("text", ["pedida de noviazgo", "PEDIR NOVIAZGO", "pedidas de mano"])
def test_g2_6_fixed_price_resolver(text: str) -> None:
    assert catalog.resolve_fixed_price_information_type(text) == "PROPOSAL"
