"""Semantic contracts through the real provider/parser, R2 and PostgreSQL."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.ai.schemas import ExtractedEntity, IntentClassification
from app.conversation.entity_validation import InvalidEntity, validate_entities, validate_entity
from app.conversation.models import Conversation
from app.conversation.pending_confirmation import proposal_context
from app.lead.models import Lead
from tests.remediation.r7.helpers import (
    actions, completed, configured, entity, prepare, proposal, send,
)
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio

INVALID = [
    ("name_digits", "full_name", "12345"),
    ("name_object", "full_name", {"name":"Cliente"}),
    ("name_emoji", "full_name", "😀😀"),
    ("name_null", "full_name", None),
    ("name_long", "full_name", "A" * 121),
    ("count_bool", "guest_count", True),
    ("count_zero", "guest_count", 0),
    ("count_fraction", "guest_count", 2.5),
    ("count_overflow", "guest_count", 2147483648),
    ("count_nested", "guest_count", {}),
    ("count_null", "guest_count", None),
    ("count_nan", "guest_count", float("nan")),
    ("count_inf", "guest_count", float("inf")),
    ("range_bool", "guest_count_range", {"min":True,"max":50}),
    ("range_fraction", "guest_count_range", {"min":4.2,"max":50}),
    ("range_extra", "guest_count_range", {"min":4,"max":50,"extra":1}),
    ("date_month", "event_date", {"event_month":"2027-13","event_date_type":"APPROXIMATE"}),
    ("date_kind", "event_date", {"event_date":"2027-02-20","event_date_type":[]}),
    (
        "date_conflict", "event_date",
        {"event_date":"2027-02-20","event_month":"2027-02","event_date_type":"EXACT"},
    ),
    ("date_past", "event_date", {"event_date":"2025-02-20","event_date_type":"EXACT"}),
    ("date_list", "event_date", []),
    ("date_unknown_key", "event_date", {"event_date_type":"UNKNOWN","surprise":True}),
    ("budget_bool", "estimated_budget", True),
    ("budget_negative", "estimated_budget", -5),
    ("budget_zero", "estimated_budget", 0),
    ("budget_overflow", "estimated_budget", "10000000000"),
    ("budget_precision", "estimated_budget", "5000.001"),
    ("budget_nan", "estimated_budget", float("nan")),
    ("budget_inf", "estimated_budget", float("inf")),
    ("budget_object", "estimated_budget", {}),
    ("budget_null", "estimated_budget", None),
    ("budget_currency", "estimated_budget", "25 USD"),
    ("decline_truthy", "budget_declined", "True"),
    ("decline_one", "budget_declined", 1),
    ("decline_null", "budget_declined", None),
    ("services_nested", "requested_services", [[{}]]),
    ("services_status", "requested_services", [{"service_code":"FOOD","status":"REMOVED"}]),
    ("services_bool", "requested_services", [True]),
    ("type_object", "event_type", {"type":"BIRTHDAY"}),
    ("text_object", "special_requests", {}),
    ("text_empty", "special_requests", ""),
    ("text_nul", "special_requests", "privado\u0000"),
]
VALID = [
    ("name", "full_name", "  María   del Río  ", "María del Río"),
    ("count_text", "guest_count", "0045", 45),
    ("count_float", "guest_count", 45, 45),
    ("count_max", "guest_count", 2147483647, 2147483647),
    ("range", "guest_count_range", {"min":"35","max":45}, [35,45]),
    (
        "date_exact", "event_date",
        {"event_date":"2027-03-12","event_date_type":"EXACT"}, "2027-03-12",
    ),
    (
        "date_month", "event_date",
        {"event_month":"2027-03","event_date_type":"APPROXIMATE"}, "2027-03",
    ),
    ("date_unknown", "event_date", {"event_date_type":"UNKNOWN"}, "UNKNOWN"),
    ("date_flexible", "event_date", {"event_date_type":"FLEXIBLE"}, "FLEXIBLE"),
    ("budget_text", "estimated_budget", "4500000", "4500000"),
    ("budget_decimal", "estimated_budget", "4500000.25", "4500000.25"),
    ("budget_max", "estimated_budget", "9999999999.99", "9999999999.99"),
    ("budget_cop", "estimated_budget", "4.500.000 COP", "4500000"),
    ("budget_millions", "estimated_budget", "4 millones y medio", "4500000"),
    ("budget_palos", "estimated_budget", "4 palos", "4000000"),
    ("decline_false", "budget_declined", False, False),
    ("decline_true", "budget_declined", True, True),
    ("services_alias", "requested_services", ["comida"], "FOOD"),
    (
        "services_object", "requested_services",
        [{"service_code":"FOOD","status":"REQUESTED"}], "FOOD",
    ),
    ("type_alias", "event_type", "cumpleaños", "BIRTHDAY"),
    ("text", "special_requests", "Necesito acceso sin escalones", "Necesito acceso sin escalones"),
]
QUESTION = {
    "full_name": "RESP-CUSTOMER-001", "guest_count": "RESP-EVENT-DATA-004",
    "guest_count_range": "RESP-EVENT-DATA-004", "event_date": "RESP-EVENT-DATA-001",
    "estimated_budget": "RESP-BUDGET-001", "budget_declined": "RESP-BUDGET-001",
    "requested_services": "RESP-EVENT-DATA-006", "event_type": "RESP-EVENT-DATA-013",
    "special_requests": "RESP-FALLBACK-004",
}


def field_value(rows: dict[str, Any], name: str) -> Any:
    event = rows["event"][0]
    if name == "full_name":
        return rows["customer"][0]["full_name"]
    if name in {"estimated_budget", "budget_declined"}:
        lead = rows["lead"][0]
        return lead["estimated_budget"], lead["budget_data_status"], lead["budget_range"]
    if name == "requested_services":
        return rows["event_service_request"]
    if name == "guest_count_range":
        return event["guest_count"], event["guest_count_min"], event["guest_count_max"]
    if name == "event_date":
        return tuple(event[key] for key in (
            "event_date", "event_month", "event_date_type", "event_date_raw"))
    return event[name]


@pytest.mark.parametrize("case,name,value", INVALID, ids=[c[0] for c in INVALID])
async def test_invalid_real_turn_keeps_previous_and_accepts_independent_field(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    case: str, name: str, value: Any,
) -> None:
    configured(monkeypatch)
    body = "Corrijo datos del evento para marzo de 2027"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        lead = await session.get(Lead, conversation.active_lead_id)
        lead.budget_data_status = "PROVIDED"
        lead.estimated_budget = Decimal("7000000")
        lead.budget_range = "REFERENCE_RANGE"
    independent = "guest_count" if name == "special_requests" else "special_requests"
    good = entity(independent, 45 if independent == "guest_count" else "Acceso amplio")
    bad = entity(name, value, raw_value="" if value is None else body,
                 quality_status="CORRECTED")
    step = await send(db, body, proposal(entities=[bad, good]), event_id=event)
    evidence(request, case=case, step=step, final=step["after"])
    completed(step)
    assert field_value(step["after"], name) == field_value(step["before"], name)
    assert field_value(step["after"], independent) == (
        45 if independent == "guest_count" else "Acceso amplio")
    assert step["after"]["conversation"][0]["last_question_code"] == QUESTION[name]
    assert not step["after"]["quote_request"] and not step["after"]["handoff"]
    diagnostics = [a for a in step["after"]["audit_event"] if a["action"] in {
        "ENTITY_INVALID", "PENDING_CONFIRMATION_INVALID_NAME"}]
    assert diagnostics
    assert set(diagnostics[-1]["new_value"]) == {"entity", "code", "value_type"}
    assert diagnostics[-1]["new_value"]["entity"] == name
    # A generic yes cannot re-present the preserved field as the rejected correction.
    if name not in {"requested_services", "special_requests"}:
        next_turn = await send(db, "si", proposal())
        completed(next_turn)
        assert not next_turn["after"]["quote_request"]
        assert field_value(next_turn["after"], name) == field_value(step["before"], name)


@pytest.mark.parametrize("case,name,value,expected", VALID, ids=[c[0] for c in VALID])
async def test_valid_representation_persists(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    case: str, name: str, value: Any, expected: Any,
) -> None:
    configured(monkeypatch)
    body = "Confirmo los datos para marzo de 2027"
    event = await prepare(db, body=body)
    step = await send(db, body, proposal(entities=[
        entity(name, value, raw_value=body, quality_status="CORRECTED")]), event_id=event)
    evidence(request, case=case, step=step, final=step["after"])
    completed(step)
    rows = step["after"]
    if name == "estimated_budget":
        assert rows["lead"][0]["estimated_budget"] == Decimal(expected)
        assert rows["lead"][0]["budget_data_status"] == "PROVIDED"
    elif name == "budget_declined":
        assert rows["lead"][0]["budget_data_status"] == "DECLINED"
        assert actions(rows, "BUDGET_DECLINED") == int(expected)
    elif name == "event_date":
        event_row = rows["event"][0]
        actual = event_row["event_date"]
        assert (actual.isoformat() if actual else (
            event_row["event_month"] or event_row["event_date_type"])) == expected
    elif name == "guest_count_range":
        assert field_value(rows, name) == (None, *expected)
    elif name == "requested_services":
        assert expected in [r["service_name"] for r in rows["event_service_request"]]
    else:
        assert field_value(rows, name) == expected


@pytest.mark.parametrize(
    "mode", ["same", "different", "invalid_legacy", "unknown", "range", "budget"],
)
async def test_dual_representations_and_dependent_groups(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    configured(monkeypatch)
    body = "Corrijo datos de la cotizacion"
    event = await prepare(db, body=body)
    items = [entity("guest_count", 45, quality_status="CORRECTED")]
    legacy = {"guest_count": 45 if mode == "same" else 50}
    if mode == "invalid_legacy":
        legacy = {"guest_count": {"raw": "muchos", "normalized": -5}}
    elif mode == "unknown":
        legacy = {"unregistered_legacy": "dato"}
    elif mode == "range":
        legacy = {"guest_count_range": {"min": 35, "max": 50}}
    elif mode == "budget":
        items = [entity("estimated_budget", "5000000"), entity("budget_declined", True)]
        legacy = {}
    step = await send(db, body, proposal(entities=items) | {"entities": legacy}, event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["event"][0]["guest_count"] == (
        45 if mode in {"same", "unknown"} else 40)
    if mode != "same":
        assert actions(step["after"], "ENTITY_INVALID") >= 1
        assert not step["after"]["quote_request"]
    if mode == "budget":
        assert step["after"]["lead"] == step["before"]["lead"]


@pytest.mark.parametrize("source", ["fresh", "legacy_pending", "valid_pending"])
async def test_semantics_rechecked_for_r6_proposals(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    configured(monkeypatch)
    body = "Quiero cambiar la cantidad de invitados"
    event = await prepare(db, body=body if source == "fresh" else "si")
    value = 45 if source == "valid_pending" else -5
    candidate = proposal(confidence=0.65, entities=[entity("guest_count", value)])
    if source != "fresh":
        async with db() as session, session.begin():
            conversation = await session.get(Conversation, 1)
            conversation.pending_action = "CLASSIFY_MESSAGE"
            conversation.last_question_code = "RESP-FALLBACK-004"
            conversation.pending_confirmation = {
                "type": "CLASSIFICATION_CONFIRMATION", "version": 1,
                "context": proposal_context(conversation.state, conversation.active_lead_id),
                "classification": candidate,
            }
    step = await send(db, body if source == "fresh" else "si",
                      candidate if source == "fresh" else proposal(), event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["event"][0]["guest_count"] == (
        45 if source == "valid_pending" else 40)
    assert step["after"]["conversation"][0]["pending_confirmation"] is None
    if source != "valid_pending":
        assert actions(step["after"], "ENTITY_INVALID") == 1
        assert not step["after"]["quote_request"]


@pytest.mark.parametrize("factory", ["copy", "construct", "legacy"])
async def test_bypass_envelopes_still_have_pure_semantic_gate(factory: str) -> None:
    item = ExtractedEntity.model_validate(entity("guest_count", 45))
    if factory == "copy":
        item = item.model_copy(update={"normalized_value": -5})
    elif factory == "construct":
        item = ExtractedEntity.model_construct(**entity("guest_count", True))
    else:
        classification = IntentClassification.model_validate(proposal() | {
            "entities": {"guest_count": {"normalized": -5, "raw": "menos cinco"}}})
        batch = validate_entities(classification, date(2026, 9, 9))
        assert not batch.accepted and batch.rejected
        return
    with pytest.raises(InvalidEntity):
        validate_entity(item, date(2026, 9, 9))
