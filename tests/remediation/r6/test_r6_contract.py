"""Candidate branch coverage for the local pending-confirmation protocol."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.channel import inbound
from app.conversation.models import Conversation
from tests.remediation.r4.helpers import configure
from tests.remediation.r5.helpers import media_payload
from tests.remediation.r6.helpers import (
    actions,
    completed,
    entity,
    prepare,
    proposal,
    send,
    snapshot,
)
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio

BAD_PENDING = [
    None, {}, [], [1], 42, "", "legacy", {"type": "UNKNOWN"},
    {"resolved_intent": "DENY"}, {"resolved_intent": "CONFIRM"},
    {"resolved_intent": "DENY", "classification": proposal(confidence=0.65)},
    {"type": "OTHER", "classification": proposal(confidence=0.65)},
    {"classification": None}, {"classification": []}, {"classification": {"confidence": 0.65}},
    {"type": "FULL_NAME_CONFIRMATION"}, {"type": "FULL_NAME_CONFIRMATION", "full_name": None},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": ""},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": "   "},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": 42},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": ["Nombre"]},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": {"name": "Nombre"}},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": "Anterior", "classification": proposal()},
    {"type": "CLASSIFICATION_CONFIRMATION", "version": 999, "classification": proposal()},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": "A"},
    {"type": "FULL_NAME_CONFIRMATION", "full_name": "A" * 121},
]


@pytest.mark.parametrize("index", range(len(BAD_PENDING)))
async def test_non_authoritative_shapes_never_apply_or_crash(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    configure(monkeypatch)
    event = await prepare(db, body="sí")
    pending = deepcopy(BAD_PENDING[index])
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_confirmation = pending
        conversation.pending_action = "CLASSIFY_MESSAGE"
        conversation.last_question_code = "RESP-FALLBACK-004"
    first = await send(db, "sí", proposal("CONFIRM"), event_id=event)
    second = await send(db, "Necesito consultar el parqueadero",
                        proposal("GENERAL_INFORMATION", information_category="parqueadero"))
    evidence(request, legacy_fixture=pending, steps=[first, second], final=second["after"])
    completed(first)
    completed(second)
    for step in (first, second):
        assert actions(step["after"], "AI_CONFIRMATION_ACCEPTED") == 0
        assert actions(step["after"], "CUSTOMER_NAME_CONFIRMED") == 0
        assert step["after"]["customer"][0]["full_name"] == "Cliente Sintetico R6"
        assert not step["after"]["quote_request"] and not step["after"]["handoff"]
        assert not step["after"]["appointment"]
    assert first["after"]["conversation"][0]["last_question_code"] == "RESP-FALLBACK-004"
    assert second["after"]["conversation"][0]["last_question_code"] == "RESP-PARKING-001"


@pytest.mark.parametrize("valid_context", [True, False])
async def test_legacy_classification_requires_actual_confirmation_context(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, valid_context: bool
) -> None:
    configure(monkeypatch)
    event = await prepare(db, body="sí")
    stored = proposal(confidence=0.65)
    legacy = dict(classification=stored, original_intent="QUOTE_REQUEST",
                  original_confidence=0.65, entities={})
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_confirmation = legacy
        conversation.pending_action = "CLASSIFY_MESSAGE" if valid_context else None
        conversation.last_question_code = "RESP-FALLBACK-004" if valid_context else None
    first = await send(db, "sí", proposal("CONFIRM"), event_id=event)
    evidence(request, legacy_fixture=legacy, steps=[first], final=first["after"])
    completed(first)
    assert actions(first["after"], "AI_CONFIRMATION_ACCEPTED") == int(valid_context)
    assert actions(first["after"], "CONFIRMATION_UPLIFT") == int(valid_context)
    assert not first["after"]["handoff"]
    assert all(q["request_status"] == "DRAFT" for q in first["after"]["quote_request"])


@pytest.mark.parametrize("valid_context", [True, False])
async def test_legacy_name_is_contextual_and_single_use(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, valid_context: bool
) -> None:
    configure(monkeypatch)
    event = await prepare(db, name=None, body="sí")
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_confirmation = dict(type="FULL_NAME_CONFIRMATION",
                                                 full_name="Nombre Vigente")
        conversation.pending_action = "COLLECT_CUSTOMER_NAME" if valid_context else None
        conversation.last_question_code = "RESP-CUSTOMER-001" if valid_context else None
    first = await send(db, "sí", proposal(), event_id=event)
    last = await send(db, "sí", proposal(), expected_calls=0 if valid_context else 1)
    evidence(request, steps=[first, last], final=last["after"], legacy_fixture=True)
    completed(first)
    completed(last)
    assert actions(last["after"], "CUSTOMER_NAME_CONFIRMED") == int(valid_context)
    assert last["after"]["customer"][0]["full_name"] == (
        "Nombre Vigente" if valid_context else None)


@pytest.mark.parametrize("mode", ["deny", "correction_with_yes", "faq"])
async def test_natural_name_lifecycle(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configure(monkeypatch)
    body = "Mi nombre tal vez sea Nombre Anterior"
    event = await prepare(db, name=None, body=body)
    first = await send(db, body, proposal(entities=[entity(
        "full_name", "Nombre Anterior", needs_confirmation=True,
        quality_status="PENDING_CONFIRMATION")]), event_id=event)
    completed(first)
    if mode == "deny":
        middle = await send(db, "no", proposal("DENY"))
        last = await send(db, "sí", proposal())
        expected, confirmations = None, 0
    elif mode == "correction_with_yes":
        middle = await send(db, "sí, corrijo mi nombre a Nombre Corregido", proposal(entities=[
            entity("full_name", "Nombre Corregido", quality_status="CORRECTED")]))
        last = await send(db, "sí", proposal(), expected_calls=0)
        expected, confirmations = "Nombre Corregido", 0
    else:
        middle = await send(db, "¿Hay parqueadero?",
                            proposal("GENERAL_INFORMATION", information_category="parqueadero"))
        last = await send(db, "sí", proposal())
        expected, confirmations = "Nombre Anterior", 1
        assert middle["after"]["conversation"][0]["pending_confirmation"] == (
            first["after"]["conversation"][0]["pending_confirmation"])
        assert middle["after"]["conversation"][0]["pending_action"] == "COLLECT_CUSTOMER_NAME"
    evidence(request, steps=[first, middle, last], final=last["after"])
    completed(middle)
    completed(last)
    assert last["after"]["customer"][0]["full_name"] == expected
    assert actions(last["after"], "CUSTOMER_NAME_CONFIRMED") == confirmations
    assert last["after"]["event"][0]["guest_count"] == 40
    assert str(last["after"]["event"][0]["event_date"]) == "2027-02-20"
    assert last["after"]["lead"][0]["budget_data_status"] == "DECLINED"
    assert last["after"]["event_service_request"][0]["service_name"] == "VENUE"


@pytest.mark.parametrize("mode", ["deny", "correction", "faq", "changed_context"])
async def test_classification_lifecycle(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", proposal(confidence=0.65), event_id=event)
    completed(first)
    steps = [first]
    if mode == "faq":
        middle = await send(db, "¿Hay parqueadero?",
                            proposal("GENERAL_INFORMATION", information_category="parqueadero"))
        completed(middle)
        steps.append(middle)
    elif mode == "deny":
        middle = await send(db, "no", proposal("DENY"))
        completed(middle)
        steps.append(middle)
    elif mode == "correction":
        middle = await send(db, "sí, corrijo a cincuenta invitados", proposal(
            "MODIFY_EVENT_DATA", entities=[entity("guest_count", 50, quality_status="CORRECTED")]))
        completed(middle)
        steps.append(middle)
    else:
        async with db() as session, session.begin():
            conversation = await session.get(Conversation, 1)
            conversation.active_lead_id = None
            conversation.state = "BOT_ACTIVE"
    context = (await snapshot(db))["conversation"][0]
    last = await send(db, "sí", proposal("CONFIRM"),
                      expected_calls=0 if (context["pending_action"] or "").startswith("CONFIRM_")
                      else 1)
    steps.append(last)
    evidence(request, steps=steps, final=last["after"])
    completed(last)
    assert actions(last["after"], "AI_CONFIRMATION_ACCEPTED") == int(mode == "faq")
    if mode == "correction":
        assert last["after"]["event"][0]["guest_count"] == 50
    elif mode != "faq":
        assert not last["after"]["handoff"]
        assert actions(last["after"], "QUOTE_REQUEST_READY") == 0


@pytest.mark.parametrize("index", [0, 2, 7, 8, 10, 15])
async def test_r4_precedes_every_pending_family(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    configure(monkeypatch)
    body = "Quiero hablar con un asesor"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.pending_confirmation = deepcopy(BAD_PENDING[index])
    last = await send(db, body, event_id=event, expected_calls=0)
    evidence(request, steps=[last], final=last["after"])
    completed(last)
    assert len(last["after"]["handoff"]) == 1
    assert last["after"]["handoff"][0]["reason"] == "CUSTOMER_REQUEST"
    assert actions(last["after"], "AI_CONFIRMATION_ACCEPTED") == 0
    assert not last["after"]["quote_request"]


@pytest.mark.parametrize("state,enabled", [
    ("WAITING_FOR_HUMAN", True), ("HUMAN_ACTIVE", False), ("BOT_ACTIVE", False)])
@pytest.mark.parametrize("kind", ["text", "image"])
async def test_paused_turn_does_not_consume_or_clean_pending(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    state: str, enabled: bool, kind: str
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", proposal(confidence=0.65), event_id=event)
    completed(first)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state, conversation.bot_enabled = state, enabled
    before = await snapshot(db)
    if kind == "image":
        event = await inbound.store_webhook_event(
            media_payload('image', 'sí', 'r6.media'), db, None)
        last = await send(db, "sí", event_id=event, expected_calls=0)
    else:
        # R5 skips preliminary IA for media only; no new blanket text optimization in R6.
        last = await send(db, "sí", proposal("CONFIRM"))
    evidence(request, before=before, steps=[last], final=last["after"])
    completed(last)
    for key in (
        'pending_confirmation', 'pending_action', 'state', 'bot_enabled', 'active_lead_id'
    ):
        assert last["after"]["conversation"][0][key] == before["conversation"][0][key]
    for table in (
        'outbox', 'customer', 'lead', 'event', 'handoff', 'payment_evidence', 'quote_request'
    ):
        assert last["after"][table] == before[table]


@pytest.mark.parametrize("missing", ["action", "question"])
async def test_legacy_summary_without_confirmation_context_is_not_accepted(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", event_id=event)
    completed(first)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        if missing == "action":
            conversation.pending_action = None
        else:
            conversation.last_question_code = None
    last = await send(db, "sí", proposal())
    repeated = await send(db, "sí", proposal())
    completed(repeated)
    assert actions(repeated["after"], "QUOTE_REQUEST_READY") == 0
    evidence(request, steps=[first, last, repeated], final=repeated["after"],
             legacy_fixture="Summary context incomplete: " + missing)
    completed(last)
    assert actions(last["after"], "QUOTE_REQUEST_READY") == 0
    assert last["after"]["quote_request"][0]["request_status"] == "DRAFT"
    assert not last["after"]["handoff"]
    assert last["after"]["conversation"][0]["last_question_code"] == "RESP-FALLBACK-004"


@pytest.mark.parametrize("value", [42, [], {"name": "No coercion"}, "", "A", "A" * 121])
async def test_invalid_name_correction_does_not_replace_a_valid_proposal(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    configure(monkeypatch)
    body = "Mi nombre tal vez sea Nombre Vigente"
    event = await prepare(db, name=None, body=body)
    first = await send(db, body, proposal(entities=[entity(
        "full_name", "Nombre Vigente", quality_status="PENDING_CONFIRMATION",
        needs_confirmation=True)]), event_id=event)
    completed(first)
    last = await send(db, "Intento corregir el nombre", proposal(entities=[
        entity("full_name", value, quality_status="CORRECTED")]))
    evidence(request, steps=[first, last], final=last["after"])
    completed(last)
    assert last["after"]["customer"][0]["full_name"] is None
    assert last["after"]["conversation"][0]["pending_confirmation"] == (
        first["after"]["conversation"][0]["pending_confirmation"])
    assert actions(last["after"], "CUSTOMER_NAME_CAPTURED") == 0
    assert actions(last["after"], "PENDING_CONFIRMATION_INVALID_NAME") == 1


async def test_inferred_replacement_of_existing_name_blocks_summary_until_confirmed(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    from app.lead.models import Lead

    configure(monkeypatch)
    body = "Mi nombre tal vez sea Nombre Nuevo"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        lead = await session.get(Lead, conversation.active_lead_id)
        lead.budget_data_status = "PROVIDED"
        lead.estimated_budget = Decimal("8000000")
        lead.budget_range = "REFERENCE_RANGE"
    first = await send(db, body, proposal(entities=[entity(
        "full_name", "Nombre Nuevo", quality_status="PENDING_CONFIRMATION",
        needs_confirmation=True)]), event_id=event)
    completed(first)
    assert first["after"]["customer"][0]["full_name"] == "Cliente Sintetico R6"
    assert first["after"]["conversation"][0]["pending_action"] == "COLLECT_CUSTOMER_NAME"
    assert not first["after"]["quote_request"]
    last = await send(db, "sí", proposal())
    evidence(request, steps=[first, last], final=last["after"])
    completed(last)
    assert last["after"]["customer"][0]["full_name"] == "Nombre Nuevo"
    for table in ("lead", "event", "event_service_request"):
        assert last["after"][table] == first["after"][table]


async def test_affirmation_of_classification_precedes_fresh_faq_guess(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", proposal(confidence=0.65), event_id=event)
    last = await send(db, "sí", proposal("GENERAL_INFORMATION", information_category="parqueadero"))
    evidence(request, steps=[first, last], final=last["after"])
    completed(first)
    completed(last)
    assert actions(last["after"], "AI_CONFIRMATION_ACCEPTED") == 1
    assert actions(last["after"], "CONFIRMATION_UPLIFT") == 1
    assert last["after"]["conversation"][0]["last_question_code"] == "RESP-QUOTE-002"
