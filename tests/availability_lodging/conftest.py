from collections.abc import AsyncIterator
from datetime import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from app.plan.models import Plan
from tests.availability_lodging.helpers import NEW_TEMPLATES, NOW
from tests.booking_conversation.conftest import base_harness  # noqa: F401
from tests.booking_conversation.conftest import harness as booking_harness  # noqa: F401
from tests.clock import FreezeAppClock
from tests.visit_booking_guard.helpers import Harness


@pytest.fixture
async def harness(
    booking_harness: Harness,  # noqa: F811
    freeze_app_clock: FreezeAppClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[Harness]:
    freeze_app_clock(NOW)
    monkeypatch.setenv("CATALOG_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("LODGING_PLAN_CODE", "REFUGIO_DOS")
    get_settings.cache_clear()
    async with booking_harness.db.begin() as session:
        for code, variables in NEW_TEMPLATES.items():
            # Synthetic approval exercises routing. Production seed must remain DRAFT.
            session.add(
                KnowledgeEntry(
                    code=code,
                    category="G2",
                    question_summary="Contrato sintético",
                    answer_template="Prueba G2: " + " / ".join("{" + v + "}" for v in variables),
                    allowed_variables=list(variables),
                    version=100,
                    status="APPROVED",
                )
            )
        # The production migration owns the backfill. create_all-based fixtures
        # explicitly prepare its business configuration once the columns exist.
        if {"overnight", "checkin_from", "checkout_time"} <= set(Plan.__table__.columns.keys()):
            plan = await session.scalar(select(Plan).where(Plan.code == "REFUGIO_DOS"))
            plan.overnight = True
            plan.checkin_from = time(15)
            plan.checkout_time = time(11)
    yield booking_harness
    get_settings.cache_clear()
