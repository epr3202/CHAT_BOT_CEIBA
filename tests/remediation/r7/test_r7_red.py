"""Frozen after a valid BASE RED: real parser, inbox and PostgreSQL effects."""
from __future__ import annotations

from typing import Any

import pytest

from app.conversation.models import Conversation
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
    ("guest_count", -5, "Corrijo a menos cinco personas", "RESP-EVENT-DATA-004"),
    ("guest_count", "many", "Corrijo a muchas personas", "RESP-EVENT-DATA-004"),
    ("guest_count_range", {"min": 30}, "Entre treinta y otra cantidad", "RESP-EVENT-DATA-004"),
    ("guest_count_range", {"min": 80, "max": 30}, "Entre ochenta y treinta",
     "RESP-EVENT-DATA-004"),
    ("event_date", {"event_date": "2027-02-31", "event_date_type": "EXACT"},
     "31 de febrero de 2027", "RESP-EVENT-DATA-001"),
    ("event_date", {"event_date": "2027-02-20"}, "20 de febrero de 2027",
     "RESP-EVENT-DATA-001"),
    ("legacy_unknown", "dato sintetico", "Corrijo un dato", "RESP-FALLBACK-004"),
]


@pytest.mark.parametrize("index", range(len(INVALID)))
async def test_invalid_entity_has_controlled_turn_without_overwriting(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    configured(monkeypatch)
    name, value, body, question = INVALID[index]
    event = await prepare(db, body=body)
    if name == "legacy_unknown":
        response = proposal() | {"entities": {"legacy_unknown": value}}
    else:
        response = proposal(entities=[entity(name, value, raw_value=body,
                                            quality_status="CORRECTED")])
    first = await send(db, body, response, event_id=event)
    evidence(request, steps=[first], final=first["after"])
    completed(first)
    assert first["after"]["event"] == first["before"]["event"]
    assert first["after"]["customer"] == first["before"]["customer"]
    assert not first["after"]["quote_request"] and not first["after"]["handoff"]
    assert first["after"]["conversation"][0]["last_question_code"] == question
    assert actions(first["after"], "GUEST_COUNT_CORRECTED") == 0
    assert actions(first["after"], "EVENT_DATE_CORRECTED") == 0
    assert len(first["after"]["outbox"]) > len(first["before"]["outbox"])
    last = await send(db, "Corrijo a cuarenta y cinco personas",
                      proposal(entities=[entity("guest_count", 45, quality_status="CORRECTED")]))
    completed(last)
    assert last["after"]["event"][0]["guest_count"] == 45
    evidence(request, steps=[first, last], final=last["after"])


@pytest.mark.parametrize("kind", ["count", "range", "date", "discard"])
async def test_valid_or_existing_discard_control(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    configured(monkeypatch)
    body = "20 de febrero de 2027"
    event = await prepare(db, body=body)
    item = {
        "count": entity("guest_count", 45),
        "range": entity("guest_count_range", {"min": 35, "max": 45}),
        "date": entity("event_date", {"event_date": "2027-02-20", "event_date_type": "EXACT"},
                       raw_value=body),
        "discard": entity("event_type", "UNSUPPORTED_SYNTHETIC"),
    }[kind]
    step = await send(db, body, proposal(entities=[item]), event_id=event)
    evidence(request, steps=[step], final=step["after"])
    completed(step)
    row = step["after"]["event"][0]
    if kind == "count":
        assert row["guest_count"] == 45
    elif kind == "range":
        assert row["guest_count"] is None and row["guest_count_min"] == 35
        assert row["guest_count_max"] == 45
    elif kind == "date":
        assert row["event_date"] == "2027-02-20" and row["event_date_type"] == "EXACT"
    else:
        assert row["event_type"] == "BIRTHDAY"


async def test_r6_current_name_confirmation_control(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured(monkeypatch)
    body = "Me llamo Nombre Vigente"
    event = await prepare(db, name=None, body=body)
    first = await send(db, body, proposal(entities=[entity(
        "full_name", "Nombre Vigente", needs_confirmation=True,
        quality_status="PENDING_CONFIRMATION")]), event_id=event)
    last = await send(db, "si", proposal())
    evidence(request, steps=[first, last], final=last["after"])
    completed(first)
    completed(last)
    assert last["after"]["customer"][0]["full_name"] == "Nombre Vigente"
    assert actions(last["after"], "CUSTOMER_NAME_CONFIRMED") == 1


async def test_pause_does_not_apply_invalid_entities(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured(monkeypatch)
    body = "Corrijo a menos cinco"
    event = await prepare(db, body=body)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state = "HUMAN_ACTIVE"
        conversation.bot_enabled = False
    step = await send(db, body, proposal(entities=[entity("guest_count", -5)]), event_id=event)
    evidence(request, steps=[step], final=step["after"])
    completed(step)
    for table in ("event", "outbox", "customer", "lead", "handoff"):
        assert step["after"][table] == step["before"][table]
