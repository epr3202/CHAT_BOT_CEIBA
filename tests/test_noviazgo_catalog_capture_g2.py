from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset, CatalogEventTypeMap, CatalogSend
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from data.knowledge_seed import iter_seed_entries
from tests.integration.helpers import (
    cleanup_test_environment,
    configure_test_environment,
    database_sessionmaker,
    whatsapp_message_payload,
)

# These are the literal production payloads supplied for conversation 203.
PAYLOAD_3448 = '{"entities": {}, "priority": "NORMAL", "confidence": 0.85, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "GENERAL_INFORMATION", "reasoning_code": "catalog_request_explicit", "requested_action": null, "context_reference": {"pending_action": null, "last_question_code": null}, "secondary_intents": [], "extracted_entities": [], "needs_confirmation": false, "information_category": "catalog_request"}'  # noqa: E501
RAW_3449 = (
    '{\n  "primary_intent": "EVENT_INFORMATION",\n  "secondary_intents": [],\n'
    '  "sub_intent": null,\n  "confidence": 0.8'
)
PAYLOAD_3450 = '{"entities": {}, "priority": "NORMAL", "confidence": 0.7, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "GENERAL_INFORMATION", "reasoning_code": "USER_REQUESTS_OPTIONS_FOR_EVENT_TYPE", "requested_action": null, "context_reference": {"pending_action": "COLLECT_CATALOG_EVENT_TYPE", "last_question_code": "RESP-DISCOVERY-002"}, "secondary_intents": [], "extracted_entities": [], "needs_confirmation": false, "information_category": "tipos de eventos"}'  # noqa: E501
T1 = "Hola nuevamente, quiero ver el catálogo de pedidas de noviazgo"
T2 = "Una pedida de noviazgo"
T3 = "Quisiera ver que opciones para pedir noviazgo tienen"
PENDING = "COLLECT_CATALOG_EVENT_TYPE"
REAL_CLASSIFY = OpenRouterIntentClient.classify_intent


@dataclass
class Harness:
    sessions: async_sessionmaker[AsyncSession]
    conversation_id: int
    phone: str
    proposal_id: UUID
    romantic_id: UUID
    outputs: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    extractor_output: str = '{"event_type": "PROPOSAL"}'

    async def capture(self, pending: str = PENDING, question: str = "RESP-CATALOG-002") -> None:
        async with self.sessions() as session, session.begin():
            conversation = await session.get(Conversation, self.conversation_id)
            assert conversation is not None
            conversation.pending_action = pending
            conversation.last_question_code = question
            conversation.failed_understanding_count = 1

    async def turn(self, text: str = "", *, kind: str = "text") -> str:
        external_id = f"wamid.noviazgo.{uuid4().hex}"
        payload = json.loads(whatsapp_message_payload(external_id, text=text, phone=self.phone))
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        if kind != "text":
            message.pop("text")
            message["type"] = kind
            message[kind] = (
                {"id": "test-sticker", "mime_type": "image/webp", "sha256": "test-hash"}
                if kind == "sticker"
                else {"message_id": "wamid.original", "emoji": "👍"}
            )
        await process_whatsapp_webhook(payload, self.sessions, uuid4())
        return external_id

    async def snapshot(self) -> dict[str, Any]:
        async with self.sessions() as session:
            conversation = await session.get(Conversation, self.conversation_id)
            assert conversation is not None
            return {
                "context": (
                    conversation.state,
                    conversation.pending_action,
                    conversation.last_question_code,
                    conversation.failed_understanding_count,
                ),
                "outbox": list(await session.scalars(select(Outbox).order_by(Outbox.id))),
                "sends": list(await session.scalars(select(CatalogSend))),
                "audits": list(await session.scalars(select(AuditEvent))),
                "ai": list(await session.scalars(select(AIExecution))),
            }

    def reply(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user = payload["messages"][-1]["content"]
        text = user.rsplit("Mensaje:\n", 1)[-1]
        task = "extract" if user.startswith("Extrae el tipo") else "classify"
        self.calls.append((task, text))
        output = (
            self.extractor_output if task == "extract" else self.outputs.get(text, PAYLOAD_3450)
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": output}}]})


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "true")
    get_settings.cache_clear()
    # Restore the real parser/audit client after the generic fixture's greeting double.
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", REAL_CLASSIFY)
    try:
        async for sessions in database_sessionmaker():
            async with sessions() as session, session.begin():
                customer = Customer(phone_number="+573009990203", full_name="Natalia Pérez")
                session.add(customer)
                await session.flush()
                lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
                session.add(lead)
                await session.flush()
                session.add(Event(lead_id=lead.lead_id))
                conversation = Conversation(
                    customer_id=customer.id,
                    channel="WHATSAPP",
                    state="BOT_ACTIVE",
                    active_lead_id=lead.lead_id,
                    pending_fields=[],
                    failed_understanding_count=0,
                )
                session.add(conversation)
                assets = []
                for event_type in ("PROPOSAL", "ROMANTIC_DINNER"):
                    asset = CatalogAsset(
                        name=event_type,
                        file_path=f"{event_type}.pdf",
                        file_hash="a" * 64,
                        file_size=25,
                        mime_type="application/pdf",
                        active=True,
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(
                        CatalogEventTypeMap(
                            catalog_asset_id=asset.catalog_asset_id,
                            event_type=event_type,
                            send_mode="PROACTIVE",
                        )
                    )
                    assets.append(asset.catalog_asset_id)
                await session.flush()
                fixture = Harness(sessions, conversation.id, "573009990203", *assets)
            # All HTTP is mocked; real client parsing and append-only execution records run.
            with respx.mock(assert_all_called=False) as router:
                router.post("https://openrouter.ai/api/v1/chat/completions").mock(
                    side_effect=fixture.reply
                )
                yield fixture
    finally:
        await cleanup_test_environment()


def assert_safe_outputs(snapshot: dict[str, Any]) -> None:
    forbidden = {
        entry.answer_template
        for entry in iter_seed_entries()
        if entry.code in {"RESP-DISCOVERY-002", "RESP-EVENTS-001", "RESP-CATALOG-002"}
    }
    assert not any(
        row.message_kind == "TEXT" and row.payload["text"]["body"] in forbidden
        for row in snapshot["outbox"]
    )
    assert "CATALOG_CAPTURE_ABANDONED" not in {row.action for row in snapshot["audits"]}


async def assert_catalog(harness: Harness, *, explicit: bool = True) -> dict[str, Any]:
    snapshot = await harness.snapshot()
    rows = snapshot["outbox"]
    assert [row.message_kind for row in rows] == (
        ["DOCUMENT"] if explicit else ["TEXT", "DOCUMENT"]
    )
    document = rows[-1]
    assert document.catalog_asset_id == harness.proposal_id
    assert document.catalog_asset_id != harness.romantic_id
    assert document.payload["document"]["caption"] == next(
        e.answer_template for e in iter_seed_entries() if e.code == "RESP-CATALOG-001"
    ).format(event_type="una propuesta de matrimonio")
    assert len(snapshot["sends"]) == 1
    assert snapshot["sends"][0].outbound_message_id == document.id
    assert snapshot["sends"][0].trigger == ("EXPLICIT_REQUEST" if explicit else "PROACTIVE")
    assert snapshot["context"][1] is None
    assert_safe_outputs(snapshot)
    return snapshot


async def test_g2_1_full_production_transcript(harness: Harness) -> None:
    harness.outputs.update({T1: PAYLOAD_3448, T2: RAW_3449, T3: PAYLOAD_3450})
    await harness.turn(T1)
    first = await harness.snapshot()
    sticker_id = await harness.turn(kind="sticker")
    sticker = await harness.snapshot()
    await harness.turn(T2)
    await harness.turn(T3)
    final = await harness.snapshot()
    # Check the transcript only after all four turns have actually executed.
    assert [row.message_kind for row in first["outbox"]] == ["DOCUMENT"]
    assert first["outbox"][0].catalog_asset_id == harness.proposal_id
    assert first["context"][1] is None
    assert ("classify", T1) not in harness.calls
    assert sticker["context"] == first["context"]
    assert not any(row.external_message_id == sticker_id for row in final["ai"])
    assert_safe_outputs(final)


async def test_g2_2_capture_sticker_then_noviazgo(harness: Harness) -> None:
    await harness.capture()
    before = await harness.snapshot()
    await harness.turn(kind="sticker")
    assert (await harness.snapshot())["context"] == before["context"]
    harness.outputs[T2] = RAW_3449
    await harness.turn(T2)
    await assert_catalog(harness)
    assert harness.calls == []


async def test_g2_3_capture_options_phrase(harness: Harness) -> None:
    await harness.capture()
    harness.outputs[T3] = PAYLOAD_3450
    await harness.turn(T3)
    await assert_catalog(harness)
    assert harness.calls == []


async def test_g2_4_invalid_json_repeats_catalog_question(harness: Harness) -> None:
    await harness.capture()
    before = (await harness.snapshot())["context"]
    text = "algo especial para mi pareja"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    result = await harness.snapshot()
    assert result["context"] == before
    assert len(result["outbox"]) == 1
    expected = next(e.answer_template for e in iter_seed_entries() if e.code == "RESP-CATALOG-002")
    assert result["outbox"][0].payload["text"]["body"] == expected
    assert "AI_UNAVAILABLE" in {row.action for row in result["audits"]}
    assert result["ai"][0].raw_output == RAW_3449
    assert result["ai"][0].error_reason == "INVALID_JSON"


async def test_g2_5_extractor_before_abandonment(harness: Harness) -> None:
    await harness.capture()
    text = "quiero sorprender a mi novia"
    harness.outputs[text] = PAYLOAD_3450
    await harness.turn(text)
    await assert_catalog(harness)
    assert harness.calls == [("classify", text), ("extract", text)]
    assert {row.task for row in (await harness.snapshot())["ai"]} == {
        "INTENT_CLASSIFICATION",
        "EVENT_TYPE_EXTRACTION",
    }


async def test_g2_6_new_general_information_fixed_price(harness: Harness) -> None:
    harness.outputs[T3] = PAYLOAD_3450
    await harness.turn(T3)
    result = await assert_catalog(harness, explicit=False)
    expected = next(
        e.answer_template for e in iter_seed_entries() if e.code == "RESP-EVENTS-PROPOSAL-001"
    )
    assert result["outbox"][0].payload["text"]["body"] == expected


@pytest.mark.parametrize("kind", ["sticker", "reaction"])
async def test_g2_8_non_text_contract(harness: Harness, kind: str) -> None:
    await harness.capture()
    before = (await harness.snapshot())["context"]
    await harness.turn(kind=kind)
    result = await harness.snapshot()
    assert result["context"] == before
    assert result["ai"] == []
    assert result["outbox"] == []
    assert harness.calls == []


@pytest.mark.parametrize(
    "pending,question,expected",
    [
        ("COLLECT_CUSTOMER_NAME", "RESP-CUSTOMER-001", "RESP-CUSTOMER-001"),
        ("COLLECT_EVENT_DATE", "RESP-EVENT-DATA-003", "RESP-DISCOVERY-002"),
    ],
)
async def test_g2_9_other_pending_question(
    harness: Harness,
    pending: str,
    question: str,
    expected: str,
) -> None:
    await harness.capture(pending, question)
    text = "algo especial para mi pareja"
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    result = await harness.snapshot()
    assert result["context"][1:] == (pending, expected, 1)
    assert result["outbox"][0].payload["text"]["body"] == next(
        e.answer_template for e in iter_seed_entries() if e.code == expected
    )
    assert "AI_UNAVAILABLE" in {row.action for row in result["audits"]}


async def test_g2_deterministic_resolution_audited(harness: Harness) -> None:
    await harness.capture()
    await harness.turn(T2)
    result = await harness.snapshot()
    audit = next(
        (row for row in result["audits"] if row.action == "CATALOG_EVENT_TYPE_RESOLVED"), None
    )
    assert audit is not None
    assert audit.actor == "SYSTEM"
    assert audit.new_value["event_type"] == "PROPOSAL"
    assert audit.new_value["matched_label"] == "pedida de noviazgo"
    assert audit.new_value["decision_source"] == "DETERMINISTIC"


@pytest.mark.parametrize(
    "text",
    [
        "cuanto cuesta el salon? llevamos 3 años de noviazgo",
        "tengo una propuesta comercial para ustedes",
        "para celebrar 2 años de noviazgo",
        "mandame otro catalogo",
    ],
)
async def test_c1_c2_incidental_mentions_reach_general_classifier(
    harness: Harness, text: str
) -> None:
    harness.outputs[text] = PAYLOAD_3450
    await harness.turn(text)
    result = await harness.snapshot()
    assert harness.calls == [("classify", text)]
    assert len(result["ai"]) == 1
    assert result["ai"][0].task == "INTENT_CLASSIFICATION"
    assert result["ai"][0].parsed_output == json.loads(PAYLOAD_3450)
    assert result["ai"][0].validation_status == "VALID"
    assert result["sends"] == []
    assert all(row.catalog_asset_id != harness.proposal_id for row in result["outbox"])
    assert result["context"][0] == "BOT_ACTIVE"
    assert "CATALOG_EVENT_TYPE_RESOLVED" not in {row.action for row in result["audits"]}
    assert "CATALOG_HANDOFF_NOT_AVAILABLE" not in {row.action for row in result["audits"]}


@pytest.mark.parametrize(
    "text,event_type",
    [("noviazgo", "PROPOSAL"), ("propuesta", "PROPOSAL"), ("otro", "OTHER")],
)
async def test_c1_capture_accepts_short_event_type_answers(
    harness: Harness,
    text: str,
    event_type: str,
) -> None:
    await harness.capture()
    harness.outputs[text] = RAW_3449
    await harness.turn(text)
    result = await harness.snapshot()
    assert harness.calls == []
    assert result["ai"] == []
    resolutions = [row for row in result["audits"] if row.action == "CATALOG_EVENT_TYPE_RESOLVED"]
    assert len(resolutions) == 1
    assert resolutions[0].new_value["event_type"] == event_type
    if event_type == "PROPOSAL":
        await assert_catalog(harness)
    else:
        # The fixture has no OTHER PDF: preserve the existing unavailable handoff.
        assert result["sends"] == []
        assert result["context"][1] == "WAIT_FOR_HUMAN"
