from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.audit.models import AuditEvent
from app.channel.inbound import process_webhook_event
from app.channel.inbox import lock_context, retire
from app.channel.models import InboxJob, Message, WebhookEvent
from app.config.database import create_engine, create_sessionmaker
from app.config.logging import configure_logging
from app.config.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reprocess stored webhook inbox events.")
    parser.add_argument(
        "--status",
        choices=("RECEIVED", "FAILED", "PREPARED", "REVIEW", "EXHAUSTED"),
        default="RECEIVED",
        help="Webhook event status to reprocess.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of events.")
    parser.add_argument(
        "--event-id", type=int, help="Select one event, respecting durable ownership."
    )
    parser.add_argument(
        "--adopt-unmaterialized",
        action="store_true",
        help="Only with --event-id: admit a legacy RECEIVED/FAILED event with no stored messages.",
    )
    parser.add_argument(
        "--retry-job",
        type=int,
        help="Explicitly grant another retry budget to one NEW failed local job.",
    )
    parser.add_argument("--reason", help="Required technical reason for a manual retry.")
    parser.add_argument(
        "--inventory-legacy",
        action="store_true",
        help="Count ambiguous historical records without replay or backfill.",
    )
    return parser.parse_args()


async def list_event_ids(
    sessionmaker: async_sessionmaker[AsyncSession],
    status: str,
    limit: int,
) -> list[int]:
    async with sessionmaker() as session:
        result = await session.scalars(
            select(WebhookEvent.id)
            .where(WebhookEvent.status == status)
            .order_by(WebhookEvent.created_at)
            .limit(limit)
        )
        return list(result.all())


async def main_async() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.environment)
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)

    try:
        if not 1 <= args.limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if args.inventory_legacy:
            result = await legacy_inventory(sessionmaker)
        elif args.retry_job is not None:
            result = {"retry_granted": await retry_job(sessionmaker, args.retry_job, args.reason)}
        else:
            if args.adopt_unmaterialized:
                if args.event_id is None:
                    raise ValueError("Adoption requires an explicit event ID")
                await adopt_unmaterialized(sessionmaker, args.event_id)
            ids = (
                [args.event_id]
                if args.event_id is not None
                else await list_event_ids(sessionmaker, args.status, args.limit)
            )
            result = await reprocess_events(sessionmaker, ids)
        print(json.dumps(result, sort_keys=True))
    finally:
        await engine.dispose()


async def reprocess_events(
    sessionmaker: async_sessionmaker[AsyncSession], ids: list[int]
) -> dict[str, int]:
    from collections import Counter

    counts: Counter[str] = Counter()
    for event_id in dict.fromkeys(ids):
        async with sessionmaker() as session:
            event = await session.get(WebhookEvent, event_id)
            if event is None or event.status == "PROCESSED":
                counts["SKIPPED_MISSING_OR_COMPLETED"] += 1
                continue
        counts.update(await process_webhook_event(event_id, sessionmaker))
    return dict(counts)


async def legacy_inventory(sessionmaker: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    from sqlalchemy import func

    async with sessionmaker() as session:
        return {
            "events_unproven": await session.scalar(
                select(func.count())
                .select_from(WebhookEvent)
                .where(WebhookEvent.intake_version.is_(None))
            )
            or 0,
            "messages_unproven": await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.direction == "INBOUND", ~Message.id.in_(select(InboxJob.message_id)))
            )
            or 0,
        }


async def adopt_unmaterialized(
    sessionmaker: async_sessionmaker[AsyncSession], event_id: int
) -> None:
    from app.channel.inbound import extract_inbound_messages

    async with sessionmaker() as session, session.begin():
        event = await session.get(WebhookEvent, event_id, with_for_update=True)
        if (
            event is None
            or event.intake_version is not None
            or event.status not in {"RECEIVED", "FAILED"}
        ):
            raise ValueError("Only a selected unproven RECEIVED/FAILED event can be admitted")
        ids = [m.external_message_id for m in extract_inbound_messages(event.payload)]
        if await session.scalar(
            select(Message.id).where(Message.external_message_id.in_(ids)).limit(1)
        ):
            raise ValueError("Stored historical message requires reconciliation, not replay")
        event.intake_version, event.status, event.next_attempt_at = 2, "RECEIVED", None


async def retry_job(
    sessionmaker: async_sessionmaker[AsyncSession], job_id: int, reason: str | None
) -> bool:
    if not reason or len(reason) > 128:
        raise ValueError("A technical reason of 1 to 128 characters is required")
    async with sessionmaker() as session, session.begin():
        conversation_id = await session.scalar(
            select(InboxJob.conversation_id).where(InboxJob.id == job_id)
        )
        if conversation_id is None:
            return False
        await lock_context(session, conversation_id)
        job = await session.get(InboxJob, job_id, with_for_update=True)
        if job.status != "FAILED" or job.origin != "NEW" or job.external_operation is not None:
            raise ValueError(
                "Only exhausted local NEW work can be retried; REVIEW needs reconciliation"
            )
        session.add(
            AuditEvent(
                actor="SYSTEM",
                action="INBOX_MANUAL_RETRY",
                entity="inbox_job",
                old_value={"job_id": job.id, "status": job.status, "attempts": job.attempts},
                new_value={"job_id": job.id, "status": "PENDING", "attempts": 0},
                reason=reason,
            )
        )
        retire(job, "PENDING")
        job.attempts = 0
        external_id = await session.scalar(
            select(Message.external_message_id).where(Message.id == job.message_id)
        )
        events = await session.scalars(
            select(WebhookEvent)
            .where(
                WebhookEvent.status == "EXHAUSTED",
                WebhookEvent.intake_version == 2,
                WebhookEvent.payload.contains(
                    {"entry": [{"changes": [{"value": {"messages": [{"id": external_id}]}}]}]}
                ),
            )
            .with_for_update()
        )
        for event in events:
            event.status, event.error, event.next_attempt_at = "PREPARED", None, None
    return True


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
