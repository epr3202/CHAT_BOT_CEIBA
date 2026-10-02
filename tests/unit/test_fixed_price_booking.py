"""F4: every significant plan word must match within its own edit budget."""

from typing import Any

import pytest

from app.conversation.fixed_price_booking import match_booking_plan
from tests.b1a_contracts import EXPECTED_PLANS


@pytest.fixture
def plans() -> list[dict[str, Any]]:
    return [
        {"name": name, "event_type": properties[0]} for name, properties in EXPECTED_PLANS.items()
    ]


@pytest.mark.parametrize(
    "message,expected_name",
    [
        ("me intrese ritual de conrazon", "Ritual del Corazón"),
        ("Ritual del corazon", "Ritual del Corazón"),
        ("romance entre copaz", "Romance entre Copas"),
        ("mananas de encanto", "Mañanas de Encanto"),
        ("me interesa el ritual del corazón para el 15", "Ritual del Corazón"),
        ("cinema", None),
        ("ritual y copas", None),
        ("quiero visitar antes de elegir el ritual del corazón", None),
    ],
)
def test_f4_required_romantic_examples(
    message: str,
    expected_name: str | None,
    plans: list[dict[str, Any]],
) -> None:
    romantic_plans = [plan for plan in plans if plan["event_type"] == "ROMANTIC_DINNER"]
    matched = match_booking_plan(message, romantic_plans)
    assert (matched["name"] if matched else None) == expected_name


def test_f4_required_proposal_example(plans: list[dict[str, Any]]) -> None:
    proposal_plans = [plan for plan in plans if plan["event_type"] == "PROPOSAL"]
    matched = match_booking_plan("quiero la noche inolvidable", proposal_plans)
    assert matched is not None
    assert matched["name"] == "Noche Inolvidable"


@pytest.mark.parametrize(
    "message",
    [
        "corazón, para el 15 quiero ese ritual",
        "¡CORAZÓN! Me interesa el RITUAL.",
        "rxtuxl de coxaxon",
    ],
)
def test_f4_words_can_be_reordered_separated_and_independently_misspelled(
    message: str,
    plans: list[dict[str, Any]],
) -> None:
    matched = match_booking_plan(message, plans)
    assert matched is not None
    assert matched["name"] == "Ritual del Corazón"


@pytest.mark.parametrize(
    "connector",
    [
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "y",
        "para",
        "entre",
        "un",
        "una",
    ],
)
def test_f4_ignores_each_insignificant_plan_word(connector: str) -> None:
    plan = {"name": f"Ritual {connector} Corazón"}
    assert match_booking_plan("corazon ritual", [plan]) is plan


@pytest.mark.parametrize(
    "name,message,matched",
    [
        ("Dos", "dos", True),
        ("Dos", "doz", False),
        ("Dos", "do", False),
        ("Dos", "doss", False),
        ("Amor", "amxr", True),
        ("Amor", "amr", True),
        ("Amor", "amoor", True),
        ("Amor", "amxx", False),
        ("Amor", "amorxx", False),
        ("Copas", "copaz", True),
        ("Copas", "copa", True),
        ("Copas", "copass", True),
        ("Copas", "cpxas", False),
        ("Ritual", "rxtuxl", True),
        ("Ritual", "ritl", True),
        ("Ritual", "rixxtual", True),
        ("Ritual", "rxtxxl", False),
        ("Ritual", "rit", False),
        ("Ritual", "rixxxtual", False),
        ("Corazón", "coxaxxn", False),
    ],
)
def test_f4_edit_budget_uses_the_length_of_the_plan_word(
    name: str,
    message: str,
    matched: bool,
) -> None:
    plan = {"name": name}
    assert (match_booking_plan(message, [plan]) is plan) is matched


@pytest.mark.parametrize(
    "message",
    [
        "ritual corazon y romance copas",
        "ritual corazon y romance copaz",
    ],
)
def test_f4_multiple_matches_are_ambiguous_even_with_an_exact_match(
    message: str,
    plans: list[dict[str, Any]],
) -> None:
    assert match_booking_plan(message, plans) is None


def test_f4_exact_name_does_not_override_another_tolerant_match() -> None:
    plans = [{"name": "Ritual del Corazón"}, {"name": "Ritual del CorazoX"}]
    assert match_booking_plan("Ritual del Corazón", plans) is None


@pytest.mark.parametrize("expression", ["visita", "visitar", "conocer el lugar", "ir a ver"])
def test_f4_visit_expressions_still_exclude_plan_matches(
    expression: str,
    plans: list[dict[str, Any]],
) -> None:
    assert match_booking_plan(f"quiero {expression} antes del ritual corazon", plans) is None


@pytest.mark.parametrize(
    "name,message",
    [
        ("Refugio para Dos", "refugio"),
        ("Refugio para Dos", "refugio doz"),
        ("Cinema y Amor", "cinema"),
        ("Ritual del Corazón", "ritual corazoncito"),
        ("Ritual del Corazón", ""),
        ("de la y", "de la y"),
    ],
)
def test_f4_missing_significant_words_and_empty_names_do_not_match(
    name: str,
    message: str,
) -> None:
    assert match_booking_plan(message, [{"name": name}]) is None


def test_f4_empty_catalog_does_not_match() -> None:
    assert match_booking_plan("ritual corazon", []) is None
