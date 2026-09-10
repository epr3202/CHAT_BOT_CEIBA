"""Current human assignment, locked with the mutation's existing transaction."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.models import Conversation
from app.handoff.models import Handoff


def assignment_conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="Human assignment is not consistent")


async def lock_human_case(
    session: AsyncSession, *, conversation_id: int | None = None, handoff_id: int | None = None,
) -> tuple[Conversation, list[Handoff]]:
    """Always Conversation -> open Handoff IDs; the initial locator cannot authorize."""
    if handoff_id is not None:
        conversation_id = await session.scalar(
            select(Handoff.conversation_id).where(Handoff.id == handoff_id),
        )
        if conversation_id is None:
            raise HTTPException(status_code=404, detail="Handoff not found")
    conversation = await session.get(
        Conversation, conversation_id, with_for_update=True, populate_existing=True,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    cases = list((await session.scalars(
        select(Handoff).where(
            Handoff.conversation_id == conversation.id,
            Handoff.status.in_(("PENDING", "TAKEN")),
        ).order_by(Handoff.id).with_for_update().execution_options(populate_existing=True),
    )).all())
    # Recheck after both locks, including a relation changed while the locator waited.
    if handoff_id is not None and (len(cases) != 1 or cases[0].id != handoff_id):
        raise assignment_conflict()
    if any(case.conversation_id != conversation.id for case in cases):
        raise assignment_conflict()
    return conversation, cases


def require_case_owner(
    conversation: Conversation, cases: list[Handoff], agent_id: int,
) -> Handoff:
    if (
        conversation.state != "HUMAN_ACTIVE" or conversation.bot_enabled
        or len(cases) != 1 or cases[0].status != "TAKEN"
        or conversation.assigned_agent_id is None or cases[0].assigned_agent_id is None
        or conversation.assigned_agent_id != cases[0].assigned_agent_id
    ):
        raise assignment_conflict()
    if conversation.assigned_agent_id != agent_id:
        raise HTTPException(status_code=403, detail="Case mutation is not permitted")
    return cases[0]


def require_pending_case(conversation: Conversation, cases: list[Handoff]) -> Handoff:
    # WAITING_FOR_HUMAN itself suspends automation; takeover sets bot_enabled=False.
    if (
        conversation.state != "WAITING_FOR_HUMAN"
        or conversation.assigned_agent_id is not None or len(cases) != 1
        or cases[0].status != "PENDING" or cases[0].assigned_agent_id is not None
        or cases[0].assigned_to is not None
    ):
        raise assignment_conflict()
    return cases[0]


def require_unassigned_conversation(conversation: Conversation, cases: list[Handoff]) -> None:
    if conversation.assigned_agent_id is not None or cases:
        raise assignment_conflict()
