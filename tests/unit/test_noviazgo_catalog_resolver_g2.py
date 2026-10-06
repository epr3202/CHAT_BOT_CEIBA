from __future__ import annotations

import inspect

import pytest

from app.conversation import catalog_event_type as catalog
from app.orchestrator.service import deterministic_booking_or_catalog_classification


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
    assert resolver(text, answering_event_type_question=True) == expected


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
    assert resolver(label, answering_event_type_question=True) == event_type


@pytest.mark.parametrize("text", ["pedida de noviazgo", "PEDIR NOVIAZGO", "pedidas de mano"])
def test_g2_6_fixed_price_resolver(text: str) -> None:
    assert catalog.resolve_fixed_price_information_type(text) == "PROPOSAL"


ANSWER_ONLY_LABELS = frozenset(
    {"noviazgo", "propuesta", "otro", "otro tipo de evento", "grado", "taller"}
)


def test_c1_answer_only_labels_are_explicit() -> None:
    assert getattr(catalog, "CATALOG_ANSWER_ONLY_LABELS", None) == ANSWER_ONLY_LABELS


@pytest.mark.parametrize("label", sorted(ANSWER_ONLY_LABELS))
def test_c1_answer_only_labels_are_ignored_outside_capture(label: str) -> None:
    assert catalog.resolve_catalog_event_type_mention(label) is None
    assert catalog.resolve_catalog_event_type_match(label) is None


@pytest.mark.parametrize(
    "text,event_type",
    [
        ("noviazgo", "PROPOSAL"),
        ("propuesta", "PROPOSAL"),
        ("otro", "OTHER"),
        ("otro tipo de evento", "OTHER"),
        ("grado", "GRADUATION"),
        ("taller", "WORKSHOP"),
    ],
)
def test_c1_answer_only_labels_resolve_in_capture(text: str, event_type: str) -> None:
    resolver = catalog.resolve_catalog_event_type_mention
    assert "answering_event_type_question" in inspect.signature(resolver).parameters
    assert resolver(text, answering_event_type_question=True) == event_type


@pytest.mark.parametrize(
    "text,expected",
    [
        ("aniversario de noviazgo", None),
        ("pedida de noviazgo con cena romantica", "PROPOSAL"),
        ("noviazgo", None),
        ("pedida de mano", "PROPOSAL"),
        ("pedida de mano para una boda civil", None),
        ("aniversario con pedida de noviazgo", None),
        ("pedida de mano con cena romántica y cumpleaños", None),
    ],
)
def test_c1_fixed_price_respects_other_event_ambiguity(text: str, expected: str | None) -> None:
    assert catalog.resolve_fixed_price_information_type(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "cuanto cuesta el salon? llevamos 3 años de noviazgo",
        "tengo una propuesta comercial para ustedes",
        "para celebrar 2 años de noviazgo",
        "mandame otro catalogo",
    ],
)
def test_c2_incidental_mentions_do_not_bypass_classifier(text: str) -> None:
    assert deterministic_booking_or_catalog_classification(text, {"pending_action": None}) is None


def test_c2_single_word_proposal_label_cannot_expand_deterministic_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A future one-word alias must not weaken the explicit-phrase guard.
    monkeypatch.setitem(catalog.CATALOG_EVENT_TYPE_LABELS, "PROPOSAL", ("compromiso",))
    assert deterministic_booking_or_catalog_classification("compromiso", {}) is None
    result = deterministic_booking_or_catalog_classification("catálogo de compromiso", {})
    assert result is not None and result.information_category == "catalog_request"
