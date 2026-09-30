"""B1b-1 contracts fail assertions, never collection, on the G2 baseline."""

from datetime import datetime
from importlib import import_module
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.plan.models import Plan

BOGOTA = ZoneInfo("America/Bogota")
START = datetime(2030, 10, 10, 12, tzinfo=BOGOTA)


def symbol(module: str, name: str) -> Any:
    try:
        loaded = import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != module:
            raise
        raise AssertionError(f"B1b-1: falta {module}") from exc
    value = getattr(loaded, name, None)
    assert value is not None, f"B1b-1: falta {module}.{name}"
    return value


def plan(**changes: Any) -> Plan:
    values = dict(
        plan_id=uuid4(),
        code="RITUAL_CORAZON",
        name="Ritual",
        event_type="ROMANTIC_DINNER",
        price_cop=250000,
        duration_minutes=180,
        exclusive=False,
        weekend_only=False,
        active=True,
        sort_order=0,
    )
    values.update(changes)
    return Plan(**values)


def settings(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://test/test",
        META_APP_SECRET="test",
        META_ACCESS_TOKEN="test",
        OPENROUTER_API_KEY="test",
        GOOGLE_FREEBUSY_CALENDAR_IDS="a,b",
        **changes,
    )
