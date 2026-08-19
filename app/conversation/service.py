from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.conversation.models import Conversation
from app.conversation.states import ConversationState

ALLOWED_TRANSITIONS: dict[ConversationState, frozenset[ConversationState]] = {
    ConversationState.NEW: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.CLOSED,
        }
    ),
    ConversationState.BOT_ACTIVE: frozenset(
        {
            ConversationState.ANSWERING_INFORMATION,
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.RESOLVED,
            ConversationState.CLOSED,
        }
    ),
    ConversationState.ANSWERING_INFORMATION: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.RESOLVED,
        }
    ),
    ConversationState.COLLECTING_EVENT_DATA: frozenset(
        {
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.ANSWERING_INFORMATION,
            ConversationState.QUOTE_REQUEST_READY,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.RESOLVED,
        }
    ),
    ConversationState.QUOTE_REQUEST_READY: frozenset(
        {
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.BOT_ACTIVE,
            ConversationState.RESOLVED,
        }
    ),
    ConversationState.WAITING_FOR_APPOINTMENT_DATE: frozenset(
        {
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            ConversationState.ANSWERING_INFORMATION,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.BOT_ACTIVE,
        }
    ),
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION: frozenset(
        {
            ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.ANSWERING_INFORMATION,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.BOT_ACTIVE,
        }
    ),
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION: frozenset(
        {
            ConversationState.APPOINTMENT_CONFIRMED,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            ConversationState.BOT_ACTIVE,
            ConversationState.WAITING_FOR_HUMAN,
        }
    ),
    ConversationState.APPOINTMENT_CONFIRMED: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
            ConversationState.WAITING_FOR_HUMAN,
            ConversationState.RESOLVED,
        }
    ),
    ConversationState.WAITING_FOR_HUMAN: frozenset(
        {
            ConversationState.HUMAN_ACTIVE,
            ConversationState.BOT_ACTIVE,
            ConversationState.RESOLVED,
            ConversationState.CLOSED,
        }
    ),
    ConversationState.HUMAN_ACTIVE: frozenset(
        {
            ConversationState.RETURNED_TO_BOT,
            ConversationState.RESOLVED,
            ConversationState.CLOSED,
            ConversationState.WAITING_FOR_HUMAN,
        }
    ),
    ConversationState.RETURNED_TO_BOT: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            ConversationState.RESOLVED,
            ConversationState.WAITING_FOR_HUMAN,
        }
    ),
    ConversationState.RESOLVED: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.HUMAN_ACTIVE,
            ConversationState.CLOSED,
        }
    ),
    ConversationState.CLOSED: frozenset(
        {
            ConversationState.BOT_ACTIVE,
            ConversationState.HUMAN_ACTIVE,
        }
    ),
}


class InvalidStateTransition(ValueError):
    pass


def coerce_conversation_state(state: ConversationState | str) -> ConversationState:
    if isinstance(state, ConversationState):
        return state
    return ConversationState(state)


async def transition_conversation(
    session: AsyncSession,
    conversation: Conversation,
    new_state: ConversationState | str,
    actor: str,
    reason: str | None = None,
) -> None:
    old_state = coerce_conversation_state(conversation.state)
    target_state = coerce_conversation_state(new_state)

    if target_state not in ALLOWED_TRANSITIONS[old_state]:
        raise InvalidStateTransition(f"{old_state.value} -> {target_state.value}")

    conversation.state = target_state.value
    transition_reason = reason or f"{old_state.value} -> {target_state.value}"
    session.add(
        AuditEvent(
            actor=actor,
            action="CONVERSATION_STATE_TRANSITION",
            entity="conversation",
            old_value={"conversation_id": conversation.id, "state": old_state.value},
            new_value={"conversation_id": conversation.id, "state": target_state.value},
            reason=transition_reason,
            request_id=None,
        )
    )
