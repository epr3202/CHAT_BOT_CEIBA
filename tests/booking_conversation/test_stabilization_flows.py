from datetime import datetime
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import select

from app.customer.models import Customer
from app.event.models import Event
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.booking_conversation.test_prefilled_experience import EXPERIENCE_FORM, converse
from tests.clock import FreezeAppClock
from tests.visit_booking_guard.helpers import Harness

BOGOTA = ZoneInfo("America/Bogota")


async def test_past_then_short_notice_then_new_date_preserves_details(
    harness: Harness, freeze_app_clock: FreezeAppClock
) -> None:
    freeze_app_clock(datetime(2026, 11, 3, 19, 8, tzinfo=BOGOTA))
    async with harness.db.begin() as session:
        plan = await session.scalar(select(Plan).where(Plan.code == "ROMANCE_COPAS"))
        plan.min_lead_days = 3
    await converse(harness, EXPERIENCE_FORM)
    assert (await harness.rows(Customer))[0].full_name == "Luna"
    assert harness.codes == ["RESP-DATE-PAST-001"]
    assert (await harness.rows(Event))[0].guest_count == 2
    assert not await harness.rows(Reservation)
    assert (await harness.conversation()).booking_draft["plan_code"] == "ROMANCE_COPAS"
    await converse(harness, "5 de noviembre de 2026")
    assert harness.codes == ["RESP-BOOKING-NOTICE-001"]
    assert "6 de noviembre de 2026" in (await harness.bodies())[-1]
    await converse(harness, "6 de noviembre de 2026 a las 7 pm")
    await converse(harness, "También quiero agregar un fotógrafo")
    await converse(harness, "Sí")
    rows = await harness.rows(Reservation)
    assert len(rows) == 1
    assert rows[0].price_cop == 400000
    assert "Violín" in rows[0].commercial_details
    assert "fotógrafo" in rows[0].commercial_details
    await converse(harness, "Quiero agregar una decoración a medida")
    assert harness.codes == ["RESP-SERVICES-003"]
    (updated,) = await harness.rows(Reservation)
    assert all(text in updated.commercial_details for text in ("Violín", "fotógrafo", "decoración"))
    assert updated.price_cop == 400000


async def test_form_replay_payment_panel_calendar_and_history(
    harness: Harness, freeze_app_clock: FreezeAppClock, api: AsyncClient
) -> None:
    import json
    from datetime import timedelta

    from app.channel.inbound import process_whatsapp_webhook
    from app.channel.models import Message
    from app.handoff.service import build_deterministic_summary
    from app.payment.models import PaymentEvidence
    from app.reservation.booking import attach_payment_evidence
    from tests.integration.helpers import login_headers, whatsapp_message_payload
    from tests.visit_booking_guard.helpers import PHONE

    freeze_app_clock(datetime(2026, 11, 3, 23, 59, tzinfo=BOGOTA))
    headers = await login_headers(api, "90000000")
    plan = next(
        p
        for p in (await api.get("/admin/plans", headers=headers)).json()
        if p["code"] == "ROMANCE_COPAS"
    )
    url = "/admin/plans/" + plan["plan_id"]
    assert (await api.patch(url, headers=headers, json={"min_lead_days": 3})).json()[
        "min_lead_days"
    ] == 3
    await converse(harness, EXPERIENCE_FORM)
    assert harness.codes == ["RESP-DATE-PAST-001"]
    occupied = datetime(2026, 11, 6, 19, tzinfo=BOGOTA)
    harness.calendar.add_event(
        "business-main", "Exclusividad", occupied, occupied + timedelta(hours=3)
    )
    await converse(harness, "6 de noviembre a las 7 pm")
    assert harness.codes == ["RESP-BOOKING-UNAVAILABLE-001"]
    await converse(harness, "7 de noviembre a las 7 pm")
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert (await api.patch(url, headers=headers, json={"min_lead_days": 4})).status_code == 200
    freeze_app_clock(datetime(2026, 11, 4, 0, 1, tzinfo=BOGOTA))
    await converse(harness, "Sí")
    assert harness.codes == ["RESP-BOOKING-NOTICE-001"]
    assert "8 de noviembre" in (await harness.bodies())[-1]
    await converse(
        harness, "8 de noviembre de 2026 a las 7 pm", "También quiero añadir un fotógrafo"
    )
    first = json.loads(
        whatsapp_message_payload("g2.189.1", phone=PHONE.removeprefix("+"), text=EXPERIENCE_FORM)
    )
    before = await harness.bodies()
    await process_whatsapp_webhook(first, harness.db, request_id="repeat-form")
    assert await harness.bodies() == before
    await converse(harness, "Sí")
    (reservation,) = await harness.rows(Reservation)
    detail_url = f"/admin/reservations/{reservation.reservation_id}"
    detail = (await api.get(detail_url, headers=headers)).json()
    snapshot = detail["commercial_details"]
    for value in (
        "Plan: Romance entre Copas",
        "Precio base de la solicitud: $400.000 COP",
        "Personas: 2",
        "Aniversario",
        "Noche",
        "$300.000",
        "$700.000",
        "fotógrafo",
        "informados por el cliente",
    ):
        assert value in snapshot
    assert snapshot.count("Violín en vivo") == 1
    from tests.integration.helpers import bootstrap_agent

    await bootstrap_agent(name="Asesor de prueba", document_id="80000111", role="AGENT")
    agent_headers = await login_headers(api, "80000111")
    cases = await api.get("/admin/conversations", headers=agent_headers)
    assert cases.status_code == 200 and cases.json()[0]["reservation_details"] == snapshot
    assert detail["price_cop"] == 400000 and detail["status"] == "PAYMENT_PENDING"
    async with harness.db.begin() as session:
        conversation = await harness.conversation()
        customer = await session.get(Customer, reservation.customer_id)
        summary = await build_deterministic_summary(
            session, conversation, customer, "PAYMENT_REVIEW", None, 1
        )
        assert snapshot in summary
        message = Message(
            external_message_id="synthetic-proof",
            conversation_id=conversation.id,
            customer_id=customer.id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="image",
            content={},
        )
        session.add(message)
        await session.flush()
        evidence = PaymentEvidence(
            conversation_id=conversation.id,
            customer_id=customer.id,
            message_id=message.id,
            media_id="synthetic",
            mime_type="image/jpeg",
            declared_sha256="0" * 64,
            download_status="DOWNLOADED",
        )
        session.add(evidence)
        await session.flush()
        await attach_payment_evidence(session, evidence, request_id=None)
        evidence_id = evidence.id
    accepted = await api.post(
        f"/admin/payment-evidence/{evidence_id}/accept",
        headers=headers,
        json={"amount_cop": 400000},
    )
    assert accepted.status_code == 200, accepted.text
    calendar_event = await harness.calendar.get_event(reservation.reservation_id.hex)
    assert snapshot in calendar_event.description
    assert (
        await api.patch(url, headers=headers, json={"price_cop": 450000, "min_lead_days": 20})
    ).status_code == 200
    reset = await api.post(
        "/admin/conversations/reset",
        headers=headers,
        json={"phone_number": PHONE, "dry_run": False, "reason": "Verificación sintética"},
    )
    assert reset.status_code == 200
    final = (await api.get(detail_url, headers=headers)).json()
    assert (final["price_cop"], final["commercial_details"], final["status"]) == (
        400000,
        snapshot,
        "RESERVED",
    )
