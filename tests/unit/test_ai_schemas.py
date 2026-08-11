from __future__ import annotations

import re
from typing import get_args

import pytest
from pydantic import ValidationError

from app.ai.schemas import FAQCategory, Intent, IntentClassification
from app.conversation.faq_catalog import FAQ_CATEGORY_VALUES


def test_intent_literal_matches_document_catalog() -> None:
    with open("docs/conversation/intents.md", encoding="utf-8") as document:
        content = document.read()

    match = re.search(
        r"# 4\. Catálogo principal de intenciones.*?```text\n(?P<intents>.*?)\n```",
        content,
        flags=re.DOTALL,
    )
    assert match is not None

    documented_intents = [
        line.strip()
        for line in match.group("intents").splitlines()
        if line.strip()
    ]

    assert list(get_args(Intent)) == documented_intents


def test_unknown_intent_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        IntentClassification.model_validate(
            {
                "primary_intent": "INVENTED_INTENT",
                "secondary_intents": [],
                "sub_intent": None,
                "confidence": 0.5,
                "entities": {},
                "requested_action": None,
                "missing_fields": [],
                "needs_confirmation": False,
                "needs_human": False,
                "handoff_reason": None,
                "priority": "NORMAL",
                "context_reference": {},
                "reasoning_code": "TEST",
            }
        )


def test_unknown_information_category_degrades_to_none() -> None:
    classification = IntentClassification.model_validate(
        {
            "primary_intent": "GENERAL_INFORMATION",
            "secondary_intents": [],
            "sub_intent": None,
            "confidence": 0.91,
            "information_category": "information_type_random",
            "entities": {},
            "requested_action": None,
            "missing_fields": [],
            "needs_confirmation": False,
            "needs_human": False,
            "handoff_reason": None,
            "priority": "NORMAL",
            "context_reference": {},
            "reasoning_code": "TEST",
        }
    )

    assert classification.information_category is None


def test_faq_category_literal_matches_catalog_keys() -> None:
    assert tuple(get_args(FAQCategory)) == FAQ_CATEGORY_VALUES
