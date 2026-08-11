from __future__ import annotations

import re
from typing import get_args

from app.ai.prompts import IntentPromptVersion, get_intent_prompt
from app.ai.schemas import FAQCategory
from app.conversation.faq_catalog import CATEGORY_RESPONSE_CODES


def test_both_intent_prompt_versions_render_contract() -> None:
    versions: tuple[IntentPromptVersion, ...] = ("intent_v1", "intent_v2")

    for version in versions:
        prompt = get_intent_prompt(version)

        assert prompt.version == version
        assert "Catálogo de intenciones principales" in prompt.content
        assert "Contrato JSON exacto" in prompt.content
        assert '"primary_intent"' in prompt.content
        assert "No inventes categorías" in prompt.content


def test_intent_v2_adds_explicit_confidence_rubric() -> None:
    prompt = get_intent_prompt("intent_v2")

    assert "Rúbrica explícita de confianza" in prompt.content
    assert "confidence > 0.85" in prompt.content
    assert "confidence entre 0.50 y 0.70" in prompt.content
    assert "confidence < 0.50" in prompt.content
    assert '"sí" sin pending_action ni last_question_code' in prompt.content


def test_faq_categories_match_literal_catalog_and_both_prompts() -> None:
    expected = tuple(CATEGORY_RESPONSE_CODES.keys())

    assert tuple(get_args(FAQCategory)) == expected
    for version in ("intent_v1", "intent_v2"):
        prompt = get_intent_prompt(version)
        assert extract_faq_categories_from_prompt(prompt.content) == expected


def extract_faq_categories_from_prompt(prompt: str) -> tuple[str, ...]:
    match = re.search(
        r"<!-- FAQ_CATEGORY_VALUES_START -->\n(?P<values>.*?)\n<!-- FAQ_CATEGORY_VALUES_END -->",
        prompt,
        flags=re.DOTALL,
    )
    assert match is not None
    return tuple(
        line.removeprefix("- ").strip()
        for line in match.group("values").splitlines()
        if line.strip()
    )
