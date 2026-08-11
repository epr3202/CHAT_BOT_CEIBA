from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import KnowledgeSeedEntry, iter_seed_entries


async def load_knowledge_entries(
    sessionmaker: async_sessionmaker[AsyncSession],
    entries: list[KnowledgeSeedEntry],
) -> int:
    inserted = 0
    async with sessionmaker() as session:
        async with session.begin():
            for entry in entries:
                existing = await session.scalar(
                    select(KnowledgeEntry)
                    .where(
                        KnowledgeEntry.code == entry.code,
                        KnowledgeEntry.version == entry.version,
                    )
                    .limit(1)
                )
                if existing is not None:
                    continue

                older_entries = await session.scalars(
                    select(KnowledgeEntry).where(
                        KnowledgeEntry.code == entry.code,
                        KnowledgeEntry.version < entry.version,
                        KnowledgeEntry.status != "INACTIVE",
                    )
                )
                for older_entry in older_entries.all():
                    older_entry.status = "INACTIVE"
                    older_entry.updated_at_version = datetime.now(UTC)

                session.add(
                    KnowledgeEntry(
                        code=entry.code,
                        category=entry.category,
                        question_summary=entry.question_summary,
                        answer_template=entry.answer_template,
                        allowed_variables=entry.allowed_variables,
                        version=entry.version,
                        status=entry.status,
                    )
                )
                inserted += 1
    return inserted


async def main() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    try:
        sessionmaker = create_sessionmaker(engine)
        entries = list(iter_seed_entries())
        inserted = await load_knowledge_entries(sessionmaker, entries)
        print(f"knowledge entries inserted: {inserted}")
        print(f"knowledge entries present in seed: {len(entries)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
