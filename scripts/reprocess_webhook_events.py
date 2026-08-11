from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.channel.inbound import process_webhook_event
from app.channel.models import WebhookEvent
from app.config.database import create_engine, create_sessionmaker
from app.config.logging import configure_logging
from app.config.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reprocess stored webhook inbox events.")
    parser.add_argument(
        "--status",
        choices=("RECEIVED", "FAILED"),
        default="RECEIVED",
        help="Webhook event status to reprocess.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of events.")
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
        event_ids = await list_event_ids(sessionmaker, args.status, args.limit)
        for event_id in event_ids:
            await process_webhook_event(event_id, sessionmaker)
        print(f"Reprocessed {len(event_ids)} webhook event(s).")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
