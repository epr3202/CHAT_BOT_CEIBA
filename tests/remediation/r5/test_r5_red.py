"""Immutable RED criteria exercised against intact R4 product first."""

from __future__ import annotations

from typing import Any

import pytest
import respx

from app.channel import inbound
from tests.remediation.r3.helpers import MAIN, Provider, valid
from tests.remediation.r4.helpers import configure, message_payload
from tests.remediation.r5.helpers import assert_passive, prepare, snapshot
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


async def test_media_without_caption_must_be_silent(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    event = await prepare(db)
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        counts = await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, counts=counts, calls=provider.calls)
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert_passive(before, final, False)
    assert provider.calls == {}


@pytest.mark.parametrize("kind", ["image", "document"])
async def test_caption_payment_must_capture_without_ai(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    configure(monkeypatch)
    event = await prepare(db, kind=kind, caption="Comprobante sintetico", payment="TAKEN")
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        counts = await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, counts=counts, calls=provider.calls)
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert len(final["payment_evidence"]) == 1, "Caption must not bypass passive evidence"
    assert_passive(before, final, True)
    assert provider.calls == {}


@pytest.mark.parametrize("case", ["active_media", "active_caption", "r4_text", "paused_text"])
async def test_existing_controls(
    db: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    configure(monkeypatch)
    event = await prepare(
        db, state="HUMAN_ACTIVE" if case == "paused_text" else "BOT_ACTIVE",
        enabled=case != "paused_text", caption="Hola" if case == "active_caption" else None,
        data=message_payload("r5.text") if "text" in case else None,
    )
    before = await snapshot(db)
    with respx.mock(assert_all_called=False) as router:
        provider = Provider(router, {MAIN: [valid()]})
        await inbound.process_webhook_event(event, db)
    final = await snapshot(db)
    evidence(request, before=before, final=final, calls=provider.calls)
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["payment_evidence"] == []
    assert provider.calls == ({MAIN: 1} if case == "active_caption" else {})
    assert len(final["outbox"]) == (0 if case == "paused_text" else 1)
    assert len(final["handoff"]) == (1 if case == "r4_text" else 0)
