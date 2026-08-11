from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.handoff.service import handoff_response_code, is_human_business_hours
from tests.integration.helpers import DATABASE_URL


def settings() -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        ENVIRONMENT="testing",
        HUMAN_HOURS_DAYS="1,2,3,4,5",
        HUMAN_HOURS_START="08:00",
        HUMAN_HOURS_END="16:00",
        _env_file=None,
    )


def test_human_business_hours_from_settings_inside_window() -> None:
    now = datetime(2026, 8, 11, 9, 0, tzinfo=ZoneInfo("America/Bogota"))

    assert is_human_business_hours(settings(), now=now) is True
    assert handoff_response_code(settings(), now=now) == "RESP-HANDOFF-001"


def test_human_business_hours_from_settings_outside_window() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=ZoneInfo("America/Bogota"))

    assert is_human_business_hours(settings(), now=now) is False
    assert handoff_response_code(settings(), now=now) == "RESP-HANDOFF-002"
