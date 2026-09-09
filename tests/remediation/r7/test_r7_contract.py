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
    actions,
    completed,
    configured,
    entity,
    prepare,
    proposal,
    send,
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
    ("count_float", "guest_count", 45.0, 45),
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
        next_turn = (
            await type_followup(db) if name == "event_type" else await send(db, "si", proposal())
        )
        completed(next_turn)
        assert not next_turn["after"]["quote_request"]
        assert field_value(next_turn["after"], name) == field_value(step["before"], name)
        evidence(request, case=case, steps=[step, next_turn], final=next_turn["after"])


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
        assert field_value(step["after"], "estimated_budget") == (
            field_value(step["before"], "estimated_budget"))


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


async def test_telemetry_sql_failure_keeps_controlled_rejection(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import structlog.testing
    from sqlalchemy import text

    configured(monkeypatch)
    body = "Corrijo invitados"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        await session.execute(text(
            "CREATE FUNCTION r7_reject_ai() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'R7_PRIVATE_TELEMETRY'; END $$"))
        await session.execute(text(
            "CREATE TRIGGER r7_reject_ai BEFORE INSERT ON ai_execution "
            "FOR EACH ROW EXECUTE FUNCTION r7_reject_ai()"))
    try:
        with structlog.testing.capture_logs() as logs:
            step = await send(db, body, proposal(entities=[entity("guest_count", -5)]),
                              event_id=event)
        evidence(request, step=step, final=step["after"], logs=logs)
        completed(step)
        assert not step["after"]["ai_execution"]
        assert actions(step["after"], "ENTITY_INVALID") == 1
        assert step["after"]["event"][0]["guest_count"] == 40
        warnings = [r for r in logs if r.get("event") == "ai_execution_persist_failed"]
        assert len(warnings) == 1 and warnings[0]["error_type"] == "DBAPIError"
        assert "R7_PRIVATE_TELEMETRY" not in json.dumps(logs, default=str)
    finally:
        async with db() as session, session.begin():
            await session.execute(text("DROP TRIGGER r7_reject_ai ON ai_execution"))
            await session.execute(text("DROP FUNCTION r7_reject_ai()"))


@pytest.mark.parametrize("mode", ["invalid", "inferred"])
async def test_visit_name_semantics_preserve_prior_value_until_resolved(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    configured(monkeypatch)
    body = "Corrijo mi nombre"
    event = await prepare(db, body=body)
    draft = dict(visit_date="2027-02-20", visit_time="09:00", attendee_count=2,
                 visit_reason="Conocer el lugar", return_to="VISIT_CONFIRMATION_SUMMARY")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state = "WAITING_FOR_APPOINTMENT_SELECTION"
        conversation.pending_action = "COLLECT_CUSTOMER_NAME"
        conversation.last_question_code = "RESP-CUSTOMER-001"
        conversation.visit_draft = draft
    step = await send(db, body, proposal("SCHEDULE_VISIT", entities=[entity(
        "full_name", "12345" if mode == "invalid" else "Nombre Propuesto",
        quality_status="CORRECTED" if mode == "invalid" else "INFERRED")]), event_id=event)
    completed(step)
    assert step["after"]["customer"] == step["before"]["customer"]
    assert step["after"]["conversation"][0]["visit_draft"] == draft
    assert step["after"]["conversation"][0]["last_question_code"] == "RESP-CUSTOMER-001"
    follow = await send(db, "si", proposal("SCHEDULE_VISIT"))
    completed(follow)
    evidence(request, steps=[step, follow], final=follow["after"])
    assert not follow["after"]["appointment"]
    if mode == "invalid":
        assert follow["after"]["customer"] == step["before"]["customer"]
        assert follow["after"]["conversation"][0]["visit_draft"] == draft
    else:
        assert follow["after"]["customer"][0]["full_name"] == "Nombre Propuesto"


async def test_r4_explicit_request_keeps_priority(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured(monkeypatch)
    body = "Quiero hablar con un asesor"
    event = await prepare(db, body=body)
    step = await send(db, body, event_id=event, expected_calls=0)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["event"] == step["before"]["event"]
    assert step["after"]["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
    assert not step["calls"]


async def test_auxiliary_services_use_existing_codes_and_parser(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import respx

    from app.channel import inbound
    from tests.remediation.r3.helpers import MAIN, SERVICES, Provider
    from tests.remediation.r7.helpers import snapshot

    configured(monkeypatch)
    body = "Necesito organizar algo especial"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_action = "COLLECT_SERVICES"
        conversation.last_question_code = "RESP-EVENT-DATA-006"
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {
            MAIN: [proposal(entities=[entity("guest_count", -5)])],
            SERVICES: [{"service_codes": ["FOOD"]}],
        })
        counts = await inbound.process_webhook_event(event, db)
    provider.exhausted()
    final = await snapshot(db)
    evidence(request, final=final, counts=counts, calls=provider.calls)
    assert all(j["status"] == "COMPLETED" for j in final["inbox_job"])
    assert final["event"][0]["guest_count"] == 40
    assert "FOOD" in [row["service_name"] for row in final["event_service_request"]]
    assert provider.calls == {MAIN: 1, SERVICES: 1}


@pytest.mark.parametrize("raw,expected", [
    ("4.5", Decimal("4500000")), ("cuatro millones y medio", Decimal("4500000")),
    ("Tengo 5000.25 COP", Decimal("5000.25")),
])
async def test_approved_raw_budget_parser_preserves_exact_precision(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    raw: str, expected: Decimal,
) -> None:
    configured(monkeypatch)
    event = await prepare(db, body=raw)
    step = await send(db, raw, proposal(entities=[entity(
        "estimated_budget", None, raw_value=raw)]), event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["lead"][0]["estimated_budget"] == expected


@pytest.mark.parametrize("quality", ["INVALID", "INFERRED", "PENDING_CONFIRMATION"])
@pytest.mark.parametrize("name,value", [
    ("full_name", "Nombre Propuesto"), ("event_type", "BIRTHDAY"),
    ("guest_count", 45), ("guest_count_range", {"min": 35, "max": 45}),
    ("event_date", {"event_date_type": "UNKNOWN"}), ("estimated_budget", "5000000"),
    ("budget_declined", True), ("requested_services", ["FOOD"]),
    ("special_requests", "Acceso amplio"),
])
async def test_quality_is_not_semantic_authorization(
    name: str, value: Any, quality: str,
) -> None:
    classification = IntentClassification.model_validate(proposal(entities=[
        entity(name, value, quality_status=quality)]))
    batch = validate_entities(classification, date(2026, 9, 9))
    if name == "full_name" and quality != "INVALID":
        assert batch.accepted and not batch.rejected
        assert batch.accepted[0].entity.quality_status == quality
    else:
        assert not batch.accepted and batch.rejected


async def test_absence_and_partial_date_keep_their_meaning() -> None:
    batch = validate_entities(IntentClassification.model_validate(proposal()), date(2026, 9, 9))
    assert not batch.accepted and not batch.rejected
    for raw, normalized, expected in [
        ("el 15", {"event_date": "2027-01-15", "event_date_type": "EXACT"}, "2026-09-15"),
        ("en marzo", {"event_month": "2027-03", "event_date_type": "APPROXIMATE"}, "2027-03"),
    ]:
        item = ExtractedEntity.model_validate(entity("event_date", normalized, raw_value=raw))
        value = validate_entity(item, date(2026, 9, 9)).value
        assert (value.event_date.isoformat() if value.event_date else value.event_month) == expected


@pytest.mark.parametrize("name,value", [
    ("full_name", "Nombre Legacy"), ("guest_count", "45"),
    ("event_date", {"event_date": "2027-02-20", "event_date_type": "EXACT"}),
])
async def test_valid_legacy_wrapper_crosses_real_turn(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    name: str, value: Any,
) -> None:
    configured(monkeypatch)
    body = "Datos para febrero de 2027"
    event = await prepare(db, body=body)
    response = proposal() | {"entities": {
        name: {"raw": body, "normalized": value, "quality_status": "CORRECTED"}}}
    step = await send(db, body, response, event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert actions(step["after"], "ENTITY_INVALID") == 0
    if name == "full_name":
        assert step["after"]["customer"][0]["full_name"] == value
    elif name == "guest_count":
        assert step["after"]["event"][0]["guest_count"] == 45
    else:
        assert step["after"]["event"][0]["event_date"] == date(2027, 2, 20)


@pytest.mark.parametrize("state", ["COLLECTING_EVENT_DATA", "WAITING_FOR_APPOINTMENT_SELECTION"])
async def test_invalid_legacy_name_proposal_with_previous_name_still_asks(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, state: str,
) -> None:
    configured(monkeypatch)
    event = await prepare(db, body="si")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state = state
        conversation.pending_action = "COLLECT_CUSTOMER_NAME"
        conversation.last_question_code = "RESP-CUSTOMER-001"
        conversation.pending_confirmation = {
            "type": "FULL_NAME_CONFIRMATION", "full_name": "12345",
        }
        if state == "WAITING_FOR_APPOINTMENT_SELECTION":
            conversation.visit_draft = dict(
                visit_date="2027-02-20", visit_time="09:00", attendee_count=2,
                visit_reason="Conocer el lugar", return_to="VISIT_CONFIRMATION_SUMMARY")
    step = await send(db, "si", proposal(
        "SCHEDULE_VISIT" if state == "WAITING_FOR_APPOINTMENT_SELECTION" else "QUOTE_REQUEST"),
        event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["customer"] == step["before"]["customer"]
    assert not step["after"]["quote_request"] and not step["after"]["appointment"]
    assert step["after"]["conversation"][0]["last_question_code"] == "RESP-CUSTOMER-001"


@pytest.mark.parametrize("followup", ["yes", "false"])
async def test_rejected_budget_correction_does_not_reuse_previous_decline(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, followup: str,
) -> None:
    configured(monkeypatch)
    body = "Corrijo mi presupuesto"
    event = await prepare(db, body=body)
    first = await send(db, body, proposal(entities=[
        entity("estimated_budget", -5, quality_status="CORRECTED")]), event_id=event)
    completed(first)
    last = await send(db, "si" if followup == "yes" else "Todavia estoy pensando",
                      proposal(entities=[] if followup == "yes" else [
                          entity("budget_declined", False)]))
    evidence(request, steps=[first, last], final=last["after"])
    completed(last)
    assert last["after"]["conversation"][0]["last_question_code"] == "RESP-BUDGET-001"
    assert not last["after"]["quote_request"]
    assert actions(last["after"], "BUDGET_DECLINED") == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
async def test_uncertain_nonfinite_value_is_not_stored_as_pending(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, value: float,
) -> None:
    configured(monkeypatch)
    body = "Tengo un presupuesto"
    event = await prepare(db, body=body)
    step = await send(db, body, proposal(confidence=0.65, entities=[
        entity("estimated_budget", value)]), event_id=event)
    evidence(request, step=step, final=step["after"])
    completed(step)
    assert step["after"]["conversation"][0]["pending_confirmation"] is None
    assert step["after"]["conversation"][0]["last_question_code"] == "RESP-FALLBACK-004"
    assert actions(step["after"], "ENTITY_INVALID") == 1


@pytest.mark.parametrize("name,value", [
    ("full_name", {"name": "No convertir"}), ("event_type", {"type": "BIRTHDAY"}),
    ("guest_count", True), ("guest_count_range", {"min": 50, "max": 30}),
    ("event_date", {"event_date_type": "EXACT", "event_date": "2027-02-31"}),
    ("estimated_budget", float("inf")), ("budget_declined", "si"),
    ("requested_services", [{"name": "FOOD"}]), ("special_requests", ["No convertir"]),
])
async def test_direct_entity_consumer_revalidates_constructed_values(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    name: str, value: Any,
) -> None:
    from app.customer.models import Customer
    from app.orchestrator import service
    from tests.remediation.r7.helpers import snapshot

    configured(monkeypatch)
    await prepare(db)
    before = await snapshot(db)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        customer = await session.get(Customer, conversation.customer_id)
        lead = await service.active_lead(session, conversation)
        event = await service.active_event(session, lead)
        item = ExtractedEntity.model_construct(**entity(
            name, value, raw_value="Dato para 2027", quality_status="CORRECTED"))
        await service.apply_extracted_entities(
            session, conversation, customer, lead, event, [item], None)
    final = await snapshot(db)
    evidence(request, before=before, final=final, boundary="Direct consumer, not provider parser")
    for table in ("customer", "event", "lead", "event_service_request", "outbox"):
        assert final[table] == before[table]
    assert (
        actions(final, "ENTITY_INVALID")
        + actions(final, "PENDING_CONFIRMATION_INVALID_NAME")
    ) == 1


async def test_capture_resumption_keeps_rejected_field_unresolved(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select

    from app.channel.models import Message
    from app.config.settings import get_settings
    from app.customer.models import Customer
    from app.orchestrator import service
    from tests.remediation.r7.helpers import snapshot

    configured(monkeypatch)
    body = "Corrijo invitados"
    event_id = await prepare(db, body=body)
    first = await send(db, body, proposal(entities=[
        entity("guest_count", -5, quality_status="CORRECTED")]), event_id=event_id)
    completed(first)
    # Synthetic completed visit context; exercise only its real capture-resume consumer.
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state = "APPOINTMENT_CONFIRMED"
        conversation.visit_draft = {"resume": {"state": "COLLECTING_EVENT_DATA"}}
        customer = await session.get(Customer, conversation.customer_id)
        message = await session.scalar(select(Message).order_by(Message.id).limit(1))
        await service.clear_visit_draft_and_resume_capture(
            session, db, service.OrchestrationInput(conversation, customer, message, body))
    final = await snapshot(db)
    evidence(request, first=first, final=final, settings_mode=get_settings().calendar_adapter)
    assert final["event"] == first["after"]["event"]
    assert final["conversation"][0]["pending_action"] == "COLLECT_GUEST_COUNT"
    assert final["conversation"][0]["last_question_code"] == "RESP-EVENT-DATA-004"
    assert not final["quote_request"]


async def type_followup(db: Any) -> dict[str, Any]:
    import respx

    from app.channel import inbound
    from tests.remediation.r3.helpers import EXTRACT, MAIN, Provider
    from tests.remediation.r4.helpers import message_payload
    from tests.remediation.r7.helpers import snapshot

    before = await snapshot(db)
    event = await inbound.store_webhook_event(message_payload("r7.type-followup", "si"), db, None)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {
            MAIN: [proposal()], EXTRACT: [{"event_type": "UNSUPPORTED_SYNTHETIC"}],
        })
        counts = await inbound.process_webhook_event(event, db)
    provider.exhausted()
    assert provider.calls == {MAIN: 1, EXTRACT: 1}
    return dict(before=before, after=await snapshot(db), counts=counts,
                event_id=event, calls=dict(provider.calls), input="si")

