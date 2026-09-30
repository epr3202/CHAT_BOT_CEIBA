from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime
from typing import Any

import pytest
import respx

from app.ai.client import OpenRouterIntentClient
from app.config.settings import get_settings
from app.handoff import service as handoff_service
from app.orchestrator import service as orchestrator
from tests.integration.helpers import configure_test_environment, database_sessionmaker
from tests.visit_booking_guard.helpers import BOGOTA, NOW, Harness, ObservedCalendar


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    real_classify = OpenRouterIntentClient.classify_intent
    await configure_test_environment(monkeypatch)
    # Exercise the real client and its persistence, with a respx provider double.
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", real_classify)
    monkeypatch.setenv("CALENDAR_ADAPTER", "fake")
    monkeypatch.setenv("GOOGLE_FREEBUSY_CALENDAR_IDS", "visits,business-main")
    monkeypatch.setenv("HUMAN_HOURS_DAYS", "1,2,3,4,5")
    monkeypatch.setenv("HUMAN_HOURS_START", "08:00")
    monkeypatch.setenv("HUMAN_HOURS_END", "16:00")
    get_settings.cache_clear()
    monkeypatch.setattr(orchestrator, "current_bogota_datetime", lambda: NOW)
    set_human_clock(monkeypatch, outside=False)
    async with aclosing(database_sessionmaker()) as databases:
        db = await anext(databases)
        case = Harness(db, ObservedCalendar())
        monkeypatch.setattr(orchestrator, "get_calendar_adapter", lambda settings: case.calendar)
        original_enqueue = orchestrator.enqueue_template

        async def record_template(*args: Any, **kwargs: Any) -> None:
            case.codes.append(args[5])
            await original_enqueue(*args, **kwargs)

        monkeypatch.setattr(orchestrator, "enqueue_template", record_template)
        # Unregistered HTTP is forbidden, including Meta. No outbound worker runs here.
        with respx.mock(assert_all_called=False) as router:
            router.post("https://openrouter.ai/api/v1/chat/completions").mock(
                side_effect=case.respond,
            )
            yield case
    get_settings.cache_clear()


def set_human_clock(monkeypatch: pytest.MonkeyPatch, *, outside: bool) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            value = datetime(2026, 9, 29, 18 if outside else 10, tzinfo=BOGOTA)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(handoff_service, "datetime", Clock)
