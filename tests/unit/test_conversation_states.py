from unittest.mock import Mock

import pytest

from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.service import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    transition_conversation,
)
from app.conversation.states import ConversationState

SCOPE_STATES = [
    "NEW",
    "BOT_ACTIVE",
    "ANSWERING_INFORMATION",
    "COLLECTING_EVENT_DATA",
    "QUOTE_REQUEST_READY",
    "WAITING_FOR_APPOINTMENT_DATE",
    "WAITING_FOR_APPOINTMENT_SELECTION",
    "APPOINTMENT_PENDING_CONFIRMATION",
    "APPOINTMENT_CONFIRMED",
    "WAITING_FOR_HUMAN",
    "HUMAN_ACTIVE",
    "RETURNED_TO_BOT",
    "RESOLVED",
    "CLOSED",
]


def build_conversation(state: ConversationState) -> Conversation:
    conversation = Conversation(
        customer_id=1,
        channel=Channel.WHATSAPP,
        state=state,
    )
    conversation.id = 1
    return conversation


def test_conversation_state_enum_matches_scope_literal() -> None:
    assert [state.value for state in ConversationState] == SCOPE_STATES


@pytest.mark.asyncio
async def test_all_allowed_transitions_are_accepted() -> None:
    session = Mock()

    for old_state, target_states in ALLOWED_TRANSITIONS.items():
        for target_state in target_states:
            conversation = build_conversation(old_state)

            await transition_conversation(
                session,
                conversation,
                target_state,
                actor="SYSTEM",
                reason="unit test transition",
            )

            assert conversation.state == target_state.value


@pytest.mark.asyncio
async def test_unlisted_transitions_are_rejected() -> None:
    session = Mock()
    samples = [
        (ConversationState.NEW, ConversationState.APPOINTMENT_CONFIRMED),
        (ConversationState.BOT_ACTIVE, ConversationState.RETURNED_TO_BOT),
        (ConversationState.WAITING_FOR_HUMAN, ConversationState.APPOINTMENT_CONFIRMED),
    ]

    for old_state, target_state in samples:
        conversation = build_conversation(old_state)

        with pytest.raises(InvalidStateTransition):
            await transition_conversation(
                session,
                conversation,
                target_state,
                actor="SYSTEM",
                reason="invalid unit test transition",
            )
