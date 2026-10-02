"""ADMIN reassignment preserves R8 ownership and serializes with returning to the bot."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.agent.models import Agent
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import mutate, seed_case, snapshot, take_case
from tests.remediation.r8.test_r8_races import (
    finish_tasks,
    pause_after_sql,
    wait_for_database_lock,
)
from tests.remediation.test_r1_outbox import db as db


async def reassign(
    client: httpx.AsyncClient,
    conversation_id: int,
    actor: dict[str, Any],
    target_id: int,
) -> httpx.Response:
    return await client.post(
        f"/admin/conversations/{conversation_id}/reassign",
        headers=actor["headers"],
        json={"agent_id": target_id},
    )


async def test_admin_reassigns_taken_case_to_another_active_agent(db: Any, api: Any) -> None:
    client, actors = api
    conversation_id, handoff_id = await take_case(db, client, actors["A"])
    before = await snapshot(db)
    async with db() as session:
        target = await session.get(Agent, actors["B"]["id"])
        target_name = target.name

    response = await reassign(client, conversation_id, actors["ADMIN"], actors["B"]["id"])
    assert response.status_code == 200, response.text
    assert response.json()["assigned_agent"]["id"] == actors["B"]["id"]
    after = await snapshot(db)
    conversation, handoff = after["conversation"][0], after["handoff"][0]
    assert handoff["assigned_agent_id"] == conversation["assigned_agent_id"] == actors["B"]["id"]
    assert handoff["assigned_to"] == target_name
    assert conversation["state"] == "HUMAN_ACTIVE" and conversation["bot_enabled"] is False
    assert handoff["status"] == "TAKEN"
    assert handoff["taken_at"] == before["handoff"][0]["taken_at"]
    assert conversation["automation_epoch"] == before["conversation"][0]["automation_epoch"]
    audits = [row for row in after["audit_event"] if row["action"] == "HANDOFF_REASSIGNED"]
    assert len(audits) == 1
    assert audits[0]["old_value"] == {
        "handoff_id": handoff_id,
        "conversation_id": conversation_id,
        "assigned_agent_id": actors["A"]["id"],
        "assigned_to": "R8 A",
    }
    assert audits[0]["new_value"] == {
        "handoff_id": handoff_id,
        "conversation_id": conversation_id,
        "assigned_agent_id": actors["B"]["id"],
        "assigned_to": target_name,
    }
    assert audits[0]["actor"] == "R8 ADMIN"
    assert audits[0]["reason"] == "Admin reassigned human case"


async def test_new_owner_can_reply_and_old_owner_cannot(db: Any, api: Any) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    response = await reassign(client, ids[0], actors["ADMIN"], actors["B"]["id"])
    assert response.status_code == 200, response.text
    reply = await mutate(client, "reply", ids, actors["B"]["headers"])
    assert reply.status_code == 200, reply.text
    before_denial = await snapshot(db)
    denied = await mutate(client, "reply", ids, actors["A"]["headers"])
    assert denied.status_code == 403, denied.text
    assert await snapshot(db) == before_denial
    identity = await client.get("/admin/me", headers=actors["A"]["headers"])
    assert identity.status_code == 200
    assert identity.json()["id"] == actors["A"]["id"]


async def test_non_admin_cannot_reassign(db: Any, api: Any) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    before = await snapshot(db)
    response = await reassign(client, ids[0], actors["B"], actors["B"]["id"])
    assert response.status_code == 403, response.text
    assert await snapshot(db) == before


async def test_reassign_requires_taken_case(db: Any, api: Any) -> None:
    client, actors = api
    ids = await seed_case(db)
    before = await snapshot(db)
    response = await reassign(client, ids[0], actors["ADMIN"], actors["B"]["id"])
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "Human assignment is not consistent"}
    assert await snapshot(db) == before


async def test_reassign_to_inactive_or_unknown_agent(db: Any, api: Any) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    async with db() as session, session.begin():
        target = await session.get(Agent, actors["B"]["id"])
        target.active = False
    before = await snapshot(db)
    unknown_id = max(actor["id"] for actor in actors.values()) + 1000
    for target_id, expected_status, detail in (
        (actors["B"]["id"], 409, "Target agent is not active"),
        (unknown_id, 404, "Agent not found"),
    ):
        response = await reassign(client, ids[0], actors["ADMIN"], target_id)
        assert response.status_code == expected_status, response.text
        assert response.json() == {"detail": detail}
        assert await snapshot(db) == before


async def test_reassign_to_current_owner_is_rejected(db: Any, api: Any) -> None:
    client, actors = api
    ids = await take_case(db, client, actors["A"])
    before = await snapshot(db)
    response = await reassign(client, ids[0], actors["ADMIN"], actors["A"]["id"])
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "Agent already owns this case"}
    assert await snapshot(db) == before


async def test_reassign_is_locked_against_concurrent_return(db: Any, api: Any) -> None:
    client, actors = api
    # Exercise both winners using real SQL locks, without relying on scheduler timing.
    for first_action in ("reassign", "return"):
        ids = await take_case(db, client, actors["A"])
        tasks: list[asyncio.Task[Any]] = []

        async def perform(action: str, case_ids: tuple[int, int] = ids) -> httpx.Response:
            if action == "reassign":
                return await reassign(client, case_ids[0], actors["ADMIN"], actors["B"]["id"])
            return await mutate(client, "return", case_ids, actors["A"]["headers"])

        try:
            async with pause_after_sql(db, lambda sql: sql.startswith("update handoff")) as (
                entered,
                release,
            ):
                first = asyncio.create_task(perform(first_action))
                reached = asyncio.create_task(entered.wait())
                tasks.extend((first, reached))
                done, _ = await asyncio.wait(
                    (first, reached),
                    timeout=10,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # A missing route must fail RED by assertion, not by a fixture timeout.
                assert reached in done, (
                    f"Mutation never reached SQL: HTTP {first.result().status_code}"
                    if first.done()
                    else "Mutation did not reach SQL within 10 seconds"
                )
                second = asyncio.create_task(
                    perform(
                        "return" if first_action == "reassign" else "reassign",
                    )
                )
                tasks.append(second)
                waits = await wait_for_database_lock(db)
                assert waits, "The competing request must actually wait on a database lock"
                release.set()
                responses = await asyncio.wait_for(asyncio.gather(first, second), 10)
        finally:
            await finish_tasks(tasks)

        expected = [200, 403] if first_action == "reassign" else [200, 409]
        assert [response.status_code for response in responses] == expected
        after = await snapshot(db)
        conversation = next(row for row in after["conversation"] if row["id"] == ids[0])
        handoff = next(row for row in after["handoff"] if row["id"] == ids[1])
        if first_action == "reassign":
            assert conversation["state"] == "HUMAN_ACTIVE"
            assert conversation["bot_enabled"] is False
            assert conversation["assigned_agent_id"] == actors["B"]["id"]
            assert handoff["status"] == "TAKEN"
            assert handoff["assigned_agent_id"] == actors["B"]["id"]
        else:
            assert conversation["state"] == "BOT_ACTIVE"
            assert conversation["bot_enabled"] is True
            assert conversation["assigned_agent_id"] is None
            assert handoff["status"] == "RETURNED"
            assert handoff["assigned_agent_id"] is None and handoff["assigned_to"] is None
        decisive_audits = [
            row
            for row in after["audit_event"]
            if row["action"] in {"HANDOFF_REASSIGNED", "HANDOFF_RETURNED"}
            and row["new_value"]["handoff_id"] == ids[1]
        ]
        assert len(decisive_audits) == 1
