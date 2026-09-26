"""Frozen H17 multiturn criteria, first executed against unchanged R5 product."""
from __future__ import annotations

from typing import Any

import pytest

from tests.remediation.r4.helpers import configure
from tests.remediation.r6.helpers import (
    actions,
    completed,
    entity,
    human_return,
    prepare,
    proposal,
    send,
)
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("mode", ["deny", "return", "deny_correction"])
async def test_summary_resolution_followed_by_affirmation(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", event_id=event)
    completed(first)
    assert first["after"]["conversation"][0]["state"] == "QUOTE_REQUEST_READY"
    assert first["after"]["conversation"][0]["pending_action"] == "CONFIRM_QUOTE_REQUEST"
    assert first["after"]["conversation"][0]["last_question_code"] == "RESP-QUOTE-002"
    second = await send(db, "sí" if mode == "return" else "no", expected_calls=0)
    completed(second)
    steps = [first, second]
    if mode == "return":
        steps.append(await human_return(db))
    if mode == "deny_correction":
        corrected = await send(db, "Corrijo la cantidad a cincuenta invitados",
                               proposal("MODIFY_EVENT_DATA", entities=[
                                   entity("guest_count", 50, quality_status="CORRECTED")]))
        completed(corrected)
        assert corrected["after"]["event"][0]["guest_count"] == 50
        steps.append(corrected)
    last = await send(db, "sí", proposal("CONFIRM"),
                      expected_calls=0 if mode == "deny_correction" else 1)
    steps.append(last)
    evidence(request, steps=steps, final=last["after"])
    completed(last)
    final = last["after"]
    assert len(final["quote_request"]) == 1
    assert actions(final, "AI_CONFIRMATION_ACCEPTED") == 0
    if mode == "deny":
        assert final["quote_request"][0]["request_status"] == "DRAFT"
        assert not final["handoff"]
        assert actions(final, "QUOTE_REQUEST_READY") == 0
        assert final["conversation"][0]["last_question_code"] == "RESP-FALLBACK-004"
    elif mode == "return":
        assert actions(final, "QUOTE_REQUEST_READY") == 1
        assert len(final["handoff"]) == 1 and final["handoff"][0]["status"] == "RETURNED"
        assert final["conversation"][0]["last_question_code"] == "RESP-FALLBACK-004"
    else:
        assert actions(final, "QUOTE_REQUEST_READY") == 1
        assert final["event"][0]["guest_count"] == 50


@pytest.mark.parametrize("corrected", [False, True])
async def test_current_name_only_can_be_confirmed(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, corrected: bool
) -> None:
    configure(monkeypatch)
    event = await prepare(db, name=None, body="Mi nombre tal vez sea Sintetico Uno")
    first = await send(db, "Mi nombre tal vez sea Sintetico Uno", proposal(entities=[
        entity("full_name", "Sintetico Uno", quality_status="PENDING_CONFIRMATION",
               needs_confirmation=True)]), event_id=event)
    completed(first)
    assert first["after"]["conversation"][0]["pending_confirmation"]["full_name"] == "Sintetico Uno"
    assert first["after"]["conversation"][0]["last_question_code"] == "RESP-CUSTOMER-001"
    steps = [first]
    if corrected:
        correction = await send(db, "Corrijo mi nombre a Sintetico Dos", proposal(entities=[
            entity("full_name", "Sintetico Dos", quality_status="CORRECTED")]))
        completed(correction)
        assert correction["after"]["customer"][0]["full_name"] == "Sintetico Dos"
        steps.append(correction)
    # BASE still asks for the old name; a fixed candidate may have emitted the new summary.
    # Both use real channel dispatch: no stub classifier or forced function invocation.
    context = steps[-1]["after"]["conversation"][0]
    deterministic = (context["pending_action"] or "").startswith("CONFIRM_")
    last = await send(db, "sí", proposal(), expected_calls=0 if deterministic else 1)
    steps.append(last)
    evidence(request, steps=steps, final=last["after"])
    completed(last)
    assert last["after"]["customer"][0]["full_name"] == (
        "Sintetico Dos" if corrected else "Sintetico Uno")
    assert actions(last["after"], "CUSTOMER_NAME_CONFIRMED") == (0 if corrected else 1)


async def test_uncertain_classification_confirmation_keeps_uplift(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", proposal(confidence=0.65), event_id=event)
    completed(first)
    assert first["after"]["conversation"][0]["pending_action"] == "CLASSIFY_MESSAGE"
    last = await send(db, "sí", proposal("CONFIRM"))
    evidence(request, steps=[first, last], final=last["after"])
    completed(last)
    assert actions(last["after"], "AI_CONFIRMATION_ACCEPTED") == 1
    assert actions(last["after"], "CONFIRMATION_UPLIFT") == 1
    assert last["after"]["conversation"][0]["pending_confirmation"] is None
    assert last["after"]["conversation"][0]["state"] == "QUOTE_REQUEST_READY"


async def test_explicit_human_request_precedes_pending_confirmation(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    first = await send(db, "Quiero cotizar mi evento", proposal(confidence=0.65), event_id=event)
    last = await send(db, "Quiero hablar con un asesor", expected_calls=0)
    evidence(request, steps=[first, last], final=last["after"])
    completed(last)
    assert len(last["after"]["handoff"]) == 1
    assert last["after"]["handoff"][0]["reason"] == "CUSTOMER_REQUEST"
    assert actions(last["after"], "AI_CONFIRMATION_ACCEPTED") == 0
    assert last["after"]["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
