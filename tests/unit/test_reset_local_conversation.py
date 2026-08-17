from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.channel.inbound import get_or_create_active_conversation
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.lead.models import Lead
from scripts.reset_local_conversation import RESET_ACTION, reset_local_conversation
from tests.integration.helpers import reset_test_database


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    sessionmaker = await reset_test_database()
    yield sessionmaker


async def seed_phone_state(
    sessionmaker: async_sessionmaker[AsyncSession],
    phone_number: str = "+573016976242",
) -> tuple[int, int]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone_number, full_name="Natalia Perez")
            session.add(customer)
            await session.flush()

            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP.value,
                lead_status="QUALIFYING",
            )
            session.add(lead)
            await session.flush()

            active_conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP.value,
                state=ConversationState.HUMAN_ACTIVE.value,
                last_intent="HUMAN_HANDOFF",
                pending_action="WAIT_FOR_HUMAN",
                pending_fields=["full_name"],
                pending_confirmation={"field": "full_name"},
                last_question_code="RESP-TEST",
                active_lead_id=lead.lead_id,
                failed_understanding_count=2,
                bot_enabled=False,
                assigned_agent_id=None,
            )
            closed_conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP.value,
                state=ConversationState.CLOSED.value,
                active_lead_id=lead.lead_id,
            )
            session.add_all([active_conversation, closed_conversation])
            await session.flush()

            inbound = Message(
                external_message_id="wamid.reset.in",
                conversation_id=active_conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP.value,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": "Hola"}},
            )
            outbound = Message(
                external_message_id="wamid.reset.out",
                conversation_id=active_conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP.value,
                direction="OUTBOUND",
                message_type="text",
                content={"text": {"body": "Hola, soy La Ceiba"}},
            )
            session.add_all([inbound, outbound])
            await session.flush()

            session.add_all(
                [
                    Outbox(
                        conversation_id=active_conversation.id,
                        message_id=outbound.id,
                        channel=Channel.WHATSAPP.value,
                        recipient_phone_number=phone_number,
                        payload={"text": {"body": "Pendiente"}},
                        status="PENDING",
                    ),
                    Handoff(
                        conversation_id=active_conversation.id,
                        status="TAKEN",
                        reason="MANUAL_TAKEOVER",
                        priority="NORMAL",
                        summary="Cliente en prueba local",
                        assigned_to="Asesor",
                    ),
                    AuditEvent(
                        actor="SYSTEM",
                        action="EXISTING_EVENT",
                        entity="conversation",
                        old_value=None,
                        new_value={"conversation_id": active_conversation.id},
                        reason="Existing audit event",
                        request_id="seed",
                    ),
                ]
            )
            return customer.id, active_conversation.id


async def count_rows(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_dry_run_does_not_change_state(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, conversation_id = await seed_phone_state(sessionmaker_fixture)

    summary = await reset_local_conversation(sessionmaker_fixture, "+573016976242")

    assert summary.dry_run is True
    assert summary.customer_id == customer_id
    assert summary.conversations_found == 2
    assert summary.conversations_closed == 1
    assert summary.audit_events_added == 0

    async with sessionmaker_fixture() as session:
        customer = await session.get(Customer, customer_id)
        conversation = await session.get(Conversation, conversation_id)
        assert customer is not None
        assert conversation is not None
        assert customer.full_name == "Natalia Perez"
        assert conversation.state == ConversationState.HUMAN_ACTIVE.value
        assert await count_rows(session, AuditEvent) == 1


async def test_execute_resets_phone_for_new_conversation_without_deleting_history(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    customer_id, old_conversation_id = await seed_phone_state(sessionmaker_fixture)

    summary = await reset_local_conversation(
        sessionmaker_fixture,
        "3016976242",
        dry_run=False,
        request_id="test-reset",
    )

    assert summary.phone_number == "+573016976242"
    assert summary.customer_id == customer_id
    assert summary.conversations_closed == 1
    assert summary.active_lead_links_cleared == 2
    assert summary.handoffs_resolved == 1
    assert summary.pending_outbox_failed == 1
    assert summary.customer_name_cleared is True
    assert summary.audit_events_added == 1

    async with sessionmaker_fixture() as session:
        customer = await session.get(Customer, customer_id)
        old_conversation = await session.get(Conversation, old_conversation_id)
        new_conversation = await get_or_create_active_conversation(session, customer)
        await session.flush()

        assert customer is not None
        assert old_conversation is not None
        assert customer.full_name is None
        assert old_conversation.state == ConversationState.CLOSED.value
        assert old_conversation.pending_action is None
        assert old_conversation.pending_fields == []
        assert old_conversation.pending_confirmation is None
        assert old_conversation.active_lead_id is None
        assert old_conversation.bot_enabled is True
        assert new_conversation.id != old_conversation_id
        assert new_conversation.state == ConversationState.BOT_ACTIVE.value

        assert await count_rows(session, Message) == 2
        assert await count_rows(session, AuditEvent) == 3

        handoff = await session.scalar(select(Handoff))
        outbox = await session.scalar(select(Outbox))
        reset_audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == RESET_ACTION)
        )
        assert handoff is not None
        assert outbox is not None
        assert reset_audit is not None
        assert handoff.status == "RESOLVED"
        assert handoff.assigned_to is None
        assert outbox.status == "FAILED"
        assert outbox.last_error == "Cancelled by local conversation reset"
        assert reset_audit.request_id == "test-reset"


async def test_unknown_phone_is_noop(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    summary = await reset_local_conversation(
        sessionmaker_fixture,
        "+573016976242",
        dry_run=False,
    )

    assert summary.customer_id is None
    assert summary.conversations_found == 0
    assert summary.audit_events_added == 0

    async with sessionmaker_fixture() as session:
        assert await count_rows(session, Customer) == 0
        assert await count_rows(session, AuditEvent) == 0
