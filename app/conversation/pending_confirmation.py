"""Pure discrimination of local proposal authority; no I/O, clocks or business actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.ai.schemas import IntentClassification
from app.conversation.faq_catalog import FAQ_CATEGORY_VALUES

NAME_ACTIONS = {
    "COLLECT_EVENT_TYPE", "COLLECT_GUEST_COUNT", "COLLECT_EVENT_DATE",
    "COLLECT_CUSTOMER_NAME", "COLLECT_BUDGET", "COLLECT_SERVICES",
}
NAME_STATES = {
    "COLLECTING_EVENT_DATA", "WAITING_FOR_APPOINTMENT_DATE",
    "WAITING_FOR_APPOINTMENT_SELECTION", "APPOINTMENT_PENDING_CONFIRMATION",
}


@dataclass(frozen=True)
class PendingProposal:
    kind: Literal["ABSENT", "INVALID", "RESOLVED", "CLASSIFICATION", "NAME"]
    reason: str | None = None
    classification: IntentClassification | None = None
    full_name: str | None = None


def proposal_context(state: str, active_lead_id: object) -> dict[str, Any]:
    return {"state": state, "active_lead_id": str(active_lead_id) if active_lead_id else None}


def name_value(value: object) -> str | None:
    # Structural boundary only. No coercion of arbitrary JSON into customer data.
    return value.strip() if isinstance(value, str) and value.strip() else None


def read_pending(
    value: object, *, state: str, pending_action: str | None,
    last_question_code: str | None, active_lead_id: object,
) -> PendingProposal:
    if value is None or value == {}:
        return PendingProposal("ABSENT")
    if not isinstance(value, dict):
        return PendingProposal("INVALID", "NON_OBJECT")
    if "resolved_intent" in value:
        return PendingProposal("RESOLVED", "RESOLUTION_HAS_NO_AUTHORITY")
    kind = value.get("type")
    versioned = "version" in value
    if versioned and (type(value["version"]) is not int or value["version"] != 1):
        return PendingProposal("INVALID", "UNSUPPORTED_VERSION")
    if versioned and value.get("context") != proposal_context(state, active_lead_id):
        return PendingProposal("INVALID", "CONTEXT_CHANGED")

    if kind == "FULL_NAME_CONFIRMATION":
        if "classification" in value:
            return PendingProposal("INVALID", "MIXED_FAMILIES")
        name = name_value(value.get("full_name"))
        if name is None:
            return PendingProposal("INVALID", "INVALID_NAME_SHAPE")
        if state not in NAME_STATES or (
            pending_action not in NAME_ACTIONS and not (versioned and pending_action is None)
        ):
            return PendingProposal("INVALID", "NAME_CONTEXT_MISSING")
        if not versioned and (
            pending_action != "COLLECT_CUSTOMER_NAME" or last_question_code != "RESP-CUSTOMER-001"
        ):
            return PendingProposal("INVALID", "AMBIGUOUS_LEGACY_NAME")
        return PendingProposal("NAME", full_name=name)

    if kind is not None and (kind != "CLASSIFICATION_CONFIRMATION" or not versioned):
        return PendingProposal("INVALID", "UNKNOWN_DISCRIMINATOR")
    if versioned and kind != "CLASSIFICATION_CONFIRMATION":
        return PendingProposal("INVALID", "MISSING_DISCRIMINATOR")
    if pending_action != "CLASSIFY_MESSAGE":
        return PendingProposal("INVALID", "CLASSIFICATION_CONTEXT_MISSING")
    if not versioned and last_question_code != "RESP-FALLBACK-004":
        return PendingProposal("INVALID", "AMBIGUOUS_LEGACY_CLASSIFICATION")
    payload = value.get("classification")
    if not isinstance(payload, dict):
        return PendingProposal("INVALID", "INVALID_CLASSIFICATION_SHAPE")
    category = payload.get("information_category")
    if category is not None and (
        not isinstance(category, str) or category not in FAQ_CATEGORY_VALUES
    ):
        return PendingProposal("INVALID", "INVALID_CLASSIFICATION_CATEGORY")
    try:
        classification = IntentClassification.model_validate(payload)
    except ValidationError:
        return PendingProposal("INVALID", "INVALID_CLASSIFICATION_SCHEMA")
    if value.get("original_intent", classification.primary_intent) != classification.primary_intent:
        return PendingProposal("INVALID", "INCONSISTENT_CLASSIFICATION")
    if value.get("original_confidence", classification.confidence) != classification.confidence:
        return PendingProposal("INVALID", "INCONSISTENT_CONFIDENCE")
    return PendingProposal("CLASSIFICATION", classification=classification)
