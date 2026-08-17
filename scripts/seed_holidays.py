from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.appointment.models import Holiday
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings


def default_seed_years(today: date | None = None) -> list[int]:
    today = today or date.today()
    return [today.year, today.year + 1, today.year + 2]


def colombian_holiday_entries(years: Iterable[int]) -> dict[date, str]:
    calendar = holidays.country_holidays("CO", years=sorted(set(years)), observed=True)
    return {holiday_date: str(name) for holiday_date, name in calendar.items()}


async def seed_colombian_holidays(
    sessionmaker: async_sessionmaker[AsyncSession],
    years: Iterable[int] | None = None,
) -> int:
    entries = colombian_holiday_entries(years or default_seed_years())
    upserted = 0
    async with sessionmaker() as session:
        async with session.begin():
            for holiday_date, name in sorted(entries.items()):
                existing = await session.scalar(
                    select(Holiday).where(Holiday.holiday_date == holiday_date).limit(1)
                )
                if existing is None:
                    session.add(
                        Holiday(
                            holiday_date=holiday_date,
                            name=name,
                            source="SEEDED",
                        )
                    )
                    upserted += 1
                    continue

                if existing.source == "MANUAL":
                    continue

                if existing.name != name or existing.source != "SEEDED":
                    existing.name = name
                    existing.source = "SEEDED"
                    existing.updated_at = datetime.now(UTC)
                    upserted += 1
    return upserted


async def main() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    try:
        sessionmaker = create_sessionmaker(engine)
        years = default_seed_years()
        upserted = await seed_colombian_holidays(sessionmaker, years=years)
        print(f"holiday years seeded: {','.join(str(year) for year in years)}")
        print(f"holiday rows inserted or updated: {upserted}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
