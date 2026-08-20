from __future__ import annotations

import importlib
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.event.models import Event
from app.orchestrator import service as orchestrator_service
from app.orchestrator.service import apply_event_type, classified_catalog_event_type
from app.orchestrator.slot_filling import CaptureProgress, select_next_question


def event_type_entity(value: str, *, quality_status: str = "PROVIDED") -> ExtractedEntity:
    return ExtractedEntity(
        entity="event_type",
        raw_value=value,
        normalized_value=value,
        quality_status=quality_status,
        confidence=0.95,
        needs_confirmation=False,
        validation_errors=[],
    )


def classification_with_event_type(value: str) -> IntentClassification:
    return IntentClassification(
        primary_intent="GENERAL_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category="catalogo",
        entities={},
        extracted_entities=[event_type_entity(value)],
        requested_action="START_INFORMATION_FLOW",
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TEST_EVENT_TYPE_NORMALIZATION",
    )


def normalize_event_type(value: str | None) -> str | None:
    module = importlib.import_module("app.event.event_type")
    return module.normalize_event_type(value)


@pytest.mark.parametrize(
    "value",
    ["GENDER REVEAL", "gender-reveal", " GENDER_REVEAL "],
)
def test_event_type_normalizer_canonicalizes_classifier_variants(value: str) -> None:
    assert normalize_event_type(value) == "GENDER_REVEAL"


def test_event_type_normalizer_degrades_unknown_value_to_none() -> None:
    assert normalize_event_type("FIESTA") is None


@pytest.mark.parametrize(
    "value",
    ["GENDER REVEAL", "gender-reveal", " GENDER_REVEAL "],
)
def test_catalog_entity_consumer_uses_canonical_event_type(value: str) -> None:
    classification = classification_with_event_type(value)

    assert classified_catalog_event_type(classification) == "GENDER_REVEAL"


def test_catalog_entity_consumer_discards_and_audits_unknown_value() -> None:
    session = Mock()
    classification = classification_with_event_type("FIESTA")

    normalized_classification = (
        orchestrator_service.normalize_classification_event_type_entities(
            session,
            classification,
            "req-invalid-catalog-event-type",
        )
    )

    assert classified_catalog_event_type(normalized_classification) is None
    assert normalized_classification.extracted_entities == []
    assert normalized_classification.entities == {}
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AuditEvent)
    assert audit.action == "EVENT_TYPE_ENTITY_DISCARDED"
    assert audit.new_value == {
        "raw_value": "FIESTA",
        "normalized_value": "FIESTA",
    }
    assert audit.request_id == "req-invalid-catalog-event-type"


def test_entity_list_consumer_discards_and_audits_unknown_value() -> None:
    session = Mock()

    normalized = orchestrator_service.normalize_event_type_entities(
        session,
        [event_type_entity("FIESTA")],
        "req-invalid-event-list-type",
    )

    assert normalized == []
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AuditEvent)
    assert audit.action == "EVENT_TYPE_ENTITY_DISCARDED"
    assert audit.new_value == {
        "raw_value": "FIESTA",
        "normalized_value": "FIESTA",
    }
    assert audit.request_id == "req-invalid-event-list-type"


@pytest.mark.parametrize(
    "value",
    ["GENDER REVEAL", "gender-reveal", " GENDER_REVEAL "],
)
@pytest.mark.parametrize("quality_status", ["PROVIDED", "CORRECTED"])
def test_event_creation_and_edit_normalize_before_model_validation(
    value: str,
    quality_status: str,
) -> None:
    event = Event(lead_id=uuid4())

    apply_event_type(
        Mock(),
        event,
        event_type_entity(value, quality_status=quality_status),
        "req-valid-event-type",
    )

    assert event.event_type == "GENDER_REVEAL"


def test_event_creation_discards_and_audits_unknown_value_without_exception() -> None:
    session = Mock()
    event = Event(lead_id=uuid4())

    apply_event_type(
        session,
        event,
        event_type_entity("FIESTA"),
        "req-invalid-event-type",
    )

    assert event.event_type is None
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AuditEvent)
    assert audit.action == "EVENT_TYPE_ENTITY_DISCARDED"
    assert audit.new_value == {
        "raw_value": "FIESTA",
        "normalized_value": "FIESTA",
    }
    assert audit.request_id == "req-invalid-event-type"


@pytest.mark.parametrize(
    ("value", "expected_question"),
    [
        ("GENDER REVEAL", "COLLECT_GUEST_COUNT"),
        ("gender-reveal", "COLLECT_GUEST_COUNT"),
        (" GENDER_REVEAL ", "COLLECT_GUEST_COUNT"),
        ("FIESTA", "COLLECT_EVENT_TYPE"),
    ],
)
def test_slot_filling_consumes_only_normalized_known_event_types(
    value: str,
    expected_question: str,
) -> None:
    assert select_next_question(CaptureProgress(event_type=value)) == expected_question
