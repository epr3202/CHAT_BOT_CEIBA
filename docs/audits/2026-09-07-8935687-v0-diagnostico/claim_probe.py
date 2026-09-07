"""H02: stale local settlement, independent of external exactly-once delivery."""
from __future__ import annotations
import asyncio
from datetime import UTC, datetime, timedelta
import traceback


async def scenario(sm, mode):
    from audit_db_probes import seed
    from app.channel.models import Outbox
    from app.channel.worker import claim_due_outbox_batch, process_claimed_outbox_item, recover_stale_sending_outbox
    from diagnostic_plugin import snapshot
    customer, conversation, message = await seed(sm)
    t0 = datetime(2026, 9, 7, 12, tzinfo=UTC)
    async with sm() as session, session.begin():
        item = Outbox(conversation_id=conversation.id, message_id=message.id, channel='WHATSAPP', recipient_phone_number=customer.phone_number,
                      payload={'type': 'text', 'text': {'body': 'Synthetic claim audit'}}, status='PENDING', created_at=t0)
        session.add(item)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    class Old:
        async def send_text(self, to, body):
            calls.append('old_invocation_started_external_outcome_unknown')
            started.set()
            await release.wait()
            if mode == 'stale_failure':
                raise TimeoutError('Synthetic old invocation outcome uncertain')
            return 'wamid.synthetic.old.accepted'
    class New:
        async def send_text(self, to, body):
            calls.append('new_simulated_acceptance')
            return 'wamid.synthetic.new.accepted'
    old = (await claim_due_outbox_batch(sm, t0, 1))[0]
    if mode == 'current_control':
        await process_claimed_outbox_item(sm, old, New(), 5, 300)
        after = await snapshot(sm)
        return dict(status='PASS' if after['outbox'][0]['status']=='SENT' and len(after['message'])==2 else 'FAIL_REQUIREMENT', after=after, calls=calls)
    task = asyncio.create_task(process_claimed_outbox_item(sm, old, Old(), 5, 300))
    try:
        await asyncio.wait_for(started.wait(), 10)
        invocation_started = await snapshot(sm)
        await recover_stale_sending_outbox(sm, t0 + timedelta(seconds=121), 120, 5, 300)
        newer = (await claim_due_outbox_batch(sm, t0 + timedelta(seconds=130), 1))[0]
        new_claim = await snapshot(sm)
        await process_claimed_outbox_item(sm, newer, New(), 5, 300)
        before_old_result = await snapshot(sm)
    finally:
        release.set()
        await asyncio.wait_for(task, 10)
    after = await snapshot(sm)
    unchanged = before_old_result['outbox'] == after['outbox'] and before_old_result['message'] == after['message']
    return dict(status='PASS' if unchanged else 'FAIL_REQUIREMENT', criterion='An obsolete claim result must not overwrite newer settled local state or append stale outbound success',
                old_invocation_started=invocation_started, after_new_claim=new_claim, before_old_result=before_old_result, after_old_result=after,
                calls=calls, limitation='Two invocations are not the failure criterion; external acceptance/delivery of the old invocation is unknown. Only local settlement is asserted.',
                synchronization='asyncio.Event after old invocation starts; newer real claim and commit finish before old result is released', clock=str(t0))


async def run(new_session):
    rows = []
    for mode in ('current_control', 'stale_success', 'stale_failure'):
        engine = None
        try:
            sm, engine, db = await new_session('claim_' + mode)
            result = await scenario(sm, mode)
            rows.append(dict(scenario='H02_' + mode, database=db, schema='ALEMBIC_HEAD', **result))
        except Exception as error:
            rows.append(dict(scenario='H02_' + mode, status='HARNESS_ERROR', error=str(error), traceback=traceback.format_exc()))
        finally:
            if engine is not None:
                await engine.dispose()
    return rows
