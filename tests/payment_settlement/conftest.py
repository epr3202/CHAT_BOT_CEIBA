from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin import routes
from app.calendar.adapter import FakeCalendarAdapter
from app.config.settings import get_settings
from app.main import app
from tests.clock import BOOKING_NOW, FreezeAppClock
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


@pytest.fixture(autouse=True)
def payment_clock(freeze_app_clock: FreezeAppClock) -> None:
    """Freeze this suite without imposing its clock on shared-client consumers."""
    freeze_app_clock(BOOKING_NOW)


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


@pytest.fixture
async def transaction_engine(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    """Tag only this test's application connections, not the whole test database."""
    name = f"ceiba-test-{uuid4()}"
    engine = create_async_engine(
        app.state.db_engine.url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": "UTC", "application_name": name}},
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(app.state, "db_engine", engine)
            patch.setattr(
                app.state, "db_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
            )
            yield name
    finally:
        await engine.dispose()
