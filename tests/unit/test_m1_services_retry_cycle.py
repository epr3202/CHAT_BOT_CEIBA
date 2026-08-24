from __future__ import annotations

from typing import Any

import pytest

from app.ai.schemas import IntentClassification
from app.channel.models import Message
from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.orchestrator import service as orchestrator
from app.orchestrator.service import OrchestrationInput


def unknown_classification() -> IntentClassification:
    return IntentClassification(
        primary_intent="UNKNOWN",
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
        reasoning_code="TC_M1_SERVICES_RETRY",
    )


@pytest.mark.asyncio
async def test_reinstalling_collect_services_starts_a_fresh_two_failure_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=1,
        customer_id=1,
        channel=Channel.WHATSAPP,
        state=ConversationState.COLLECTING_EVENT_DATA,
        pending_action="COLLECT_SERVICES",
        pending_fields=["requested_services"],
        services_failed_understanding_count=1,
    )
    customer = Customer(id=1, phone_number="+573001112233")
    inbound_message = Message(
        id=1,
        external_message_id="wamid.m1.services-retry",
        conversation_id=1,
        customer_id=1,
        channel=Channel.WHATSAPP,
        direction="INBOUND",
        message_type="text",
        content={"text": {"body": "no sé cómo explicarlo"}},
    )
    orchestration_input = OrchestrationInput(
        conversation=conversation,
        customer=customer,
        inbound_message=inbound_message,
        message_text="no sé cómo explicarlo",
    )
    response_codes: list[str] = []
    applied_services: list[list[str]] = []
    handoff_reasons: list[str] = []

    async def fake_enqueue_template(
        _session: Any,
        _knowledge_sessionmaker: Any,
        _conversation: Conversation,
        _customer: Customer,
        _inbound_message: Message,
        response_code: str,
        _variables: dict[str, Any],
    ) -> None:
        response_codes.append(response_code)

    async def fake_get_or_create_capture_models(*_args: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return object(), object()

    def fake_apply_requested_services(
        _session: Any,
        _event: Any,
        entity: Any,
        _request_id: Any,
    ) -> None:
        applied_services.append(entity.normalized_value)

    async def fake_create_handoff_and_pause(
        _session: Any,
        _settings: Any,
        _knowledge_sessionmaker: Any,
        received_input: OrchestrationInput,
        _classification: IntentClassification,
        *,
        reason: str,
        priority: str,
        detail: str | None = None,
        response_code_override: str | None = None,
    ) -> None:
        assert priority == "NORMAL"
        assert detail is not None
        assert response_code_override is None
        handoff_reasons.append(reason)
        orchestrator.set_pending_action(received_input.conversation, "WAIT_FOR_HUMAN")
        received_input.conversation.services_failed_understanding_count = 0

    monkeypatch.setattr(orchestrator, "enqueue_template", fake_enqueue_template)
    monkeypatch.setattr(
        orchestrator,
        "get_or_create_capture_models",
        fake_get_or_create_capture_models,
    )
    monkeypatch.setattr(orchestrator, "apply_requested_services", fake_apply_requested_services)
    monkeypatch.setattr(
        orchestrator,
        "create_handoff_and_pause",
        fake_create_handoff_and_pause,
    )

    orchestrator.set_pending_action(conversation, "COLLECT_SERVICES")
    assert conversation.services_failed_understanding_count == 0

    await orchestrator.handle_failed_services_resolution(
        object(),
        object(),
        object(),
        orchestration_input,
        unknown_classification(),
    )

    assert response_codes == ["RESP-SERVICES-RETRY-001"]
    assert applied_services == []
    assert handoff_reasons == []
    assert conversation.pending_action == "COLLECT_SERVICES"
    assert conversation.services_failed_understanding_count == 1

    await orchestrator.handle_failed_services_resolution(
        object(),
        object(),
        object(),
        orchestration_input,
        unknown_classification(),
    )

    assert response_codes == ["RESP-SERVICES-RETRY-001"]
    assert applied_services == [["OTHER"]]
    assert handoff_reasons == ["OTHER"]
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.services_failed_understanding_count == 0
