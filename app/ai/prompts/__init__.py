"""Versioned AI prompts."""

from __future__ import annotations

from typing import Literal, NamedTuple

from app.ai.prompts import intent_v1, intent_v2, intent_v3, intent_v4

IntentPromptVersion = Literal["intent_v1", "intent_v2", "intent_v3", "intent_v4"]


class IntentPrompt(NamedTuple):
    version: IntentPromptVersion
    content: str


_INTENT_PROMPTS: dict[IntentPromptVersion, IntentPrompt] = {
    "intent_v1": IntentPrompt(
        version="intent_v1",
        content=intent_v1.INTENT_CLASSIFICATION_PROMPT,
    ),
    "intent_v2": IntentPrompt(
        version="intent_v2",
        content=intent_v2.INTENT_CLASSIFICATION_PROMPT,
    ),
    "intent_v3": IntentPrompt(
        version="intent_v3",
        content=intent_v3.INTENT_CLASSIFICATION_PROMPT,
    ),
    "intent_v4": IntentPrompt(
        version="intent_v4",
        content=intent_v4.INTENT_CLASSIFICATION_PROMPT,
    ),
}


def get_intent_prompt(version: IntentPromptVersion) -> IntentPrompt:
    return _INTENT_PROMPTS[version]
