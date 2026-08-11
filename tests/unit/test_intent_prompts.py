from __future__ import annotations

from app.ai.prompts import IntentPromptVersion, get_intent_prompt


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
