from __future__ import annotations

import importlib
import re
from unittest.mock import Mock

import pytest

from app.ai.schemas import ExtractedEntity
from app.conversation.presentation import EVENT_TYPE_LABELS, format_event_type
from app.event.models import EVENT_TYPES, Event
from app.orchestrator.service import apply_event_type


def normalize_event_type(value: str | None) -> str | None:
    """Load the T3 public API without making this red-first suite fail collection."""
    module = importlib.import_module("app.event.event_type")
    normalizer = module.normalize_event_type
    return normalizer(value)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        pytest.param("CENA ROMÁNTICA", "ROMANTIC_DINNER", id="TC-ETYPE-001"),
        pytest.param("cena romantica", "ROMANTIC_DINNER", id="TC-ETYPE-002"),
        pytest.param("Propuesta de matrimonio", "PROPOSAL", id="TC-ETYPE-003"),
        pytest.param("ROMANTIC_DINNER", "ROMANTIC_DINNER", id="TC-ETYPE-004"),
        pytest.param(" romantic_dinner ", "ROMANTIC_DINNER", id="TC-ETYPE-005"),
    ],
)
def test_classifier_event_type_aliases_normalize_to_canonical_enum(
    raw_value: str,
    expected: str,
) -> None:
    assert normalize_event_type(raw_value) == expected


def test_tc_etype_006_unrecognized_value_normalizes_to_unresolved() -> None:
    assert normalize_event_type("FIESTA GALÁCTICA") is None


def test_tc_etype_006_raw_fallback_never_reaches_domain_persistence() -> None:
    event = Event(lead_id=None)  # type: ignore[arg-type]
    entity = ExtractedEntity(
        entity="event_type",
        raw_value="FIESTA GALÁCTICA",
        normalized_value="FIESTA GALÁCTICA",
        quality_status="PROVIDED",
        confidence=0.92,
    )

    apply_event_type(Mock(), event, entity, "request-etype-006")

    assert event.event_type is None


def test_tc_etype_008_normalization_is_pure_and_deterministic() -> None:
    inputs = (" CENA  ROMÁNTICA ", "propuesta", "FIESTA GALÁCTICA", None)

    first = tuple(normalize_event_type(value) for value in inputs)
    second = tuple(normalize_event_type(value) for value in inputs)

    assert first == second


def test_tc_display_001_template_value_uses_natural_spanish_display_name() -> None:
    rendered = "Te comparto nuestro catálogo para {event_type}.".format(
        event_type=format_event_type("ROMANTIC_DINNER")
    )

    assert "cena romántica" in rendered
    assert "ROMANTIC_DINNER" not in rendered


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda value: f"TC-DISPLAY-002-{value}")
def test_every_official_event_type_has_a_non_enum_display_name(event_type: str) -> None:
    assert set(EVENT_TYPE_LABELS) == set(EVENT_TYPES)
    assert format_event_type(event_type) == EVENT_TYPE_LABELS[event_type]
    assert EVENT_TYPE_LABELS[event_type] != event_type


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda value: f"TC-DISPLAY-003-{value}")
def test_composed_message_never_exposes_raw_event_type_identifier(event_type: str) -> None:
    rendered = f"Para {format_event_type(event_type)}, revisaremos el espacio."
    raw_enum = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")

    assert raw_enum.search(rendered) is None


def test_tc_display_004_verbatim_user_text_is_not_reused_as_template_value() -> None:
    user_text = "CENA ROMÁNTICA!!!"
    rendered = "Te comparto nuestro catálogo para {event_type}.".format(
        event_type=format_event_type("ROMANTIC_DINNER")
    )

    assert user_text not in rendered
    assert "cena romántica" in rendered
