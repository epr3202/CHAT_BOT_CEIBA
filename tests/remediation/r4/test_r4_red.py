"""H05 functional RED on unchanged R3; these criteria remain unchanged in GREEN."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.channel import inbound
from tests.remediation.r3.helpers import MAIN, SERVICES, Provider, valid
from tests.remediation.r4.helpers import admin_cases, configure, prepare, snapshot
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("context", ["active", "services"])
async def test_explicit_request_is_independent_of_ai(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, context: str
) -> None:
    configure(monkeypatch)
    event_id = await prepare(
        db,
        pending="COLLECT_SERVICES" if context == "services" else None,
        state="COLLECTING_EVENT_DATA" if context == "services" else "BOT_ACTIVE",
    )
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(
            router,
            {
                MAIN: [valid() if context == "services" else httpx.ConnectError("R4 synthetic")],
                SERVICES: [httpx.ReadError("R4 synthetic auxiliary unavailable")],
            },
        )
        counts = await inbound.process_webhook_event(event_id, db)
    final = await snapshot(db)
    administrative = await admin_cases(db)
    evidence(
        request,
        before=before,
        final=final,
        calls=provider.calls,
        counts=counts,
        administrative=administrative,
    )
    assert administrative["status_code"] == 200
    assert provider.calls == {}, "Explicit personal request must precede every AI task"
    assert final["ai_execution"] == []
    assert final["message"] == before["message"] and len(final["message"]) == 1
    assert len(final["handoff"]) == len(final["outbox"]) == len(administrative["body"]) == 1
    assert final["handoff"][0]["reason"] == "CUSTOMER_REQUEST"
    assert administrative["body"][0]["id"] == final["handoff"][0]["id"]
    assert final["conversation"][0]["state"] == "WAITING_FOR_HUMAN"
    assert final["conversation"][0]["last_question_code"] == "RESP-HANDOFF-001"
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["inbox_job"][0]["attempts"] == 0
    assert final["webhook_event"][0]["status"] == "PROCESSED"


@pytest.mark.parametrize("case", ["ordinary", "transport", "negated", "quoted"])
async def test_unrecognized_control_keeps_existing_ai_path(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    configure(monkeypatch)
    body = {
        "ordinary": "Hola",
        "transport": "consulta sintetica zzz",
        "negated": "No quiero hablar con un asesor",
        "quoted": "El mensaje dice: quiero hablar con un asesor",
    }[case]
    event_id = await prepare(db, body=body)
    before = await snapshot(db)
    with respx.mock as router:
        provider = Provider(
            router, {MAIN: [httpx.ReadError("R4 synthetic") if case == "transport" else valid()]}
        )
        await inbound.process_webhook_event(event_id, db)
        provider.exhausted()
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls, input=body)
    assert provider.calls == {MAIN: 1}
    assert final["handoff"] == [] and len(final["outbox"]) == 1
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert len(final["ai_execution"]) == 1
