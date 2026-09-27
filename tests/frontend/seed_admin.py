"""Seed the disposable frontend test database; never use a production URL."""

import asyncio
import os

from tests.frontend.seed_spanish_labels import seed_spanish_labels
from tests.integration.helpers import assert_safe_test_database_url, bootstrap_agent


async def main() -> None:
    assert_safe_test_database_url(os.environ["TEST_DATABASE_URL"])
    await bootstrap_agent(name="Frontend Test Admin", document_id="90000000", role="ADMIN")
    await seed_spanish_labels()


if __name__ == "__main__":
    asyncio.run(main())
