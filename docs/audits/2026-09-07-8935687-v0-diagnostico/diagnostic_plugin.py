"""Read-only pipeline observation and explicitly selected provider diagnostics."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio

OUT = Path('/audit-output')
CASES = json.loads(Path('/audit/case_manifest.json').read_text())
TARGET_NAMES = {r['nodeid'].split('::')[-1].split('[')[0] for r in CASES}
EXTRACTOR_NAMES = {r['nodeid'].split('::')[-1] for r in CASES if 'catalogs_adversarial' not in r['nodeid']}


def emit(nodeid, event, **data):
    with (OUT / (os.environ['DIAG_LABEL'] + '_observations.jsonl')).open('a') as handle:
        handle.write(json.dumps(dict(nodeid=nodeid, event=event, utc=datetime.now(UTC), **data), default=str) + '\n')


async def snapshot(sm):
    from sqlalchemy import text
    columns = {
        'conversation': 'id,state,bot_enabled,last_intent,pending_action,last_question_code,pending_confirmation,failed_understanding_count',
        'message': 'id,external_message_id,conversation_id,direction,message_type',
        'outbox': 'id,message_id,conversation_id,status,attempts,claimed_at,sent_at',
        'webhook_event': 'id,status,error,processed_at',
        'audit_event': 'id,action,entity,old_value,new_value',
        'ai_execution': 'id,task,success,validation_status,error_reason,error',
        'handoff': 'id,conversation_id,status,reason',
    }
    async with sm() as session:
        return {t: [dict(r) for r in (await session.execute(text(f'SELECT {cols} FROM "{t}" ORDER BY id'))).mappings()] for t, cols in columns.items()}


def pytest_runtest_call(item):
    name = item.originalname or item.name
    if name not in TARGET_NAMES:
        return
    from sqlalchemy.engine import make_url
    from app.config.settings import get_settings
    from app.main import app
    destinations = {}
    for key in ('DATABASE_URL', 'TEST_DATABASE_URL'):
        value = make_url(os.environ[key])
        destinations[key] = dict(host=value.host, database=value.database)
    settings = getattr(app.state, 'settings', None)
    if settings is not None:
        value = make_url(settings.database_url)
        destinations['app_state_settings'] = dict(host=value.host, database=value.database)
    emit(item.nodeid, 'test_call_configuration', destinations=destinations, settings_cache=str(get_settings.cache_info()))


@pytest_asyncio.fixture(autouse=True)
async def audit_observer(request):
    name = request.node.originalname or request.node.name
    if name not in TARGET_NAMES:
        yield
        return
    from app.channel import inbound
    from app.ai.client import OpenRouterIntentClient
    from app.config.settings import get_settings
    from sqlalchemy.engine import make_url
    nodeid = request.node.nodeid
    original_phase_a = inbound.persist_payload_phase_a
    original_phase_bc = inbound.classify_and_orchestrate_phase_b_c
    original_task = OpenRouterIntentClient._execute_task
    original_failed = inbound.mark_webhook_event_failed

    async def record(label, sm, **data):
        emit(nodeid, label, rows=await snapshot(sm), **data)

    async def phase_a(payload, sm, *args, **kwargs):
        await record('phase_a_before', sm)
        result = await original_phase_a(payload, sm, *args, **kwargs)
        await record('phase_a_after', sm, persisted=[dict(message_id=x.message_id, context=x.context) for x in result])
        return result

    async def phase_bc(messages, sm, *args, **kwargs):
        settings = get_settings()
        destination = make_url(settings.database_url)
        await record('phase_bc_before', sm, settings_db=dict(host=destination.host, database=destination.database),
                     cache=str(get_settings.cache_info()), classifier=OpenRouterIntentClient.classify_intent.__qualname__)
        try:
            return await original_phase_bc(messages, sm, *args, **kwargs)
        except Exception as error:
            emit(nodeid, 'phase_bc_exception', error_type=type(error).__name__, error=str(error))
            raise
        finally:
            await record('phase_bc_after', sm)

    async def task(self, *args, **kwargs):
        emit(nodeid, 'ai_task_start', task=kwargs.get('task'), context=kwargs.get('context'))
        try:
            result = await original_task(self, *args, **kwargs)
            emit(nodeid, 'ai_task_return', task=kwargs.get('task'), result=result)
            return result
        except Exception as error:
            emit(nodeid, 'ai_task_exception', task=kwargs.get('task'), error_type=type(error).__name__, error=str(error))
            raise

    async def failed(event_id, sm, error):
        result = await original_failed(event_id, sm, error)
        await record('webhook_failed_persisted', sm, webhook_event_id=event_id, error_type=type(error).__name__)
        return result

    with ExitStack() as stack:
        stack.enter_context(patch.object(inbound, 'persist_payload_phase_a', phase_a))
        stack.enter_context(patch.object(inbound, 'classify_and_orchestrate_phase_b_c', phase_bc))
        stack.enter_context(patch.object(inbound, 'mark_webhook_event_failed', failed))
        stack.enter_context(patch.object(OpenRouterIntentClient, '_execute_task', task))
        route = None
        if os.environ.get('DIAG_VARIANT') == 'diagnostic' and name in EXTRACTOR_NAMES:
            import httpx
            import respx
            router = stack.enter_context(respx.mock(assert_all_called=False))
            route = router.post(url__regex=r'https://openrouter\.ai/.*').mock(return_value=httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'event_type': 'synthetic unsupported event'})}}]}))
            emit(nodeid, 'explicit_diagnostic_provider', response={'event_type': 'synthetic unsupported event'}, purpose='valid extractor response discarded by deterministic normalizer')
        try:
            yield
        finally:
            if route is not None:
                emit(nodeid, 'diagnostic_provider_calls', count=len(route.calls))
                if not route.calls:
                    raise RuntimeError('Diagnostic prerequisite: extractor double was never reached')
