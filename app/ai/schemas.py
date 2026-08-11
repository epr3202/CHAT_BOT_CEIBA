from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    "UNKNOWN",
]

Priority = Literal["NORMAL", "URGENT", "CRITICAL"]


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_intent: Intent
    secondary_intents: list[Intent] = Field(default_factory=list)
    sub_intent: str | None
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    requested_action: str | None
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool
    needs_human: bool
    handoff_reason: str | None
    priority: Priority
    context_reference: dict[str, Any] = Field(default_factory=dict)
    reasoning_code: str

    @model_validator(mode="after")
    def require_handoff_reason_when_needed(self) -> IntentClassification:
        if self.needs_human and not self.handoff_reason:
            raise ValueError("handoff_reason is required when needs_human is true")
        return self
