"""Narrow full-turn recognition; unrecognized never means a safe negative intent."""

from __future__ import annotations

import pytest

from app.conversation.explicit_human import is_explicit_human_request
from tests.remediation.test_r1_outbox import evidence

CASES = {
    "advisor": ("Quiero hablar con un asesor", True),
    "advisor_female": ("Necesito hablar con una asesora", True),
    "question": ("¿Me puedes comunicar con un asesor?", True),
    "please_team": ("Por favor, pásame con una persona del equipo", True),
    "personal_attention": ("Quiero que me atienda una persona", True),
    "spacing_caps": ("  QUIERO   HABLAR\nCON  UN  ASESOR!!! ", True),
    "accentless": ("por favor, pasame con una persona del equipo.", True),
    "courtesy_suffix": ("Quiero hablar con un asesor, por favor.", True),
    "person": ("Quiero hablar con una persona.", True),
    "someone": ("Quiero hablar con alguien", True),
    "pass_advisor": ("Pásame un asesor", True),
    "need_person": ("Necesito una persona", True),
    "repeated": ("Quiero hablar con un asesor; quiero hablar con un asesor", True),
    "local_negation": ("No quiero más información; quiero hablar con un asesor", True),
    "negated": ("No quiero hablar con un asesor", False),
    "catalog_only": ("No necesito un asesor, solo el catálogo", False),
    "conditional": ("Si necesito un asesor después, les aviso", False),
    "third_party": ("Mi pareja quiere hablar con un asesor", False),
    "definition": ("¿Qué hace un asesor?", False),
    "reported": ("El mensaje dice: quiero hablar con un asesor", False),
    "quoted": ('"Quiero hablar con un asesor"', False),
    "curly_quoted": ("«Quiero hablar con un asesor»", False),
    "decline": ("No, gracias", False),
    "partial_word": ("Quiero hablar con un asesoramiento", False),
    "withdrawn": ("Quiero hablar con un asesor; ya no lo necesito", False),
    "contradictory": ("Quiero hablar con un asesor, pero no me comuniques", False),
    "negated_repeat": ("Quiero hablar con un asesor. No quiero hablar con un asesor", False),
    "future": ("Mañana quiero hablar con un asesor", False),
    "hypothetical": ("Si fuera necesario, quiero hablar con un asesor", False),
    "complaint_mix": ("Tengo una queja; quiero hablar con un asesor", False),
    "emergency_mix": ("Hay una emergencia. Quiero hablar con un asesor", False),
    "payment_mix": ("Ya pagué; quiero hablar con un asesor", False),
    "unknown_content": ("Quiero hablar con un asesor sobre un reembolso", False),
    "empty": (" ", False),
}


@pytest.mark.parametrize("case", list(CASES))
def test_explicit_phrase_contract(case: str, request: pytest.FixtureRequest) -> None:
    body, expected = CASES[case]
    actual = is_explicit_human_request(body)
    evidence(request, input=body, expected=expected, recognized=actual)
    assert actual is expected
