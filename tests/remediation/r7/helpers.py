"""R7 synthetic input uses the frozen R6 real channel/provider/R2 harness."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.orchestrator import service
from tests.remediation.r4.helpers import configure
from tests.remediation.r6.helpers import actions as actions
from tests.remediation.r6.helpers import completed as completed
from tests.remediation.r6.helpers import entity as entity
from tests.remediation.r6.helpers import prepare as prepare
from tests.remediation.r6.helpers import proposal as proposal
from tests.remediation.r6.helpers import send as send
from tests.remediation.r6.helpers import snapshot as snapshot


class Clock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = datetime(2026, 9, 9, 15, tzinfo=UTC)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    monkeypatch.setattr(service, "datetime", Clock)
