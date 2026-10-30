"""Seed the disposable frontend test database; never use a production URL."""

import asyncio
import os
from datetime import time

from sqlalchemy import select

from app.plan.models import Plan
from scripts.load_plans import load_plans
from tests.frontend.seed_spanish_labels import seed_spanish_labels
from tests.integration.helpers import (
    assert_safe_test_database_url,
    bootstrap_agent,
    database_sessionmaker,
)


async def main() -> None:
    assert_safe_test_database_url(os.environ["TEST_DATABASE_URL"])
    # Production startup now verifies LODGING_PLAN_CODE. Populate that real
    # dependency in this disposable DB, which was migrated before any plans existed.
    async for sm in database_sessionmaker():
        await load_plans(sm)
        async with sm.begin() as session:
            plan = await session.scalar(select(Plan).where(Plan.code == "REFUGIO_DOS"))
            plan.overnight, plan.checkin_from, plan.checkout_time = True, time(15), time(11)
    await bootstrap_agent(name="Frontend Test Admin", document_id="90000000", role="ADMIN")
    await seed_spanish_labels()


if __name__ == "__main__":
    asyncio.run(main())
