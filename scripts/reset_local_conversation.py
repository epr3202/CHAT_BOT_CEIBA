from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.audit.models import AuditEvent
from app.channel.inbound import normalize_phone_number
from app.channel.models import Outbox
from app.config.database import create_sessionmaker
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff

DEFAULT_PHONE = "+573016976242"
RESET_ACTOR = "LOCAL_SCRIPT"
RESET_ACTION = "LOCAL_CONVERSATION_RESET"
RESET_REASON = "Local test reset requested from reset_local_conversation.py"


@dataclass(frozen=True)
class ResetSummary:
    phone_number: str
    customer_id: int | None
    conversations_found: int
    conversations_closed: int
    active_lead_links_cleared: int
    handoffs_resolved: int
    pending_outbox_failed: int
    customer_name_cleared: bool
    audit_events_added: int
    dry_run: bool


async def reset_local_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    raw_phone_number: str,
    *,
    dry_run: bool = True,
    request_id: str | None = None,
) -> ResetSummary:
    phone_number = normalize_phone_number(raw_phone_number)
    request_id = request_id or f"local-reset-{uuid.uuid4()}"

    async with sessionmaker() as session:
        async with session.begin():
            customer = await session.scalar(
                select(Customer).where(Customer.phone_number == phone_number).with_for_update()
            )
            if customer is None:
                return ResetSummary(
                    phone_number=phone_number,
                    customer_id=None,
                    conversations_found=0,
                    conversations_closed=0,
                    active_lead_links_cleared=0,
                    handoffs_resolved=0,
                    pending_outbox_failed=0,
                    customer_name_cleared=False,
                    audit_events_added=0,
                    dry_run=dry_run,
                )

            conversations = (
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.customer_id == customer.id)
                    .order_by(Conversation.id)
                    .with_for_update()
                )
            ).all()
            conversation_ids = [conversation.id for conversation in conversations]
            handoffs = (
                await session.scalars(
                    select(Handoff)
                    .where(
                        Handoff.conversation_id.in_(conversation_ids),
                        Handoff.status != "RESOLVED",
                    )
                    .order_by(Handoff.id)
                    .with_for_update()
                )
            ).all()
            outbox_items = (
                await session.scalars(
                    select(Outbox)
                    .where(
                        Outbox.recipient_phone_number == phone_number,
                        Outbox.status.in_(("PENDING", "SENDING")),
                    )
                    .order_by(Outbox.id)
                    .with_for_update()
                )
            ).all()

            conversations_to_close = [
                conversation
                for conversation in conversations
                if conversation.state != ConversationState.CLOSED.value
            ]
            conversations_with_active_lead = [
                conversation
                for conversation in conversations
                if conversation.active_lead_id is not None
            ]
            customer_name_cleared = customer.full_name is not None

            summary = ResetSummary(
                phone_number=phone_number,
                customer_id=customer.id,
                conversations_found=len(conversations),
                conversations_closed=len(conversations_to_close),
                active_lead_links_cleared=len(conversations_with_active_lead),
                handoffs_resolved=len(handoffs),
                pending_outbox_failed=len(outbox_items),
                customer_name_cleared=customer_name_cleared,
                audit_events_added=0 if dry_run else 1,
                dry_run=dry_run,
            )
            if dry_run:
                return summary

            old_value = reset_snapshot(customer, conversations, handoffs, outbox_items)
            if customer_name_cleared:
                customer.full_name = None

            for conversation in conversations:
                conversation.state = ConversationState.CLOSED.value
                conversation.pending_action = None
                conversation.pending_fields = []
                conversation.pending_confirmation = None
                conversation.last_question_code = None
                conversation.last_intent = None
                conversation.failed_understanding_count = 0
                conversation.bot_enabled = True
                conversation.assigned_agent_id = None
                conversation.active_lead_id = None

            for handoff in handoffs:
                handoff.status = "RESOLVED"
                handoff.assigned_to = None
                handoff.assigned_agent_id = None

            for outbox_item in outbox_items:
                outbox_item.status = "FAILED"
                outbox_item.last_error = "Cancelled by local conversation reset"
                outbox_item.claimed_at = None
                outbox_item.next_attempt_at = None

            session.add(
                AuditEvent(
                    actor=RESET_ACTOR,
                    action=RESET_ACTION,
                    entity="customer",
                    old_value=old_value,
                    new_value={
                        "phone_number": phone_number,
                        "customer_id": customer.id,
                        "conversation_ids": conversation_ids,
                        "conversation_state": ConversationState.CLOSED.value,
                        "full_name": None,
                        "active_lead_id": None,
                        "pending_outbox_status": "FAILED",
                    },
                    reason=RESET_REASON,
                    request_id=request_id,
                )
            )
            return summary


def reset_snapshot(
    customer: Customer,
    conversations: list[Conversation],
    handoffs: list[Handoff],
    outbox_items: list[Outbox],
) -> dict[str, Any]:
    return {
        "customer": {
            "id": customer.id,
            "phone_number": customer.phone_number,
            "full_name": customer.full_name,
        },
        "conversations": [
            {
                "id": conversation.id,
                "state": conversation.state,
                "active_lead_id": str(conversation.active_lead_id)
                if conversation.active_lead_id is not None
                else None,
                "bot_enabled": conversation.bot_enabled,
                "assigned_agent_id": conversation.assigned_agent_id,
            }
            for conversation in conversations
        ],
        "handoffs": [
            {
                "id": handoff.id,
                "conversation_id": handoff.conversation_id,
                "status": handoff.status,
                "assigned_to": handoff.assigned_to,
                "assigned_agent_id": handoff.assigned_agent_id,
            }
            for handoff in handoffs
        ],
        "outbox": [
            {
                "id": outbox_item.id,
                "conversation_id": outbox_item.conversation_id,
                "status": outbox_item.status,
            }
            for outbox_item in outbox_items
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset a local test phone without deleting append-only history."
    )
    parser.add_argument("--phone", default=DEFAULT_PHONE, help="Phone number to reset.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes. Without this flag the script only prints a dry run.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
        help="Database connection timeout in seconds.",
    )
    return parser.parse_args()


def print_summary(summary: ResetSummary) -> None:
    mode = "DRY RUN" if summary.dry_run else "EXECUTED"
    print(f"{mode}: phone={summary.phone_number}")
    if summary.customer_id is None:
        print("No customer found for this phone.")
        return
    print(f"customer_id={summary.customer_id}")
    print(f"conversations_found={summary.conversations_found}")
    print(f"conversations_closed={summary.conversations_closed}")
    print(f"active_lead_links_cleared={summary.active_lead_links_cleared}")
    print(f"handoffs_resolved={summary.handoffs_resolved}")
    print(f"pending_outbox_failed={summary.pending_outbox_failed}")
    print(f"customer_name_cleared={summary.customer_name_cleared}")
    print(f"audit_events_added={summary.audit_events_added}")


async def async_main() -> None:
    args = parse_args()
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to reset conversations when ENVIRONMENT=production.")

    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={
            "server_settings": {"timezone": "UTC"},
            "timeout": args.connect_timeout,
        },
    )
    try:
        sessionmaker = create_sessionmaker(engine)
        summary = await reset_local_conversation(
            sessionmaker,
            args.phone,
            dry_run=not args.execute,
        )
        print_summary(summary)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
