"""Release OFF gates; historical capabilities require explicit non-production opt-in."""

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4

import pytest
import respx
from pydantic import ValidationError

from app.config.settings import get_settings
from tests.remediation.r5.helpers import prepare, snapshot
from tests.remediation.r8.helpers import api as api
from tests.remediation.r9.helpers import Sender, enqueue
from tests.remediation.test_r1_outbox import db as db


@pytest.fixture(autouse=True)
def release_off(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("PAYMENT_EVIDENCE_AUTOMATION_ENABLED", "false")
    monkeypatch.setenv("CALENDAR_WRITES_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "document", "audio", "video"])
async def test_multimedia_preserved_without_evidence(db: Any, kind: str) -> None:
    from app.channel import inbound, inbox

    event = await prepare(db, kind=kind, payment="TAKEN")
    before = await snapshot(db)
    with respx.mock:
        await inbox.process_event(event, db)
        await inbound.process_webhook_event(event, db)
    after = await snapshot(db)
    for table in ("message", "conversation", "handoff", "outbox", "ai_execution"):
        assert after[table] == before[table]
    assert after["payment_evidence"] == []
    assert after["inbox_job"][0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_worker_off_consumer_has_no_effects_and_outbox_progresses(db: Any) -> None:
    from app.channel import inbox, worker
    from app.payment.worker import process_payment_evidence_once

    event = await prepare(db, payment="TAKEN")
    with respx.mock:
        await inbox.process_event(event, db)
        await enqueue(db)
        before = await snapshot(db)
        assert await process_payment_evidence_once(db, settings=get_settings()) == 0
        assert await snapshot(db) == before
        sender = Sender()
        await worker.process_outbox_once(db, sender)
    assert len(sender.sends) == 1


@pytest.mark.asyncio
async def test_worker_starts_only_inbox_and_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.channel import worker

    started: list[str] = []

    async def inbox_loop(*args: Any) -> None:
        started.append("inbox")

    async def outbox_loop(*args: Any) -> None:
        started.append("outbox")

    async def forbidden(*args: Any) -> None:
        pytest.fail("OFF consumer started")

    monkeypatch.setattr(worker, "_run_inbox_loop", inbox_loop)
    monkeypatch.setattr(worker, "_run_outbox_loop", outbox_loop)
    monkeypatch.setattr(worker, "_run_payment_evidence_loop", forbidden)
    with respx.mock:
        await worker.run_worker()
    assert sorted(started) == ["inbox", "outbox"]


@pytest.mark.asyncio
async def test_historical_evidence_manual_review_preserved(
    db: Any, api: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.channel import inbox
    from app.payment.worker import process_payment_evidence_once

    monkeypatch.setenv("PAYMENT_EVIDENCE_AUTOMATION_ENABLED", "true")
    event = await prepare(db, payment="TAKEN")
    with respx.mock:
        await inbox.process_event(event, db)
    monkeypatch.setenv("PAYMENT_EVIDENCE_AUTOMATION_ENABLED", "false")
    get_settings.cache_clear()
    before = await snapshot(db)
    item = before["payment_evidence"][0]
    with respx.mock:
        assert await process_payment_evidence_once(db, settings=get_settings()) == 0
    assert await snapshot(db) == before
    client, actors = api
    path = f'/admin/payment-evidence/{item["id"]}/accept'
    assert (await client.post(path, json={"note": "Revisión humana"})).status_code == 401
    response = await client.post(path, headers=actors["ADMIN"]["headers"],
                                 json={"note": "Revisión humana"})
    assert response.status_code == 200
    after = await snapshot(db)
    assert after["payment_evidence"][0]["review_status"] == "ACCEPTED"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", ["fake", "google"])
@pytest.mark.parametrize("operation", ["create_event", "update_event", "delete_event"])
async def test_adapter_writes_rejected_before_http(adapter_name: str, operation: str) -> None:
    from app.calendar.adapter import CalendarWritesDisabled, FakeCalendarAdapter
    from app.calendar.google_adapter import GoogleCalendarAdapter

    with respx.mock:
        adapter = (FakeCalendarAdapter() if adapter_name == "fake" else
                   GoogleCalendarAdapter("synthetic", "never-read.json"))
        args = [uuid4().hex]
        if operation != "delete_event":
            args += ["Synthetic", datetime.now(UTC), datetime.now(UTC)]
        try:
            with pytest.raises(CalendarWritesDisabled):
                await getattr(adapter, operation)(*args)
        finally:
            if adapter_name == "google":
                await adapter._http_client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["confirm_appointment", "reschedule_appointment",
                                      "cancel_appointment"])
async def test_service_rejects_before_database_or_adapter(operation: str) -> None:
    from app.appointment.service import VisitSchedulingService

    class Forbidden:
        def __getattr__(self, name: str) -> Any:
            pytest.fail("OFF operation touched dependency: " + name)

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("OFF operation opened transaction")

    service = VisitSchedulingService(sessionmaker=Forbidden(), calendar_adapter=Forbidden(),
                                     freebusy_calendar_ids=[])
    kwargs: dict[str, Any] = dict(appointment_id=uuid4(), actor="human", now=datetime.now(UTC))
    if operation == "confirm_appointment":
        kwargs = dict(customer_id=1, lead_id=None, conversation_id=1, visit_date=date(2030, 1, 8),
                      visit_time=time(8), attendee_count=1, visit_reason="Visita",
                      customer_confirmation=True, now=datetime.now(UTC))
    elif operation == "reschedule_appointment":
        kwargs.update(new_date=date(2030, 1, 8), new_time=time(8))
    if operation == "cancel_appointment":
        kwargs = dict(appointment_id=uuid4(), customer_confirmation=True, reason="Cancel",
                      now=datetime.now(UTC))
    result = await getattr(service, operation)(**kwargs)
    assert result.needs_handoff is True
    assert result.appointment_id is None


def test_defaults_are_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config.release_scope import ReleaseScope

    monkeypatch.delenv("PAYMENT_EVIDENCE_AUTOMATION_ENABLED")
    monkeypatch.delenv("CALENDAR_WRITES_ENABLED")
    scope = ReleaseScope(_env_file=None)
    assert not scope.payment_evidence_automation_enabled
    assert not scope.calendar_writes_enabled


@pytest.mark.parametrize("environment", ["production", "staging"])
@pytest.mark.parametrize("flag", ["PAYMENT_EVIDENCE_AUTOMATION_ENABLED", "CALENDAR_WRITES_ENABLED"])
def test_protected_environment_cannot_enable_automation(environment: str, flag: str) -> None:
    from app.config.release_scope import ReleaseScope

    with pytest.raises(ValidationError, match="release scope"):
        ReleaseScope(ENVIRONMENT=environment, **{flag: True}, _env_file=None)


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_production_fake_configuration_rejected(environment: str) -> None:
    from app.config.settings import Settings

    with pytest.raises(ValidationError, match="fake"):
        Settings(ENVIRONMENT=environment, CALENDAR_ADAPTER="fake", _env_file=None)


def test_fake_allowed_in_testing() -> None:
    from app.calendar.adapter import FakeCalendarAdapter

    assert FakeCalendarAdapter() is not None


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_direct_fake_and_simulator_rejected(
    environment: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.calendar.adapter import FakeCalendarAdapter
    from scripts.fake_meta_server import create_app
    from scripts.simulate_webhook import main

    monkeypatch.setenv("ENVIRONMENT", environment)
    for operation in (FakeCalendarAdapter, create_app, main):
        with pytest.raises(ValueError, match="forbidden"):
            operation()


@pytest.mark.parametrize("url", ["http://localhost:8081", "https://fake.example"])
def test_production_fake_whatsapp_rejected(url: str) -> None:
    from app.config.settings import Settings

    with pytest.raises(ValidationError, match="WHATSAPP_API_BASE_URL"):
        Settings(ENVIRONMENT="production", CALENDAR_ADAPTER="google",
                 WHATSAPP_API_BASE_URL=url, _env_file=None)


def test_reminders_not_connected() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path("app/channel/worker.py").read_text())
    assert not any(isinstance(n, ast.Name) and "reminder" in n.id for n in ast.walk(tree))
