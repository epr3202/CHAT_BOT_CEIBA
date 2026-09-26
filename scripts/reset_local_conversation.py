from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.admin.conversation_reset import (
    RESET_ACTION as RESET_ACTION,
)
from app.admin.conversation_reset import (
    ResetSummary as ResetSummary,
)
from app.admin.conversation_reset import (
    reset_conversation_by_phone,
)
from app.config.database import create_sessionmaker
from app.config.settings import get_settings

DEFAULT_PHONE = "+573016976242"
RESET_ACTOR = "LOCAL_SCRIPT"
RESET_REASON = "Local test reset requested from reset_local_conversation.py"


async def reset_local_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    raw_phone_number: str,
    *,
    dry_run: bool = True,
    request_id: str | None = None,
    allow_production_phone: bool = False,
) -> ResetSummary:
    # Production permission and explicit phone are checked by async_main before
    # opening the database; keep this callable's existing interface for tooling.
    async with sessionmaker() as session, session.begin():
        return await reset_conversation_by_phone(
            session, raw_phone_number=raw_phone_number, dry_run=dry_run,
            actor=RESET_ACTOR, reason=RESET_REASON,
            request_id=request_id or f"local-reset-{uuid.uuid4()}",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset a local test phone without deleting append-only history."
    )
    parser.add_argument(
        "--phone",
        help=f"Phone number to reset. Defaults to {DEFAULT_PHONE} outside production.",
    )
    parser.add_argument(
        "--allow-production-phone",
        action="store_true",
        help="Allow resetting one explicitly provided phone when ENVIRONMENT=production.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes. Without this flag the script only prints a dry run.",
    )
    mode.add_argument("--dry-run", action="store_false", dest="execute",
                      help="Preview only (the default).")
    parser.set_defaults(execute=False)
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
    for field, value in asdict(summary).items():
        if field not in {"phone_number", "dry_run"}:
            print(f"{field}={value}")


async def async_main() -> None:
    args = parse_args()
    settings = get_settings()
    if settings.environment == "production" and not args.allow_production_phone:
        raise SystemExit(
            "Refusing to reset a production conversation without --allow-production-phone."
        )
    if settings.environment == "production" and args.phone is None:
        raise SystemExit("Production resets require an explicit --phone.")
    phone_number = args.phone or DEFAULT_PHONE

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
            phone_number,
            dry_run=not args.execute,
            allow_production_phone=args.allow_production_phone,
        )
        print_summary(summary)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
