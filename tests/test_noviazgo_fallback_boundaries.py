from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs

from app.conversation.models import Conversation, KnowledgeEntry
from data.knowledge_seed import iter_seed_entries
from tests.test_noviazgo_catalog_capture_g2 import (
    RAW_3449,
    T1,
    T2,
    T3,
    Harness,
)
from tests.test_noviazgo_catalog_capture_g2 import (
    harness as harness,
)


@pytest.mark.parametrize(
    "text,source",
    [(T1, "EXPLICIT_CATALOG_MENTION"), (T2, "FIXED_PRICE_MENTION"), (T3, "FIXED_PRICE_MENTION")],
)
async def test_deterministic_catalog_sources(harness: Harness, text: str, source: str) -> None:
    with capture_logs() as logs:
        await harness.turn(text)
    snapshot = await harness.snapshot()
    assert harness.calls == []
    assert snapshot["ai"] == []
    resolutions = [row for row in snapshot["audits"] if row.action == "CATALOG_EVENT_TYPE_RESOLVED"]
    assert len(resolutions) == 1
    assert resolutions[0].new_value["source"] == source
    assert resolutions[0].new_value["decision_source"] == "DETERMINISTIC"
    assert resolutions[0].new_value["matched_label"] in {
        "pedidas de noviazgo",
        "pedida de noviazgo",
        "pedir noviazgo",
    }
    decisions = [row for row in logs if row["event"] == "orchestrator_decision"]
    assert decisions[-1]["decision_source"] == "DETERMINISTIC"
    assert decisions[-1]["conversation_id"] == harness.conversation_id


@pytest.mark.parametrize(
    "pending,question",
    [
        (None, "RESP-CATALOG-002"),
        ("NONE", "RESP-CATALOG-002"),
        ("COLLECT_CATALOG_EVENT_TYPE", None),
        ("COLLECT_CATALOG_EVENT_TYPE", "RESP-NOT-EXISTING"),
    ],
)
async def test_missing_pending_or_question_keeps_discovery_fallback(
    harness: Harness,
    pending: str | None,
    question: str | None,
) -> None:
    async with harness.sessions() as session, session.begin():
        conversation = await session.get(Conversation, harness.conversation_id)
        assert conversation is not None
        conversation.pending_action = pending
        conversation.last_question_code = question
    text = "algo especial para mi pareja"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    snapshot = await harness.snapshot()
    assert snapshot["context"][1] == pending
    assert snapshot["context"][2] == "RESP-DISCOVERY-002"


async def test_latest_draft_does_not_revive_older_approved_question(harness: Harness) -> None:
    await harness.capture()
    async with harness.sessions() as session, session.begin():
        latest = await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == "RESP-CATALOG-002")
            .order_by(KnowledgeEntry.version.desc())
        )
        assert latest is not None and latest.status == "APPROVED"
        session.add(
            KnowledgeEntry(
                code=latest.code,
                category=latest.category,
                question_summary=latest.question_summary,
                answer_template=latest.answer_template,
                allowed_variables=[],
                version=latest.version + 1,
                status="DRAFT",
            )
        )
    text = "algo especial para mi pareja"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    assert (await harness.snapshot())["context"][2] == "RESP-DISCOVERY-002"


@pytest.mark.parametrize(
    "state",
    [
        "APPOINTMENT_PENDING_CONFIRMATION",
        "WAITING_FOR_APPOINTMENT_DATE",
        "WAITING_FOR_APPOINTMENT_SELECTION",
        "QUOTE_REQUEST_READY",
    ],
)
async def test_ai_unavailable_critical_precedence(harness: Harness, state: str) -> None:
    await harness.capture()
    async with harness.sessions() as session, session.begin():
        conversation = await session.get(Conversation, harness.conversation_id)
        assert conversation is not None
        conversation.state = state
    text = "algo especial para mi pareja"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    snapshot = await harness.snapshot()
    assert snapshot["context"][0] == "WAITING_FOR_HUMAN"
    assert snapshot["context"][1] == "WAIT_FOR_HUMAN"


async def test_ai_unavailable_location_precedes_pending_question(harness: Harness) -> None:
    await harness.capture()
    text = "¿Dónde están ubicados?"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    snapshot = await harness.snapshot()
    assert snapshot["context"][1] == "COLLECT_CATALOG_EVENT_TYPE"
    assert snapshot["context"][2] == "RESP-LOCATION-002"
    assert snapshot["context"][3] == 1


@pytest.mark.parametrize("question", ["RESP-CATALOG-002", "RESP-CUSTOMER-001"])
async def test_fallback_preserves_counter_and_exact_approved_text(
    harness: Harness,
    question: str,
) -> None:
    await harness.capture("COLLECT_CUSTOMER_NAME", question)
    harness.outputs["indefinido"] = RAW_3449
    await harness.turn("indefinido")
    snapshot: dict[str, Any] = await harness.snapshot()
    expected = next(e.answer_template for e in iter_seed_entries() if e.code == question)
    assert snapshot["context"][1:] == ("COLLECT_CUSTOMER_NAME", question, 1)
    assert snapshot["outbox"][0].payload["text"]["body"] == expected
