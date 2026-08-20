from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.config.database import create_sessionmaker
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import KnowledgeSeedEntry, iter_seed_entries

SyncAction = Literal["CREATE", "BUMP", "UNCHANGED"]


@dataclass(frozen=True)
class KnowledgeSyncPlan:
    code: str
    action: SyncAction
    new_version: int | None
    answer_preview: str
    changed_fields: tuple[str, ...]


def changed_knowledge_fields(
    seed: KnowledgeSeedEntry,
    latest: KnowledgeEntry,
) -> tuple[str, ...]:
    fields = (
        "answer_template",
        "question_summary",
        "category",
        "allowed_variables",
    )
    return tuple(
        field
        for field in fields
        if getattr(seed, field) != getattr(latest, field)
    )


def next_knowledge_version(existing: Sequence[KnowledgeEntry]) -> int:
    return max((entry.version for entry in existing), default=0) + 1


def plan_knowledge_sync(
    seed: KnowledgeSeedEntry,
    existing: Sequence[KnowledgeEntry],
) -> KnowledgeSyncPlan:
    preview = " ".join(seed.answer_template.split())[:60]
    if not existing:
        return KnowledgeSyncPlan(
            code=seed.code,
            action="CREATE",
            new_version=1,
            answer_preview=preview,
            changed_fields=(
                "answer_template",
                "question_summary",
                "category",
                "allowed_variables",
            ),
        )

    latest = max(existing, key=lambda entry: entry.version)
    changed_fields = changed_knowledge_fields(seed, latest)
    if not changed_fields:
        return KnowledgeSyncPlan(
            code=seed.code,
            action="UNCHANGED",
            new_version=None,
            answer_preview=preview,
            changed_fields=(),
        )
    return KnowledgeSyncPlan(
        code=seed.code,
        action="BUMP",
        new_version=next_knowledge_version(existing),
        answer_preview=preview,
        changed_fields=changed_fields,
    )


async def sync_knowledge_versions(
    sessionmaker: async_sessionmaker[AsyncSession],
    entries: Sequence[KnowledgeSeedEntry],
    *,
    execute: bool = False,
) -> list[KnowledgeSyncPlan]:
    plans: list[KnowledgeSyncPlan] = []
    async with sessionmaker() as session:
        async with session.begin():
            for seed in entries:
                query = (
                    select(KnowledgeEntry)
                    .where(KnowledgeEntry.code == seed.code)
                    .order_by(KnowledgeEntry.version)
                )
                if execute:
                    query = query.with_for_update()
                existing = list((await session.scalars(query)).all())
                plan = plan_knowledge_sync(seed, existing)
                plans.append(plan)
                if not execute or plan.new_version is None:
                    continue

                updated_at = datetime.now(UTC)
                for previous in existing:
                    if previous.status != "INACTIVE":
                        previous.status = "INACTIVE"
                        previous.updated_at_version = updated_at

                session.add(
                    KnowledgeEntry(
                        code=seed.code,
                        category=seed.category,
                        question_summary=seed.question_summary,
                        answer_template=seed.answer_template,
                        allowed_variables=seed.allowed_variables,
                        version=plan.new_version,
                        status=seed.status,
                    )
                )
    return plans


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize versioned knowledge from approved responses."
    )
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


def print_plans(plans: Sequence[KnowledgeSyncPlan], *, execute: bool) -> None:
    mode = "EXECUTED" if execute else "DRY RUN"
    print(f"{mode}: knowledge codes={len(plans)}")
    for plan in plans:
        new_version = str(plan.new_version) if plan.new_version is not None else "-"
        print(
            f"{plan.code}: action={plan.action} new_version={new_version} "
            f"preview={plan.answer_preview!r}"
        )


async def async_main() -> None:
    args = parse_args()
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to sync knowledge when ENVIRONMENT=production.")

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
        plans = await sync_knowledge_versions(
            sessionmaker,
            list(iter_seed_entries()),
            execute=args.execute,
        )
        print_plans(plans, execute=args.execute)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
