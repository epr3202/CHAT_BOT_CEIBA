from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.admin import routes
from app.calendar.adapter import FakeCalendarAdapter
from app.config.settings import get_settings
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    configure_test_environment,
)


@pytest.fixture
def calendar(monkeypatch: pytest.MonkeyPatch) -> FakeCalendarAdapter:
    adapter = FakeCalendarAdapter()
    monkeypatch.setattr(routes, "get_calendar_adapter", lambda settings: adapter)
    return adapter


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    calendar: FakeCalendarAdapter,
) -> AsyncIterator[AsyncClient]:
    await configure_test_environment(monkeypatch)
    monkeypatch.setenv("GOOGLE_FREEBUSY_CALENDAR_IDS", "business-main")
    for key, value in {
        "BOOKING_BANK_NAME": "Banco Ficticio",
        "BOOKING_ACCOUNT_TYPE": "Ahorros",
        "BOOKING_ACCOUNT_NUMBER": "000123456",
        "BOOKING_ACCOUNT_HOLDER": "Club de Prueba",
        "BANK_BREB_KEY": "CEIBA-BREB-TEST",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    await bootstrap_agent(name="Admin B2", document_id="90000000", role="ADMIN")
    await bootstrap_agent(name="Agente B2", document_id="80000000", role="AGENT")
    try:
        async for instance in app_client():
            yield instance
    finally:
        await cleanup_test_environment()
