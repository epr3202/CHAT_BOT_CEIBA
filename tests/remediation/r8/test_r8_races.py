"""Real SQL contention, deferred commit failure and cancellation after persisted writes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.util import await_only

from app.channel import inbound
from app.conversation.models import Conversation
from app.handoff.models import Handoff
from tests.remediation.r4.helpers import configure, prepare
from tests.remediation.r5.helpers import media_payload
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import mutate, seed_case, snapshot, take_case
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def pause_after_sql(db: Any, matches: Callable[[str], bool]) -> AsyncIterator[Any]:
    """Observe an executed real statement. No SQL, result, lock or commit is replaced."""
    entered, release = asyncio.Event(), asyncio.Event()
    engine = db.kw['bind'].sync_engine
    used = False

    def observe(
        connection: Any, cursor: Any, statement: str, parameters: Any,
        context: Any, executemany: bool,
    ) -> None:
        nonlocal used
        if not used and matches(statement.lower()):
            used = True
            entered.set()
            await_only(release.wait())

    event.listen(engine, 'after_cursor_execute', observe)
    try:
        yield entered, release
    finally:
        release.set()
        event.remove(engine, 'after_cursor_execute', observe)


async def wait_for_database_lock(db: Any) -> list[dict[str, Any]]:
    # A timeout bounds failure; actual pg_blocking_pids, not elapsed time, proves contention.
    async with asyncio.timeout(10):
        while True:
            async with db() as session:
                rows = (await session.execute(text(
                    "SELECT pid, pg_blocking_pids(pid) AS blockers, wait_event "
                    "FROM pg_stat_activity WHERE datname=current_database() "
                    "AND pid != pg_backend_pid() AND wait_event_type='Lock' "
                    "AND cardinality(pg_blocking_pids(pid)) > 0 "
                    "AND lower(query) LIKE '%conversation%'",
                ))).mappings().all()
            if rows:
                return [dict(row) for row in rows]
            await asyncio.sleep(0)


async def finish_tasks(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def mutation_sql(action: str) -> Callable[[str], bool]:
    prefix = 'insert into outbox' if action == 'reply' else 'update handoff'
    return lambda statement: statement.startswith(prefix)


@pytest.mark.parametrize('pending', [True, False])
async def test_two_real_takes_have_one_owner(
    db: Any, api: Any, request: pytest.FixtureRequest, pending: bool,
) -> None:
    client, actors = api
    ids = await seed_case(db, pending=pending)
    path = f'/admin/handoffs/{ids[1]}/take' if pending else (
        f'/admin/conversations/{ids[0]}/take')
    tasks = []
    before = await snapshot(db)
    try:
        async with pause_after_sql(db, lambda s: s.startswith(
            'update handoff' if pending else 'insert into handoff',
        )) as (entered, release):
            tasks.append(asyncio.create_task(client.post(path, headers=actors['A']['headers'])))
            await asyncio.wait_for(entered.wait(), 10)
            tasks.append(asyncio.create_task(client.post(path, headers=actors['B']['headers'])))
            waits = await wait_for_database_lock(db)
            release.set()
            first, second = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    finally:
        await finish_tasks(tasks)
    after = await snapshot(db)
    evidence(request, before=before, after=after, database_waits=waits,
             statuses=[first.status_code, second.status_code])
    assert [first.status_code, second.status_code] == [200, 409]
    assert len(after['handoff']) == 1
    assert after['conversation'][0]['assigned_agent_id'] == actors['A']['id']
    assert after['handoff'][0]['assigned_agent_id'] == actors['A']['id']
    assert sum(a['action'] == 'HANDOFF_TAKEN' for a in after['audit_event']) == 1


@pytest.mark.parametrize('first_action', ['reply', 'return'])
async def test_reply_and_return_serialize_under_real_locks(
    db: Any, api: Any, request: pytest.FixtureRequest, first_action: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors['A'])
    second_action = 'return' if first_action == 'reply' else 'reply'
    before = await snapshot(db)
    tasks = []
    try:
        async with pause_after_sql(db, mutation_sql(first_action)) as (entered, release):
            tasks.append(asyncio.create_task(mutate(
                client, first_action, ids, actors['A']['headers'])))
            await asyncio.wait_for(entered.wait(), 10)
            tasks.append(asyncio.create_task(mutate(
                client, second_action, ids, actors['A']['headers'])))
            waits = await wait_for_database_lock(db)
            release.set()
            first, second = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    finally:
        await finish_tasks(tasks)
    after = await snapshot(db)
    evidence(request, before=before, after=after, database_waits=waits,
             first_action=first_action, statuses=[first.status_code, second.status_code])
    assert first.status_code == 200
    assert second.status_code == (200 if first_action == 'reply' else 409)
    assert after['conversation'][0]['state'] == 'BOT_ACTIVE'
    assert after['conversation'][0]['assigned_agent_id'] is None
    assert after['handoff'][0]['status'] == 'RETURNED'
    assert len(after['outbox']) == int(first_action == 'reply')
    assert after['message'] == before['message']
    assert sum(a['action'] == 'AGENT_MESSAGE_ENQUEUED' for a in after['audit_event']) == (
        int(first_action == 'reply'))
    assert sum(a['action'] == 'HANDOFF_RETURNED' for a in after['audit_event']) == 1


@pytest.mark.parametrize('action', ['reply', 'return'])
@pytest.mark.parametrize('change', ['owner', 'relation'])
async def test_waiter_reloads_current_assignment_and_relation(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str, change: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors['A'])
    other_ids = await take_case(db, client, actors['B']) if change == 'relation' else None
    tasks = []
    try:
        async with db() as holder, holder.begin():
            conversation = await holder.get(Conversation, ids[0], with_for_update=True)
            tasks.append(asyncio.create_task(mutate(client, action, ids, actors['A']['headers'])))
            waits = await wait_for_database_lock(db)
            handoff = await holder.get(Handoff, ids[1], with_for_update=True)
            if change == 'owner':
                # Synthetic SQL transition only: no reassignment endpoint is claimed.
                conversation.assigned_agent_id = actors['B']['id']
                handoff.assigned_agent_id = actors['B']['id']
                handoff.assigned_to = 'R8 B'
            else:
                handoff.conversation_id = other_ids[0]
            await holder.flush()
            expected = await snapshot(db)  # Before commit, independent readers see old rows.
        response = await asyncio.wait_for(tasks[0], 10)
    finally:
        await finish_tasks(tasks)
    after = await snapshot(db)
    # Verify precisely the synthetic transition; the waiting request adds no effect.
    if change == 'owner':
        for row in expected['conversation']:
            if row['id'] == ids[0]:
                row['assigned_agent_id'] = actors['B']['id']
        for row in expected['handoff']:
            if row['id'] == ids[1]:
                row['assigned_agent_id'], row['assigned_to'] = actors['B']['id'], 'R8 B'
    else:
        for row in expected['handoff']:
            if row['id'] == ids[1]:
                row['conversation_id'] = other_ids[0]
    # Neither model has an onupdate timestamp. Normalize snapshot order by stable IDs.
    for table in expected:
        assert sorted(expected[table], key=str) == sorted(after[table], key=str), table
    evidence(request, expected=expected, after=after, database_waits=waits,
             http_status=response.status_code, synthetic_transition=change)
    assert response.status_code == (403 if change == 'owner' else 409)
    if change == 'owner':
        current_owner = await mutate(client, action, ids, actors['B']['headers'])
        assert current_owner.status_code == 200


@pytest.mark.parametrize('action', ['reply', 'return'])
async def test_real_deferred_commit_failure_is_atomic_and_retryable(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors['A'])
    table = 'outbox' if action == 'reply' else 'handoff'
    operation = 'INSERT' if action == 'reply' else 'UPDATE'
    condition = '' if action == 'reply' else "WHEN (NEW.status = 'RETURNED') "
    before = await snapshot(db)
    async with db() as session, session.begin():
        await session.execute(text(
            "CREATE FUNCTION r8_fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'R8 synthetic deferred commit failure'; END $$",
        ))
        await session.execute(text(
            f'CREATE CONSTRAINT TRIGGER r8_commit_failure AFTER {operation} ON {table} '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW ' + condition +
            'EXECUTE FUNCTION r8_fail_commit()',
        ))
    try:
        with pytest.raises(DBAPIError, match='R8 synthetic deferred commit failure'):
            await mutate(client, action, ids, actors['A']['headers'])
        failed = await snapshot(db)
        assert failed == before
    finally:
        async with db() as session, session.begin():
            await session.execute(text(f'DROP TRIGGER r8_commit_failure ON {table}'))
            await session.execute(text('DROP FUNCTION r8_fail_commit()'))
    denied = await mutate(client, action, ids, actors['B']['headers'])
    assert denied.status_code == 403 and await snapshot(db) == before
    retry = await mutate(client, action, ids, actors['A']['headers'])
    assert retry.status_code == 200
    final = await snapshot(db)
    later = await mutate(client, action, ids, actors['B']['headers'])
    assert later.status_code == (403 if action == 'reply' else 409)
    assert await snapshot(db) == final
    evidence(request, before=before, failed=failed, final=final, real_commit_failure=True,
             retry_status=retry.status_code, denials=[denied.status_code, later.status_code])


@pytest.mark.parametrize('action', ['reply', 'return'])
async def test_cancel_before_commit_rolls_back_without_unlocking_another_case(
    db: Any, api: Any, request: pytest.FixtureRequest, action: str,
) -> None:
    client, actors = api
    ids = await take_case(db, client, actors['A'])
    other_ids = await take_case(db, client, actors['B'])
    before = await snapshot(db)
    tasks = []
    try:
        async with pause_after_sql(db, mutation_sql(action)) as (entered, release):
            tasks.append(asyncio.create_task(mutate(client, action, ids, actors['A']['headers'])))
            await asyncio.wait_for(entered.wait(), 10)
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(tasks[0], 10)
            release.set()
    finally:
        await finish_tasks(tasks)
    cancelled = await snapshot(db)
    assert cancelled == before
    denied = await mutate(client, action, other_ids, actors['A']['headers'])
    assert denied.status_code == 403 and await snapshot(db) == before
    retry = await mutate(client, action, ids, actors['A']['headers'])
    assert retry.status_code == 200
    evidence(request, before=before, cancelled=cancelled, final=await snapshot(db),
             retry_status=retry.status_code, unrelated_denial=denied.status_code)


async def test_r5_passive_capture_progresses_with_admin_contention(
    db: Any, api: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, actors = api
    configure(monkeypatch)
    tasks = []
    with respx.mock:
        incoming = await prepare(db)
        await inbound.process_webhook_event(incoming, db)
        async with db() as session:
            case_id = await session.scalar(select(Handoff.id))
        take = await client.post(f'/admin/handoffs/{case_id}/take', headers=actors['A']['headers'])
        assert take.status_code == 200
        async with db() as session, session.begin():
            handoff = await session.get(Handoff, case_id)
            handoff.reason = 'PAYMENT_REVIEW'
        before = await snapshot(db)
        try:
            async with pause_after_sql(db, mutation_sql('reply')) as (entered, release):
                tasks.append(asyncio.create_task(mutate(
                    client, 'reply', (1, case_id), actors['A']['headers'])))
                await asyncio.wait_for(entered.wait(), 10)
                tasks.append(asyncio.create_task(inbound.process_whatsapp_webhook(
                    media_payload(caption='Comprobante sintetico R8', external_id='r8.r5.race'), db,
                )))
                waits = await wait_for_database_lock(db)
                release.set()
                responses = await asyncio.wait_for(asyncio.gather(*tasks), 15)
        finally:
            await finish_tasks(tasks)
    after = await snapshot(db)
    evidence(request, before=before, after=after, database_waits=waits,
             human_status=responses[0].status_code)
    assert responses[0].status_code == 200
    assert len(after['payment_evidence']) == 1
    assert len(after['message']) == len(before['message']) + 1
    assert len(after['outbox']) == len(before['outbox']) + 1
    assert sum(o['payload'].get('agent') is True for o in after['outbox']) == 1
    summary = after['handoff'][0]['summary']
    assert 'evidencia #' in summary and 'Respuesta humana sintetica R8' in summary
    assert after['conversation'][0]['state'] == 'HUMAN_ACTIVE'
    assert after['conversation'][0]['assigned_agent_id'] == actors['A']['id']
    assert all(j['status'] == 'COMPLETED' for j in after['inbox_job'])
