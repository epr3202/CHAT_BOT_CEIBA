from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.config.settings import get_settings
from tests.integration.helpers import app_client, bootstrap_agent, configure_test_environment


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "true")
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", "true")
    get_settings.cache_clear()
    await bootstrap_agent(name="Admin avisos", document_id="90000000", role="ADMIN")
    await bootstrap_agent(name="Asesor avisos", document_id="80000000", role="AGENT")
    async for instance in app_client():
        yield instance
    get_settings.cache_clear()
