from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.conversation.faq_catalog import FAQ_CATEGORY_VALUES
from app.conversation.services_catalog import service_catalog_codes

logger = logging.getLogger(__name__)

Intent = Literal[
    "GREETING",
    "GENERAL_INFORMATION",
    "EVENT_INFORMATION",
    "QUOTE_REQUEST",
    "MODIFY_EVENT_DATA",
    "SCHEDULE_VISIT",
    "RESCHEDULE_VISIT",
    "CANCEL_VISIT",
    "PAYMENT_MESSAGE",
    "RESERVATION_INFORMATION",
    "EVENT_CANCELLATION",
    "HUMAN_REQUEST",
    "COMPLAINT",
    "EMERGENCY",
    "FAREWELL",
    "CONFIRM",
    "DENY",
    "UNKNOWN",
]

Priority = Literal["NORMAL", "URGENT", "CRITICAL"]
FAQCategory = Literal[*FAQ_CATEGORY_VALUES]
EntityName = Literal[
    "full_name",
    "event_type",
    "event_date",
    "guest_count",
    "guest_count_range",
    "estimated_budget",
    "budget_declined",
    "requested_services",
    "special_requests",
]
EntityQualityStatus = Literal[
    "PROVIDED",
    "INFERRED",
    "PENDING_CONFIRMATION",
    "CORRECTED",
    "INVALID",
]
ServiceCode = Literal[*service_catalog_codes()]


class ServicesClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_codes: list[ServiceCode]


class EventTypeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: EntityName
    raw_value: str
    normalized_value: Any = None
    quality_status: EntityQualityStatus
    confidence: float = Field(ge=0, le=1)
    needs_confirmation: bool = False
    validation_errors: list[str] = Field(default_factory=list)


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_intent: Intent
    secondary_intents: list[Intent] = Field(default_factory=list)
    sub_intent: str | None
    confidence: float = Field(ge=0, le=1)
    information_category: FAQCategory | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)
    requested_action: str | None
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool
    needs_human: bool
    handoff_reason: str | None
    priority: Priority
    context_reference: dict[str, Any] = Field(default_factory=dict)
    reasoning_code: str

    @field_validator("information_category", mode="before")
    @classmethod
    def unknown_information_category_becomes_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value in FAQ_CATEGORY_VALUES:
            return value
        logger.info("ai_invalid_information_category", extra={"information_category": value})
        return None

    @model_validator(mode="after")
    def require_handoff_reason_when_needed(self) -> IntentClassification:
        if self.needs_human and not self.handoff_reason:
            raise ValueError("handoff_reason is required when needs_human is true")
        return self
