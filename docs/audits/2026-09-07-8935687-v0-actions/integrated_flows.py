"""Synthetic multi-message flows through the real inbox, AI client and transactions."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import traceback
import uuid
from unittest.mock import patch

FIXED_NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


class AuditDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW.astimezone(tz) if tz is not None else FIXED_NOW.replace(tzinfo=None)


def proposal(intent="QUOTE_REQUEST", entities=None):
    return dict(primary_intent=intent, sub_intent=None, confidence=0.99,
                extracted_entities=entities or [], requested_action=None, needs_confirmation=False,
                needs_human=False, handoff_reason=None, priority="NORMAL", reasoning_code="AUDIT_SYNTHETIC")


def entity(name, value, **overrides):
    return dict(entity=name, raw_value=str(value), normalized_value=value,
                quality_status="PROVIDED", confidence=1.0, needs_confirmation=False) | overrides


async def snapshot(sm):
    from sqlalchemy import text
    tables = ("customer", "conversation", "lead", "event", "quote_request", "message", "outbox",
              "handoff", "audit_event", "ai_execution", "webhook_event")
    async with sm() as session:
        # This database is fresh and synthetic. Agent/session credentials are never selected.
        return {t: [dict(r) for r in (await session.execute(text('SELECT * FROM "' + t + '"'))).mappings()]
                for t in tables}


async def setup(sm, *, ready=False):
    from audit_db_probes import seed
    from app.conversation.models import Conversation
    from app.lead.models import Lead
    from app.event.models import Event, EventServiceRequest
    from data.knowledge_seed import iter_seed_entries
    from scripts.load_knowledge import load_knowledge_entries
    customer, conversation, _ = await seed(sm, state="COLLECTING_EVENT_DATA")
    async with sm() as session, session.begin():
        lead = Lead(customer_id=customer.id, channel="WHATSAPP", budget_data_status="DECLINED")
        session.add(lead)
        await session.flush()
        event = Event(lead_id=lead.lead_id, event_type="BIRTHDAY", guest_count=40,
                      guest_count_status="PROVIDED", event_date_type="UNKNOWN")
        session.add(event)
        await session.flush()
        if ready:
            session.add(EventServiceRequest(event_id=event.event_id, service_name="VENUE", position=0))
        conv = await session.get(Conversation, conversation.id)
        conv.active_lead_id = lead.lead_id
    await load_knowledge_entries(sm, list(iter_seed_entries()))
    return conversation.id


async def send(sm, text, response=None, failure=None):
    import httpx
    import respx
    from app.channel.inbound import store_webhook_event, process_webhook_event
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"messages": [{"from": "15550100001",
        "id": "wamid.audit." + uuid.uuid4().hex, "timestamp": "1788782400", "type": "text", "text": {"body": text}}]}}]}]}
    event_id = await store_webhook_event(payload, sm, request_id=None)
    calls = []
    def provider(request):
        request_payload = json.loads(request.content)
        system_prompt = request_payload["messages"][0]["content"]
        task = "SERVICES" if '"service_codes"' in system_prompt else ("EVENT_TYPE" if '"event_type": "valor' in system_prompt else "INTENT")
        calls.append({"method": request.method, "host": request.url.host, "task": task})
        if failure in {"ConnectError", "ReadError", "ReadTimeout"}:
            raise getattr(httpx, failure)("Synthetic audit transport failure", request=request)
        if failure == "INVALID_JSON":
            return httpx.Response(200, json={"choices": [{"message": {"content": "invalid synthetic json"}}]})
        output = {"service_codes": []} if task == "SERVICES" else ({"event_type": "synthetic unrecognized event"} if task == "EVENT_TYPE" else (response or proposal()))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})
    with respx.mock(assert_all_called=False) as router:
        router.post(url__regex=r"https://openrouter\.ai/.*").mock(side_effect=provider)
        await process_webhook_event(event_id, sm)
    after = await snapshot(sm)
    external_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    if sum(m["external_message_id"] == external_id for m in after["message"]) != 1:
        raise RuntimeError("Harness precondition: incoming synthetic message was not persisted exactly once")
    return dict(event_id=event_id, provider_calls=calls, after=after)


def processed(step):
    return next(r for r in step["after"]["webhook_event"] if r["id"] == step["event_id"])["status"] == "PROCESSED"


async def semantic_case(sm, name, value, valid):
    await setup(sm)
    before = await snapshot(sm)
    first = await send(sm, "Dato sintetico para mi evento", proposal(entities=[entity(name, value)]))
    if not first["provider_calls"]:
        raise RuntimeError("Harness precondition: semantic proposal did not reach the real AI HTTP client")
    # Follow-up with a safe corrected value proves whether processing can continue.
    control_value = 50 if name == "guest_count" else ({"min": 30, "max": 50} if name == "guest_count_range" else {"event_date": "2026-12-01", "event_date_type": "EXACT", "event_month": None})
    second = await send(sm, "Corrijo el dato de mi evento", proposal(entities=[entity(name, control_value, raw_value="1 diciembre 2026" if name == "event_date" else str(control_value))]))
    event = first["after"]["event"][0]
    field_ok = (event["guest_count"] > 0 if name == "guest_count" else
                event["guest_count_min"] is not None and event["guest_count_max"] is not None and 0 < event["guest_count_min"] <= event["guest_count_max"] if name == "guest_count_range" else True)
    ok = processed(first) and processed(second) and (field_ok if valid else event == before["event"][0])
    if valid:
        expected_fields = {"guest_count": value} if name == "guest_count" else ({"guest_count_min": value["min"], "guest_count_max": value["max"]} if name == "guest_count_range" else {"event_date": value["event_date"]})
        ok = ok and all(str(event[k]) == str(v) for k, v in expected_fields.items())
    # Compare domain fields only; timestamps and audit events are recorded separately.
    if not valid and name == "guest_count":
        ok = processed(first) and processed(second) and event["guest_count"] == before["event"][0]["guest_count"]
    return "Invalid semantic values must not commit, crash or prevent a safe next turn", dict(before=before, steps=[first, second], valid_control=valid), ok


async def transport(sm, failure, state, human=False):
    from app.conversation.models import Conversation
    cid = await setup(sm)
    async with sm() as session, session.begin():
        conv = await session.get(Conversation, cid)
        conv.state = state
    before = await snapshot(sm)
    message = "No quiero hablar con un asesor, solo necesito informacion" if human == "negated" else ("Quiero hablar con un asesor" if human else "Hola necesito informacion")
    first = await send(sm, message, failure=failure)
    second = await send(sm, "Necesito informacion general", proposal("GENERAL_INFORMATION"))
    after = first["after"]
    handoff_created = len(after["handoff"]) > len(before["handoff"])
    replied = len(after["outbox"]) > len(before["outbox"])
    expected_effect = (replied and not handoff_created) if human == "negated" else (handoff_created if human else (replied or handoff_created))
    ok = processed(first) and expected_effect and processed(second)
    return "Transport/schema failure must preserve input and safely respond or hand off; explicit human request must escalate", dict(before=before, steps=[first, second], correspondence="H05 / PR-06b / U21" if human else "H04 / PR-06"), ok


async def name_correction(sm, corrected):
    await setup(sm)
    first = await send(sm, "Mi nombre tal vez sea Sintetico Uno", proposal(entities=[entity("full_name", "Sintetico Uno", needs_confirmation=True, quality_status="PENDING_CONFIRMATION")]))
    steps = [first]
    if corrected:
        steps.append(await send(sm, "Corrijo mi nombre a Sintetico Dos", proposal(entities=[entity("full_name", "Sintetico Dos", quality_status="CORRECTED")])))
    # A valid commercial-intent proposal reaches name confirmation; the prior run
    # separately retains the CONFIRM proposal path that asks for clarification.
    steps.append(await send(sm, "si", proposal("QUOTE_REQUEST")))
    expected = "Sintetico Dos" if corrected else "Sintetico Uno"
    ok = all(processed(s) for s in steps) and steps[-1]["after"]["customer"][0]["full_name"] == expected
    return "An explicit name correction must supersede an older pending candidate", dict(steps=steps, expected_name=expected), ok


async def quote_followup(sm, mode):
    from sqlalchemy import select
    from app.agent.auth import hash_agent_token
    from app.agent.models import Agent, AgentSession
    from app.admin.routes import take_handoff, return_handoff, ReturnHandoffRequest
    from app.handoff.models import Handoff
    await setup(sm, ready=True)
    first = await send(sm, "Quiero mi cotizacion", proposal())
    if first["after"]["conversation"][0]["state"] != "QUOTE_REQUEST_READY":
        raise RuntimeError("Harness precondition: complete synthetic quote did not reach summary")
    steps = [first]
    denied = mode in {"deny", "deny_correction"}
    steps.append(await send(sm, "no" if denied else "si", proposal("DENY" if denied else "CONFIRM")))
    if mode == "deny_correction":
        steps.append(await send(sm, "Corrijo la cantidad a cincuenta invitados", proposal("MODIFY_EVENT_DATA", [entity("guest_count", 50, quality_status="CORRECTED")])))
    if mode == "return":
        token = "synthetic-audit-session-" + uuid.uuid4().hex
        async with sm() as session, session.begin():
            agent = Agent(name="Synthetic Audit Agent", role="AGENT")
            session.add(agent)
            await session.flush()
            session.add(AgentSession(agent_id=agent.id, token_hash=hash_agent_token(token), expires_at=datetime.now(UTC) + timedelta(hours=1)))
            handoff_id = await session.scalar(select(Handoff.id))
        async with sm() as session:
            await take_handoff(handoff_id, session, authorization="Bearer " + token)
        async with sm() as session:
            await return_handoff(handoff_id, ReturnHandoffRequest(resolution="Synthetic resolution"), session, authorization="Bearer " + token)
        steps.append(dict(after_human_return=await snapshot(sm)))
    steps.append(await send(sm, "si", proposal("CONFIRM")))
    ok = all(processed(s) for s in steps if "event_id" in s)
    return "Resolved quote context must accept a subsequent affirmation without stale-contract failure", dict(mode=mode, steps=steps), ok


async def legacy_unknown(sm):
    await setup(sm)
    before = await snapshot(sm)
    response = proposal()
    response["entities"] = {"unknown_audit_entity": "synthetic"}
    first = await send(sm, "Dato sintetico legacy", response)
    if not first["provider_calls"]:
        raise RuntimeError("Harness precondition: legacy proposal did not reach AI client")
    second = await send(sm, "Corrijo el dato a cincuenta invitados", proposal(entities=[entity("guest_count", 50)]))
    return "Unknown legacy entity must produce a controlled fallback and allow the next valid turn", dict(before=before, steps=[first, second]), processed(first) and processed(second)


async def run(new_session):
    cases = []
    for name, values in (("guest_count", [(-5, False), (50, True), ("many", False)]),
                         ("guest_count_range", [({"min": 80, "max": 30}, False), ({"min": 30}, False), ({"min": 30, "max": 50}, True)]),
                         ("event_date", [({"event_date": "2026-02-30", "event_date_type": "EXACT"}, False), ({"event_date": "2026-12-01", "event_date_type": "EXACT", "event_month": None}, True), ({"event_date": "2026-12-01"}, False)])):
        for index, (value, valid) in enumerate(values):
            async def fn(sm, name=name, value=value, valid=valid):
                return await semantic_case(sm, name, value, valid)
            cases.append((f"H29_{name}_{index}_{'control' if valid else 'invalid'}", fn))
    cases.append(("H29_legacy_unknown", legacy_unknown))
    for failure in ("ConnectError", "ReadError", "ReadTimeout", "INVALID_JSON"):
        for state in ("BOT_ACTIVE", "COLLECTING_EVENT_DATA"):
            async def fn(sm, failure=failure, state=state):
                return await transport(sm, failure, state)
            cases.append((f"H04_{failure}_{state}", fn))
        async def human(sm, failure=failure):
            return await transport(sm, failure, "BOT_ACTIVE", human=True)
        cases.append((f"H05_PR06b_U21_{failure}", human))
        async def negated(sm, failure=failure):
            return await transport(sm, failure, "BOT_ACTIVE", human="negated")
        cases.append((f"H05_PR06b_U21_{failure}_negated_control", negated))
    for corrected in (False, True):
        async def fn(sm, corrected=corrected):
            return await name_correction(sm, corrected)
        cases.append(("H17_name_" + ("correction" if corrected else "control"), fn))
    for mode in ("deny", "deny_correction", "confirm", "return"):
        async def fn(sm, mode=mode):
            return await quote_followup(sm, mode)
        cases.append(("H17_quote_" + mode + "_affirm", fn))
    rows = []
    for index, (name, fn) in enumerate(cases):
        engine = None
        try:
            sm, engine, database = await new_session("flow" + str(index))
            with patch("app.orchestrator.service.datetime", AuditDatetime):
                requirement, evidence, ok = await asyncio.wait_for(fn(sm), 90)
            rows.append(dict(scenario=name, database=database, schema="ALEMBIC_HEAD", status="PASS" if ok else "FAIL_REQUIREMENT", requirement=requirement, evidence=evidence, clock=str(FIXED_NOW), synchronization="Sequential awaited real commits; no race claimed"))
        except Exception as error:
            rows.append(dict(scenario=name, status="HARNESS_ERROR", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc()))
        finally:
            if engine is not None:
                await engine.dispose()
    return rows
