from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
import structlog.testing
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.models import AIExecution
from app.ai.schemas import IntentClassification
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.services_catalog import (
    compose_requested_services_summary,
    match_requested_services,
    service_aliases,
    service_catalog_codes,
)
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.lead.models import Lead
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)

PHONE = "+573001112233"
RETRY_TEXT = (
    'No logré identificar los servicios que te interesan. ¿Me lo confirmas de nuevo? '
    'Por ejemplo: "el espacio y la decoración" o "solo el espacio".'
)


@pytest.fixture
async def sessionmaker_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await configure_test_environment(monkeypatch)
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    yield sessionmaker


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL_INTENT="openai/test-model",
        OPENROUTER_TIMEOUT_SECONDS=0.2,
        OPENROUTER_MAX_RETRIES=0,
        ENVIRONMENT="testing",
        _env_file=None,
    )


def classification_without_entities(intent: str = "EVENT_INFORMATION") -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category=None,
        entities={},
        extracted_entities=[],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_PR_B",
    )


async def seed_capture(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    pending_action: str | None = "COLLECT_SERVICES",
) -> tuple[Conversation, Event]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                lead_status="QUALIFYING",
                budget_data_status="PROVIDED",
            )
            session.add(lead)
            await session.flush()
            event = Event(
                lead_id=lead.lead_id,
                event_type="WEDDING",
                event_date=date(2027, 2, 20),
                event_date_type="EXACT",
                event_date_raw="20 de febrero de 2027",
                guest_count=40,
                guest_count_status="PROVIDED",
            )
            session.add(event)
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.COLLECTING_EVENT_DATA,
                active_lead_id=lead.lead_id,
                pending_action=pending_action,
                pending_fields=["requested_services"] if pending_action else [],
                last_question_code=(
                    "RESP-EVENT-DATA-006" if pending_action == "COLLECT_SERVICES" else None
                ),
            )
            session.add(conversation)
            await session.flush()
            return conversation, event


async def send_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    message_id: str,
    text: str,
) -> None:
    payload = json.loads(
        whatsapp_message_payload(
            message_id,
            phone=PHONE.removeprefix("+"),
            text=text,
        ).decode()
    )
    await process_whatsapp_webhook(payload, sessionmaker, request_id=uuid4())


async def requested_service_values(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[str]:
    async with sessionmaker() as session:
        return list(
            await session.scalars(
                select(EventServiceRequest.service_name).order_by(EventServiceRequest.created_at)
            )
        )


async def install_no_llm_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("No LLM task may run for a deterministic service match")

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", fail)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", fail)


def completion_payload(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-services-test",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(arguments)}}],
    }


@pytest.mark.asyncio
async def test_tc_svc_001_solo_espacio_is_deterministic_and_skips_llm(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    await install_no_llm_allowed(monkeypatch)

    await send_turn(sessionmaker_fixture, message_id="tc-svc-001", text="solo espacio")

    assert await requested_service_values(sessionmaker_fixture) == ["VENUE"]


@pytest.mark.asyncio
async def test_tc_svc_002_production_literal_persists_codes_not_verbatim(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    await install_no_llm_allowed(monkeypatch)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-svc-002",
        text="Espacio y gastronomía",
    )

    values = await requested_service_values(sessionmaker_fixture)
    assert values == ["VENUE", "FOOD"]
    assert "Espacio y gastronomía" not in values


@pytest.mark.asyncio
async def test_tc_svc_003_multiple_aliases_resolve_multiple_codes(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    await install_no_llm_allowed(monkeypatch)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-svc-003",
        text="espacio y decoracion",
    )

    assert await requested_service_values(sessionmaker_fixture) == ["VENUE", "DECORATION"]


def test_tc_svc_004_longest_alias_match_wins_for_overlapping_phrases() -> None:
    assert match_requested_services("mobiliario adicional y musica en vivo") == [
        "ADDITIONAL_FURNITURE",
        "LIVE_MUSIC",
    ]


@pytest.mark.asyncio
async def test_tc_svc_005_matching_is_case_and_accent_insensitive(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    await install_no_llm_allowed(monkeypatch)

    await send_turn(sessionmaker_fixture, message_id="tc-svc-005", text="DECORACIÓN")

    assert await requested_service_values(sessionmaker_fixture) == ["DECORATION"]


@pytest.mark.asyncio
async def test_tc_svc_006_adjacent_negation_dispatches_services_classifier(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    service_calls: list[tuple[str, dict[str, Any]]] = []

    async def general_classifier(*_args: object, **_kwargs: object) -> IntentClassification:
        raise AssertionError("General classification must not replace SERVICES_CLASSIFICATION")

    async def services_classifier(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, Any],
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        service_calls.append((message_text, context))
        return ["VENUE"]

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", general_classifier)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", services_classifier)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-svc-006",
        text="sin licor, lo demás sí",
    )

    assert len(service_calls) == 1
    assert service_calls[0][0] == "sin licor, lo demás sí"
    assert service_calls[0][1]["pending_action"] == "COLLECT_SERVICES"


@pytest.mark.asyncio
async def test_tc_svc_007_no_alias_uses_closed_set_llm_result(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    service_calls: list[str] = []

    async def general_classifier(*_args: object, **_kwargs: object) -> IntentClassification:
        raise AssertionError("Pending services must use the directed services task")

    async def services_classifier(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        service_calls.append(message_text)
        return ["VENUE", "DECORATION"]

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", general_classifier)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", services_classifier)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-svc-007",
        text="quiero que todo se vea inolvidable",
    )

    assert service_calls == ["quiero que todo se vea inolvidable"]
    assert await requested_service_values(sessionmaker_fixture) == ["VENUE", "DECORATION"]


@pytest.mark.asyncio
@respx.mock
async def test_tc_svc_008_unknown_llm_code_is_invalid_schema_and_never_reaches_domain(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=completion_payload({"service_codes": ["PRIVATE_JET"]}),
        )
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        with pytest.raises(AIUnavailable) as raised:
            await client.classify_services(
                "quiero un jet privado",
                context={"pending_action": "COLLECT_SERVICES"},
                request_id=uuid4(),
            )

    assert raised.value.reason == AIErrorReason.SCHEMA_VIOLATION
    async with sessionmaker_fixture() as session:
        execution = await session.scalar(
            select(AIExecution).where(AIExecution.task == "SERVICES_CLASSIFICATION")
        )
    assert execution is not None
    assert execution.validation_status == "INVALID_SCHEMA"
    assert await requested_service_values(sessionmaker_fixture) == []


@pytest.mark.asyncio
async def test_tc_svc_009_empty_result_retries_once_then_uses_other_or_handoff(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_entry = next(
        (
            entry
            for entry in iter_seed_entries()
            if entry.code == "RESP-SERVICES-RETRY-001"
        ),
        None,
    )
    assert retry_entry is not None, (
        "RESP-SERVICES-RETRY-001 debe existir en approved-responses.md "
        "(entregable G3 commit 1)"
    )
    assert retry_entry.status == "APPROVED"
    assert retry_entry.answer_template == RETRY_TEXT
    await seed_capture(sessionmaker_fixture)

    async def general_classifier(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification_without_entities("UNKNOWN")

    async def empty_services(*_args: object, **_kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", general_classifier)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", empty_services)

    for attempt in range(1, 4):
        await send_turn(
            sessionmaker_fixture,
            message_id=f"tc-svc-009-{attempt}",
            text="no sé cómo explicarlo",
        )

    async with sessionmaker_fixture() as session:
        bodies = [
            row.payload["text"]["body"]
            for row in (
                await session.scalars(select(Outbox).order_by(Outbox.id))
            ).all()
        ]
        conversation = await session.scalar(select(Conversation))
    assert conversation is not None
    assert bodies.count(RETRY_TEXT) == 1
    assert conversation.pending_action != "COLLECT_SERVICES"
    stored_other = "OTHER" in await requested_service_values(sessionmaker_fixture)
    escalated = conversation.state in {
        ConversationState.WAITING_FOR_HUMAN,
        ConversationState.HUMAN_ACTIVE,
    }
    assert stored_other or escalated


def test_tc_svc_010_catalog_document_and_code_module_have_exact_parity() -> None:
    catalog_path = Path(__file__).parents[1] / "docs" / "product" / "services-catalog.md"
    documented = tuple(
        re.findall(r"^\| `([A-Z_]+)` \|", catalog_path.read_text(encoding="utf-8"), re.MULTILINE)
    )

    assert len(documented) == 37
    assert service_catalog_codes() == documented


def test_tc_svc_011_summary_uses_presentations_and_spanish_list_punctuation() -> None:
    assert compose_requested_services_summary(["VENUE"]) == "el espacio"
    assert compose_requested_services_summary(["VENUE", "DECORATION"]) == (
        "el espacio y la decoración"
    )
    assert compose_requested_services_summary(["VENUE", "DECORATION", "DJ"]) == (
        "el espacio, la decoración y el DJ"
    )


@pytest.mark.asyncio
async def test_tc_svc_012_service_word_outside_pending_scope_does_not_trigger_matcher(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert len(service_catalog_codes()) == 37
    await seed_capture(sessionmaker_fixture, pending_action=None)
    service_calls: list[str] = []

    async def general_classifier(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification_without_entities("UNKNOWN")

    async def services_classifier(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[str]:
        service_calls.append(message_text)
        return ["VENUE"]

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", general_classifier)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", services_classifier)

    await send_turn(sessionmaker_fixture, message_id="tc-svc-012", text="espacio")

    assert service_calls == []
    assert await requested_service_values(sessionmaker_fixture) == []


def test_tc_svc_013_legacy_free_text_degrades_and_emits_structlog_warning() -> None:
    legacy_value = "Solo el Espacio Premium"

    with structlog.testing.capture_logs() as logs:
        summary = compose_requested_services_summary([legacy_value])

    assert summary == "el espacio premium"
    assert legacy_value not in summary
    warnings = [
        record
        for record in logs
        if record.get("event") == "requested_service_presentation_fallback"
    ]
    assert len(warnings) == 1
    assert warnings[0]["legacy_value"] == legacy_value


@pytest.mark.asyncio
async def test_tc_svc_014_deterministic_capture_stores_only_catalog_codes(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_capture(sessionmaker_fixture)
    await install_no_llm_allowed(monkeypatch)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-svc-014",
        text="espacio y decoracion",
    )

    values = await requested_service_values(sessionmaker_fixture)
    assert values == ["VENUE", "DECORATION"]
    assert not {"espacio", "decoracion", "espacio y decoracion"}.intersection(values)


def test_tc_svc_015_other_has_no_deterministic_alias() -> None:
    codes = service_catalog_codes()

    assert "OTHER" in codes
    assert service_aliases("OTHER") == ()
    assert all(
        alias
        for code in codes
        if code != "OTHER"
        for alias in service_aliases(code)
    )
