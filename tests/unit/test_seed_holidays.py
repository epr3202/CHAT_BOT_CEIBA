from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.appointment.models import Holiday
from scripts.seed_holidays import colombian_holiday_entries, seed_colombian_holidays
from tests.integration.helpers import cleanup_test_environment, reset_test_database


async def test_colombian_holiday_seed_includes_emiliani_transfer() -> None:
    entries = colombian_holiday_entries([2026])

    assert date(2026, 8, 17) in entries
    assert date(2026, 8, 15) not in entries


async def test_seed_colombian_holidays_is_idempotent_and_preserves_manual_rows() -> None:
    sessionmaker = await reset_test_database()
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                Holiday(
                    holiday_date=date(2026, 8, 17),
                    name="Cierre manual",
                    source="MANUAL",
                )
            )

    first_count = await seed_colombian_holidays(sessionmaker, years=[2026])
    second_count = await seed_colombian_holidays(sessionmaker, years=[2026])

    async with sessionmaker() as session:
        manual = await session.scalar(
            select(Holiday).where(Holiday.holiday_date == date(2026, 8, 17))
        )
        all_rows = (await session.scalars(select(Holiday))).all()

    assert first_count > 0
    assert second_count == 0
    assert manual is not None
    assert manual.name == "Cierre manual"
    assert manual.source == "MANUAL"
    assert len({holiday.holiday_date for holiday in all_rows}) == len(all_rows)
    await cleanup_test_environment()
