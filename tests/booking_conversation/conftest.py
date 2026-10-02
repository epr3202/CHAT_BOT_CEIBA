import re
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.admin import routes
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from scripts.load_plans import load_plans
from tests.booking_conversation.helpers import TEMPLATES, code
from tests.integration.helpers import app_client, bootstrap_agent
from tests.visit_booking_guard.conftest import harness as base_harness  # noqa: F401
from tests.visit_booking_guard.helpers import Harness


@pytest.fixture
async def harness(  # noqa: F811
    base_harness: Harness,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Harness]:
    case = base_harness
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "true")
    # Existing window validates the whole duration. The literal 19:00 example
    # needs a configured close after 22:00 for the seeded three-hour plan.
    monkeypatch.setenv("BOOKING_HOURS_END", "23:00")
    for name, value in {
        "NAME": "Banco Ficticio",
        "ACCOUNT_TYPE": "Ahorros",
        "ACCOUNT_NUMBER": "000123456",
        "ACCOUNT_HOLDER": "Club de Prueba",
    }.items():
        key = "BOOKING_BANK_NAME" if name == "NAME" else f"BOOKING_{name}"
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    await load_plans(case.db)
    async with case.db.begin() as session:
        # Active B1b-3 requires an approved informational text before its PDF.
        # Production proposals stay DRAFT; approval here is synthetic test setup.
        for response_code in ("RESP-EVENTS-ROMANTIC-001", "RESP-EVENTS-PROPOSAL-001"):
            proposal = await session.scalar(select(KnowledgeEntry).where(
                KnowledgeEntry.code == response_code,
            ).order_by(KnowledgeEntry.version.desc()).limit(1))
            session.add(KnowledgeEntry(
                code=response_code, category=proposal.category,
                question_summary=proposal.question_summary,
                answer_template=proposal.answer_template,
                allowed_variables=proposal.allowed_variables, version=100, status="APPROVED",
            ))
        for name, template in TEMPLATES.items():
            session.add(
                KnowledgeEntry(
                    code=code(name),
                    category="Reservas",
                    question_summary=name,
                    answer_template=template,
                    allowed_variables=sorted(set(re.findall(r"{(\w+)}", template))),
                    version=100,
                    status="APPROVED",
                )
            )
    monkeypatch.setattr(routes, "get_calendar_adapter", lambda settings: case.calendar)
    original_list = case.calendar.list_events

    async def checked_list(*args, **kwargs):
        async with case.db() as session:
            active = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND xact_start IS NOT NULL"
                )
            )
            assert active == 0, "Calendar called while a transaction is open"
        return await original_list(*args, **kwargs)

    monkeypatch.setattr(case.calendar, "list_events", checked_list)
    yield case
    get_settings.cache_clear()


@pytest.fixture
async def api(harness: Harness) -> AsyncIterator[AsyncClient]:
    await bootstrap_agent(name="Admin Booking", document_id="90000000", role="ADMIN")
    async for client in app_client():
        yield client
