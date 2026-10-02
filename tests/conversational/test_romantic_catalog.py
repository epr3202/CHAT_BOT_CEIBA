from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset, CatalogEventTypeMap, CatalogSend
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.states import ConversationState
from app.event.models import Event, EventServiceRequest
from app.lead.models import Lead
from app.quote.models import QuoteRequest
from data.knowledge_seed import iter_seed_entries
from tests.conversational.test_slice3_quote_capture import (
    classification,
    entity,
    run_turn,
    seed_conversation,
)
from tests.integration.helpers import (
    cleanup_test_environment,
    configure_test_environment,
    database_sessionmaker,
    whatsapp_message_payload,
)

ROMANTIC_CODE = "RESP-EVENTS-ROMANTIC-001"
ROMANTIC_TEXT = (
    "Nuestras experiencias románticas para dos: Ritual del Corazón ($250.000), "
    "Romance entre Copas ($400.000), Mañanas de Encanto ($450.000, fines de semana), "
    "Cinema y Amor ($700.000) y Refugio para Dos ($1.000.000). Te envío el catálogo "
    "con el detalle de cada una. Cuéntame cuál te interesa y para qué fecha, "
    "y te confirmo disponibilidad."
)
FORENSIC_TEXT = "Quiero saber información sobre una cena romántica"


@dataclass(frozen=True)
class CatalogFixture:
    sessions: async_sessionmaker[AsyncSession]
    proactive_id: UUID
    on_request_id: UUID


@pytest.fixture
async def catalogs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[CatalogFixture]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setattr("app.orchestrator.service.entity_today", lambda: date(2026, 9, 26))
    try:
        async for sessions in database_sessionmaker():
            async with sessions() as session, session.begin():
                asset_ids = []
                for mode in ("PROACTIVE", "ON_REQUEST"):
                    pdf = tmp_path / f"{mode}.pdf"
                    pdf.write_bytes(b"%PDF-1.4\nromantic test catalog\n")
                    asset = CatalogAsset(
                        name=f"Romantic {mode}",
                        file_path=str(pdf),
                        file_hash="a" * 64,
                        file_size=pdf.stat().st_size,
                        mime_type="application/pdf",
                        active=True,
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(
                        CatalogEventTypeMap(
                            catalog_asset_id=asset.catalog_asset_id,
                            event_type="ROMANTIC_DINNER",
                            send_mode=mode,
                        )
                    )
                    asset_ids.append(asset.catalog_asset_id)
                template = await session.scalar(
                    select(KnowledgeEntry).where(KnowledgeEntry.code == ROMANTIC_CODE)
                )
                # Approval is test-only; the seed must remain DRAFT pending Leandro's OK.
                if template is not None:
                    template.status = "APPROVED"
                    template.answer_template = template.answer_template.removeprefix("[REVISAR] ")
            yield CatalogFixture(sessions, *asset_ids)
    finally:
        await cleanup_test_environment()


async def assert_romantic_template(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Check the shared seed prerequisite with AssertionError, never a missing-key error."""
    async with sessions() as session:
        template = await session.scalar(
            select(KnowledgeEntry).where(KnowledgeEntry.code == ROMANTIC_CODE)
        )
    assert template is not None, f"Missing knowledge_entry: {ROMANTIC_CODE}"
    assert template.status == "APPROVED"
    assert template.answer_template == ROMANTIC_TEXT
    seed = next((entry for entry in iter_seed_entries() if entry.code == ROMANTIC_CODE), None)
    assert seed is not None
    assert seed.status == "DRAFT", "Production copy still awaits Leandro's approval"


async def information_turn(
    catalogs: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    event_type: str = "ROMANTIC_DINNER",
) -> int:
    text = FORENSIC_TEXT if event_type == "ROMANTIC_DINNER" else "Información sobre una boda"
    async with catalogs.sessions() as session, session.begin():
        customer, conversation = await seed_conversation(session)
        conversation.last_intent = "GREETING"
        conversation.last_question_code = "RESP-GREETING-001"

    # Exact ai_execution 3354 payload. The entity comes separately from 3355,
    # through the real inbound pipeline and OrchestrationInput.directed_event_type.
    result = classification("GENERAL_INFORMATION", information_category="tipos de eventos")
    result = result.model_copy(
        update={
            "confidence": 0.7,
            "context_reference": {
                "pending_action": None,
                "last_question_code": "RESP-GREETING-001",
            },
            "reasoning_code": "CLIENT_ASKED_FOR_INFO_ABOUT_EVENT_TYPE",
        }
    )
    calls = []

    async def classify(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict,
        **_kwargs: object,
    ) -> IntentClassification:
        assert message_text == text
        assert context["last_question_code"] == "RESP-GREETING-001"
        calls.append("classify")
        return result

    async def extract(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict,
        **_kwargs: object,
    ) -> str:
        assert message_text == text
        assert context["pending_action"] is None
        calls.append("extract")
        return event_type

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract)
    payload = json.loads(
        whatsapp_message_payload(
            f"wamid.romantic.{uuid4().hex}",
            text=text,
            phone=customer.phone_number.lstrip("+"),
        )
    )
    await process_whatsapp_webhook(payload, catalogs.sessions, uuid4())
    assert calls == ["classify", "extract"]
    return conversation.id


async def seed_capture(catalogs: CatalogFixture) -> tuple[int, int]:
    async with catalogs.sessions() as session, session.begin():
        customer, conversation = await seed_conversation(
            session,
            ConversationState.COLLECTING_EVENT_DATA,
        )
        customer.full_name = "Emerson"
        lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
        session.add(lead)
        await session.flush()
        event = Event(lead_id=lead.lead_id, guest_count=2, guest_count_status="PROVIDED")
        session.add(event)
        await session.flush()
        session.add(
            EventServiceRequest(
                event_id=event.event_id,
                service_name="espacio",
                status="REQUESTED",
            )
        )
        conversation.active_lead_id = lead.lead_id
        # A stale held budget field must not win over the actual missing date.
        conversation.pending_fields = ["estimated_budget", "event_date"]
        return customer.id, conversation.id


@pytest.mark.asyncio
async def test_general_information_with_extracted_romantic_dinner_sends_catalog(
    catalogs: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await information_turn(catalogs, monkeypatch)
    async with catalogs.sessions() as session:
        outbox = list(await session.scalars(select(Outbox).order_by(Outbox.id)))
        documents = [row for row in outbox if row.message_kind == "DOCUMENT"]
        assert [(row.catalog_asset_id, row.status) for row in documents] == [
            (catalogs.proactive_id, "PENDING"),
        ]
        assert [row.payload["text"]["body"] for row in outbox if row.message_kind == "TEXT"] == [
            ROMANTIC_TEXT,
        ]
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.last_question_code == ROMANTIC_CODE
        assert conversation.state == "BOT_ACTIVE"
        assert conversation.pending_action is None
        send = await session.scalar(select(CatalogSend))
        assert send is not None
        assert send.lead_id == conversation.active_lead_id
        assert send.catalog_asset_id == catalogs.proactive_id
        assert send.trigger == "PROACTIVE"
        assert send.outbound_message_id == documents[0].id
        event = await session.scalar(select(Event).where(Event.lead_id == send.lead_id))
        assert event is not None and event.event_type == "ROMANTIC_DINNER"
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ROMANTIC_CATALOG_SENT_FROM_GENERAL_INFO",
            )
        )
        assert audit is not None
        assert audit.new_value["event_type"] == "ROMANTIC_DINNER"
        assert audit.new_value["lead_id"] == str(send.lead_id)
        assert audit.new_value["sent_count"] == 1
    await assert_romantic_template(catalogs.sessions)


@pytest.mark.asyncio
async def test_collecting_event_data_romantic_dinner_sends_catalog_and_skips_budget(
    catalogs: CatalogFixture,
) -> None:
    customer_id, conversation_id = await seed_capture(catalogs)
    await run_turn(
        catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "Una cena romántica",
        classification(
            "EVENT_INFORMATION",
            [
                entity("event_type", "Una cena romántica", "cena romántica"),
            ],
        ).model_copy(update={"confidence": 0.7, "reasoning_code": "MSG-EVENT-TYPE-DETECTED"}),
        "wamid.romantic.capture",
    )
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        lead = await session.scalar(select(Lead))
        document = await session.scalar(select(Outbox).where(Outbox.message_kind == "DOCUMENT"))
        assert document is not None and document.catalog_asset_id == catalogs.proactive_id
        assert document.status == "PENDING"
        assert conversation is not None and lead is not None
        assert conversation.pending_action == "COLLECT_EVENT_DATE"
        assert "estimated_budget" not in conversation.pending_fields
        assert lead.budget_data_status == "NOT_ASKED"

    await run_turn(
        catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "10 de octubre de 2026",
        classification(
            "MODIFY_EVENT_DATA",
            [
                entity(
                    "event_date",
                    "10 de octubre",
                    {
                        "event_date": "2026-10-10",
                        "event_month": None,
                        "event_date_type": "EXACT",
                        "event_date_raw": "10 de octubre",
                    },
                )
            ],
        ),
        "wamid.romantic.date",
    )
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        lead = await session.scalar(select(Lead))
        quote = await session.scalar(select(QuoteRequest))
        assert conversation is not None and lead is not None and quote is not None
        assert conversation.pending_action == "CONFIRM_QUOTE_REQUEST"
        assert conversation.state == "QUOTE_REQUEST_READY"
        assert conversation.pending_fields == []
        assert lead.budget_data_status == "NOT_ASKED"
        assert lead.estimated_budget is None
        assert quote.minimum_data_complete
        budget = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == "RESP-BUDGET-001",
            )
        )
        texts = [
            row.payload["text"]["body"]
            for row in await session.scalars(
                select(Outbox).where(Outbox.message_kind == "TEXT"),
            )
        ]
        assert budget is not None and budget.answer_template not in texts
    await assert_romantic_template(catalogs.sessions)


@pytest.mark.asyncio
async def test_romantic_catalog_not_sent_twice_in_same_lead(
    catalogs: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await information_turn(catalogs, monkeypatch)
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        original_lead_id = conversation.active_lead_id
        customer_id = conversation.customer_id
    await run_turn(
        catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "Una cena romántica",
        classification(
            "EVENT_INFORMATION",
            [
                entity("event_type", "cena romántica", "ROMANTIC_DINNER"),
            ],
        ),
        "wamid.romantic.repeat",
    )
    async with catalogs.sessions() as session:
        sends = list(await session.scalars(select(CatalogSend)))
        assert len(sends) == 1
        assert sends[0].lead_id == original_lead_id
        assert sends[0].catalog_asset_id == catalogs.proactive_id
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(
                    Outbox.message_kind == "DOCUMENT",
                )
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert (
            await session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action == "CATALOG_SEND_DEDUPED",
                )
            )
            is not None
        )
    await assert_romantic_template(catalogs.sessions)


@pytest.mark.asyncio
async def test_other_event_type_general_information_unchanged(
    catalogs: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await information_turn(catalogs, monkeypatch, event_type="WEDDING")
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.last_question_code == "RESP-EVENTS-001"
        assert conversation.active_lead_id is None
        outbox = list(await session.scalars(select(Outbox)))
        template = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == "RESP-EVENTS-001",
            )
        )
        assert template is not None
        assert [(row.message_kind, row.payload["text"]["body"]) for row in outbox] == [
            ("TEXT", template.answer_template),
        ]
    await assert_romantic_template(catalogs.sessions)


@pytest.mark.asyncio
async def test_romantic_dinner_without_proactive_mapping_falls_back(
    catalogs: CatalogFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with catalogs.sessions() as session, session.begin():
        mapping = await session.scalar(
            select(CatalogEventTypeMap).where(
                CatalogEventTypeMap.catalog_asset_id == catalogs.proactive_id,
            )
        )
        assert mapping is not None
        mapping.send_mode = "ON_REQUEST"
    await information_turn(catalogs, monkeypatch)
    async with catalogs.sessions() as session:
        outbox = list(await session.scalars(select(Outbox)))
        assert [(row.message_kind, row.payload["text"]["body"]) for row in outbox] == [
            ("TEXT", ROMANTIC_TEXT),
        ]
        omitted = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "CATALOG_SEND_OMITTED",
            )
        )
        assert omitted is not None
        assert omitted.new_value["event_type"] == "ROMANTIC_DINNER"
        assert omitted.new_value["trigger"] == "PROACTIVE"
        assert await session.scalar(select(func.count()).select_from(CatalogSend)) == 0
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ROMANTIC_CATALOG_SENT_FROM_GENERAL_INFO",
            )
        )
        assert audit is not None and audit.new_value["sent_count"] == 0
    await assert_romantic_template(catalogs.sessions)


@pytest.mark.asyncio
async def test_budget_still_asked_for_non_romantic_event(catalogs: CatalogFixture) -> None:
    customer_id, conversation_id = await seed_capture(catalogs)
    await run_turn(
        catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "Una boda",
        classification("EVENT_INFORMATION", [entity("event_type", "boda", "WEDDING")]),
        "wamid.wedding.budget",
    )
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        lead = await session.scalar(select(Lead))
        assert conversation is not None and lead is not None
        assert conversation.pending_action == "COLLECT_BUDGET"
        assert conversation.last_question_code == "RESP-BUDGET-001"
        assert "estimated_budget" in conversation.pending_fields
        assert lead.budget_data_status == "ASKED_PENDING"
    await assert_romantic_template(catalogs.sessions)


PROPOSAL_CODE = "RESP-EVENTS-PROPOSAL-001"
PROPOSAL_TEXT = (
    "Nuestras experiencias para pedir la mano: Entre Pétalos y Estrellas ($450.000), "
    "Confesión bajo la Luna ($900.000) y Noche Inolvidable ($2.500.000, con exclusividad "
    "de la terraza). Te envío el catálogo con el detalle de cada una. Cuéntame cuál "
    "te interesa y para qué fecha, y te confirmo disponibilidad."
)


@pytest.fixture
async def proposal_catalogs(catalogs: CatalogFixture, tmp_path: Path) -> CatalogFixture:
    async with catalogs.sessions() as session, session.begin():
        asset_ids = []
        for mode in ("PROACTIVE", "ON_REQUEST"):
            pdf = tmp_path / f"proposal-{mode}.pdf"
            pdf.write_bytes(b"%PDF-1.4\nproposal test catalog\n")
            asset = CatalogAsset(
                name=f"Proposal {mode}",
                file_path=str(pdf),
                file_hash="b" * 64,
                file_size=pdf.stat().st_size,
                mime_type="application/pdf",
                active=True,
            )
            session.add(asset)
            await session.flush()
            session.add(
                CatalogEventTypeMap(
                    catalog_asset_id=asset.catalog_asset_id,
                    event_type="PROPOSAL",
                    send_mode=mode,
                )
            )
            asset_ids.append(asset.catalog_asset_id)
        template = await session.scalar(
            select(KnowledgeEntry).where(KnowledgeEntry.code == PROPOSAL_CODE)
        )
        # Same test-only approval as romantic plans; the new seed must remain DRAFT.
        if template is not None:
            template.status = "APPROVED"
            template.answer_template = template.answer_template.removeprefix("[REVISAR] ")
    return CatalogFixture(catalogs.sessions, *asset_ids)


async def fixed_price_information_turn(
    catalogs: CatalogFixture,
    text: str,
    event_types: tuple[str, ...] = (),
    *,
    information_category: str | None = None,
) -> int:
    async with catalogs.sessions() as session, session.begin():
        customer, conversation = await seed_conversation(session)
    await run_turn(
        catalogs.sessions,
        get_settings(),
        conversation.id,
        customer.id,
        text,
        classification(
            "GENERAL_INFORMATION",
            [entity("event_type", value, value) for value in event_types],
            information_category=information_category,
        ),
        f"wamid.fixed-price.{uuid4().hex}",
    )
    return conversation.id


async def assert_fixed_price_information(
    catalogs: CatalogFixture,
    conversation_id: int,
    event_type: str,
    response_code: str,
    response_text: str,
    *,
    sent_count: int = 1,
) -> None:
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        event = await session.scalar(
            select(Event).where(
                Event.lead_id == conversation.active_lead_id,
            )
        )
        assert event is not None and event.event_type == event_type
        assert conversation.state == "BOT_ACTIVE"
        assert conversation.last_question_code == response_code
        assert conversation.pending_action is None
        outbox = list(
            await session.scalars(
                select(Outbox)
                .where(
                    Outbox.conversation_id == conversation_id,
                )
                .order_by(Outbox.id)
            )
        )
        assert [row.payload["text"]["body"] for row in outbox if row.message_kind == "TEXT"] == [
            response_text,
        ]
        documents = [row for row in outbox if row.message_kind == "DOCUMENT"]
        assert [row.catalog_asset_id for row in documents] == [catalogs.proactive_id] * sent_count
        captured = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "EVENT_TYPE_CAPTURED",
            )
        )
        assert captured is not None and captured.new_value["event_type"] == event_type
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO",
            )
        )
        assert audit is not None
        assert audit.new_value["event_type"] == event_type
        assert audit.new_value["lead_id"] == str(event.lead_id)
        assert audit.new_value["sent_count"] == sent_count
        if event_type == "PROPOSAL":
            assert (
                await session.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.action == "ROMANTIC_CATALOG_SENT_FROM_GENERAL_INFO",
                    )
                )
                is None
            )


@pytest.mark.parametrize(
    "text",
    [
        "Quiero información sobre una pedida de mano",
        "PEDIDA DE MANO",
        "Información sobre una propuesta de matrimonio",
        "PROPUESTA DE MATRIMONIO",
        "Quiero un letrero: ¿quieres ser mi esposa?",
        "¿QUIÉRES SER MÍ ESPOSA?",
        "Quiero pedirle matrimonio",
        "PEDIRLE MATRIMONIO",
        "Quiero pedir la mano",
        "PEDIRLE LA MANO",
        "Quiero proponerle matrimonio",
        "anillo de compromiso",
        "Fiesta de compromiso",
        "CELEBRACIÓN DE COMPROMISO",
    ],
)
async def test_proposal_information_phrase_without_ai_entity(
    proposal_catalogs: CatalogFixture,
    text: str,
) -> None:
    conversation_id = await fixed_price_information_turn(proposal_catalogs, text)
    await assert_fixed_price_information(
        proposal_catalogs,
        conversation_id,
        "PROPOSAL",
        PROPOSAL_CODE,
        PROPOSAL_TEXT,
    )


@pytest.mark.parametrize(
    "text,event_types",
    [
        ("Pedida de mano con cena romántica", ()),
        ("Pedida de mano con cena romántica", ("ROMANTIC_DINNER",)),
        ("CENA ROMANTICA PARA UNA PROPUESTA DE MATRIMONIO", ("ROMANTIC_DINNER",)),
        ("Cena romántica de compromiso", ("ROMANTIC_DINNER", "PROPOSAL")),
        ("Quiero más información", ("ROMANTIC_DINNER", "PROPOSAL")),
        ("Quiero más información", ("PROPOSAL", "ROMANTIC_DINNER")),
        ("Quiero más información", ("PROPOSAL",)),
    ],
)
async def test_proposal_takes_priority_over_romantic_dinner(
    proposal_catalogs: CatalogFixture,
    text: str,
    event_types: tuple[str, ...],
) -> None:
    conversation_id = await fixed_price_information_turn(proposal_catalogs, text, event_types)
    await assert_fixed_price_information(
        proposal_catalogs,
        conversation_id,
        "PROPOSAL",
        PROPOSAL_CODE,
        PROPOSAL_TEXT,
    )


async def assert_no_fixed_price_capture(
    catalogs: CatalogFixture,
    conversation_id: int,
    response_code: str,
) -> None:
    async with catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.last_question_code == response_code
        template = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == response_code,
            )
        )
        assert template is not None
        outbox = list(
            await session.scalars(
                select(Outbox).where(
                    Outbox.conversation_id == conversation_id,
                )
            )
        )
        assert all(row.message_kind == "TEXT" for row in outbox)
        assert [(row.message_kind, row.payload["text"]["body"]) for row in outbox] == [
            ("TEXT", template.answer_template),
        ]
        assert await session.scalar(select(func.count()).select_from(CatalogSend)) == 0
        assert (
            await session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action.in_(
                        [
                            "EVENT_TYPE_CAPTURED",
                            "EVENT_TYPE_CORRECTED",
                            "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO",
                            "ROMANTIC_CATALOG_SENT_FROM_GENERAL_INFO",
                        ]
                    ),
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "information_category,response_code",
    [
        (None, "RESP-FALLBACK-001"),
        ("tipos de eventos", "RESP-EVENTS-001"),
    ],
)
@pytest.mark.parametrize(
    "text",
    [
        "romántico",
        "ROMANTICO",
        "¿el lugar es romántico?",
        "cotización sin compromiso",
        "tengo un compromiso ese día",
        "COMPROMISO",
        "Información sobre un compromiso",
    ],
)
async def test_ambiguous_text_without_event_entity_does_not_capture_or_send_catalog(
    proposal_catalogs: CatalogFixture,
    text: str,
    information_category: str | None,
    response_code: str,
) -> None:
    conversation_id = await fixed_price_information_turn(
        proposal_catalogs,
        text,
        information_category=information_category,
    )
    await assert_no_fixed_price_capture(proposal_catalogs, conversation_id, response_code)
    async with proposal_catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation.active_lead_id is None
        assert await session.scalar(select(func.count()).select_from(Event)) == 0


@pytest.mark.parametrize("event_type", ["ANNIVERSARY", "WEDDING"])
@pytest.mark.parametrize("quality_status", ["PROVIDED", "CORRECTED"])
@pytest.mark.parametrize("needs_confirmation", [False, True])
async def test_proposal_text_preserves_other_classified_event_type(
    proposal_catalogs: CatalogFixture,
    event_type: str,
    quality_status: str,
    needs_confirmation: bool,
) -> None:
    async with proposal_catalogs.sessions() as session, session.begin():
        customer, conversation = await seed_conversation(session)
        lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
        session.add(lead)
        await session.flush()
        event = Event(lead_id=lead.lead_id, event_type=event_type)
        session.add(event)
        await session.flush()
        conversation.active_lead_id = lead.lead_id
    await run_turn(
        proposal_catalogs.sessions,
        get_settings(),
        conversation.id,
        customer.id,
        "pedida de mano",
        classification(
            "GENERAL_INFORMATION",
            [
                entity("event_type", event_type, event_type, quality_status, needs_confirmation),
            ],
            information_category="tipos de eventos",
        ),
        f"wamid.proposal.other.{uuid4().hex}",
    )
    await assert_no_fixed_price_capture(proposal_catalogs, conversation.id, "RESP-EVENTS-001")
    async with proposal_catalogs.sessions() as session:
        stored_event = await session.get(Event, event.event_id)
        assert stored_event is not None and stored_event.event_type == event_type
        assert await session.scalar(select(Event).where(Event.event_type == "PROPOSAL")) is None


async def test_proposal_without_active_asset_still_sends_approved_plans_text(
    proposal_catalogs: CatalogFixture,
) -> None:
    async with proposal_catalogs.sessions() as session, session.begin():
        for asset_id in (proposal_catalogs.proactive_id, proposal_catalogs.on_request_id):
            asset = await session.get(CatalogAsset, asset_id)
            asset.active = False
    conversation_id = await fixed_price_information_turn(proposal_catalogs, "pedida de mano")
    await assert_fixed_price_information(
        proposal_catalogs,
        conversation_id,
        "PROPOSAL",
        PROPOSAL_CODE,
        PROPOSAL_TEXT,
        sent_count=0,
    )
    async with proposal_catalogs.sessions() as session:
        omitted = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "CATALOG_SEND_OMITTED",
            )
        )
        assert omitted is not None
        assert omitted.new_value["event_type"] == "PROPOSAL"
        assert omitted.new_value["trigger"] == "PROACTIVE"
        assert await session.scalar(select(func.count()).select_from(CatalogSend)) == 0


async def test_proposal_capture_skips_budget_and_reaches_quote_confirmation(
    proposal_catalogs: CatalogFixture,
) -> None:
    customer_id, conversation_id = await seed_capture(proposal_catalogs)
    await run_turn(
        proposal_catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "Pedida de mano",
        classification("EVENT_INFORMATION", [entity("event_type", "Pedida de mano", "PROPOSAL")]),
        "wamid.proposal.capture",
    )
    async with proposal_catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation.pending_action == "COLLECT_EVENT_DATE"
        assert "estimated_budget" not in conversation.pending_fields
    await run_turn(
        proposal_catalogs.sessions,
        get_settings(),
        conversation_id,
        customer_id,
        "10 de octubre",
        classification(
            "MODIFY_EVENT_DATA",
            [
                entity(
                    "event_date",
                    "10 de octubre de 2026",
                    {
                        "event_date": "2026-10-10",
                        "event_month": None,
                        "event_date_type": "EXACT",
                        "event_date_raw": "10 de octubre de 2026",
                    },
                )
            ],
        ),
        "wamid.proposal.date",
    )
    async with proposal_catalogs.sessions() as session:
        conversation = await session.get(Conversation, conversation_id)
        lead = await session.get(Lead, conversation.active_lead_id)
        assert conversation.state == "QUOTE_REQUEST_READY"
        assert conversation.pending_action == "CONFIRM_QUOTE_REQUEST"
        assert conversation.pending_fields == []
        assert lead.budget_data_status == "NOT_ASKED"
        assert lead.estimated_budget is None
        budget = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == "RESP-BUDGET-001",
            )
        )
        texts = [
            row.payload["text"]["body"]
            for row in await session.scalars(
                select(Outbox).where(
                    Outbox.message_kind == "TEXT",
                )
            )
        ]
        assert budget.answer_template not in texts


def test_proposal_seed_is_draft_with_exact_plans_text() -> None:
    from data.knowledge_seed import CONDITIONAL_DRAFT_CODES

    assert PROPOSAL_CODE in CONDITIONAL_DRAFT_CODES
    template = next(entry for entry in iter_seed_entries() if entry.code == PROPOSAL_CODE)
    assert template.status == "DRAFT"
    assert template.answer_template == f"[REVISAR] {PROPOSAL_TEXT}"


async def test_unapproved_proposal_template_is_not_sent(catalogs: CatalogFixture) -> None:
    conversation_id = await fixed_price_information_turn(catalogs, "pedida de mano")
    async with catalogs.sessions() as session:
        event = await session.scalar(select(Event))
        assert event is not None and event.event_type == "PROPOSAL"
        fallback = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == "RESP-AI-ERROR-001",
            )
        )
        texts = [
            row.payload["text"]["body"]
            for row in await session.scalars(
                select(Outbox).where(
                    Outbox.conversation_id == conversation_id,
                    Outbox.message_kind == "TEXT",
                )
            )
        ]
        assert texts == [fallback.answer_template]
        assert all("[REVISAR]" not in text and "$450.000" not in text for text in texts)
