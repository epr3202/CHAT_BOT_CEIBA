"""Freeze only after real login/take and both CI phase sets have been inspected."""

from __future__ import annotations

from typing import Any

import pytest
import respx

from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import mutate, snapshot, take_case
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_nonowner_cannot_mutate_taken_case(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    with respx.mock:
        ids = await take_case(db, client, actors["A"])
        before = await snapshot(db)
        response = await mutate(client, action, ids, actors["B"]["headers"])
        after = await snapshot(db)
    evidence(request, action=action, owner_id=actors["A"]["id"],
             actor_id=actors["B"]["id"], before=before, after=after,
             http_status=response.status_code, response=response.json())
    assert response.status_code == 403
    assert after == before


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_owner_keeps_legitimate_mutation(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    with respx.mock:
        ids = await take_case(db, client, actors["A"])
        before = await snapshot(db)
        response = await mutate(client, action, ids, actors["A"]["headers"])
        after = await snapshot(db)
    evidence(request, before=before, after=after, action=action,
             http_status=response.status_code, actor_id=actors["A"]["id"])
    assert response.status_code == 200
    assert after["message"] == before["message"]
    if action == "reply":
        assert len(after["outbox"]) == len(before["outbox"]) + 1
        assert after["outbox"][-1]["payload"]["agent"] is True
        assert "Respuesta humana sintetica R8" in after["handoff"][0]["summary"]
        assert after["conversation"] == before["conversation"]
    else:
        assert after["outbox"] == before["outbox"]
        assert after["handoff"][0]["status"] == "RETURNED"
        assert after["conversation"][0]["state"] == "BOT_ACTIVE"
        assert after["conversation"][0]["bot_enabled"] is True
        assert after["conversation"][0]["assigned_agent_id"] is None
        assert after["handoff"][0]["assigned_agent_id"] is None
    action_name = "AGENT_MESSAGE_ENQUEUED" if action == "reply" else "HANDOFF_RETURNED"
    assert sum(a["action"] == action_name for a in after["audit_event"]) == 1


@pytest.mark.parametrize("action", ["reply", "return"])
async def test_invalid_session_keeps_case_unchanged(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    with respx.mock:
        ids = await take_case(db, client, actors["A"])
        before = await snapshot(db)
        response = await mutate(client, action, ids, {"Authorization": "Bearer invalid-r8"})
        after = await snapshot(db)
    evidence(request, before=before, after=after, action=action,
             http_status=response.status_code)
    assert response.status_code == 401
    assert after == before
