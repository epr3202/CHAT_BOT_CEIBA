"""G2 for the October 7 payment-message audit, using existing public endpoints."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from structlog.testing import capture_logs

from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.channel.delivery import eligibility, payment_review_context
from app.channel.models import Message, Outbox
from app.config.settings import get_settings
from app.conversation.knowledge import render_response
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.presentation import present_variables
from app.event.models import Event
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from data.knowledge_seed import iter_seed_entries
from tests.booking_conversation.helpers import (
    START,
    code,
    review_fixture,
    selected_plan,
    to_confirmation,
)
from tests.integration.helpers import login_headers
from tests.visit_booking_guard import helpers as visit_helpers
from tests.visit_booking_guard.conftest import set_human_clock
from tests.visit_booking_guard.helpers import Harness

UNLINKED_CODE = "RESP-PAYMENT-004"
PENDING_CODE = "RESP-BOOKING-PENDING-001"
RECEIPT_AMOUNT = 45596
DEPOSIT_AMOUNT = 125000


@pytest.fixture(autouse=True)
async def actual_payment_templates(harness: Harness) -> None:
    """Exercise current approved source copy instead of the older harness overrides."""
    entries = {entry.code: entry for entry in iter_seed_entries()}
    async with harness.db.begin() as session:
        for response_code in (code("PAYMENT"), code("PARTIAL"), UNLINKED_CODE, PENDING_CODE):
            entry = entries.get(response_code)
            if entry is not None:
                session.add(
                    KnowledgeEntry(
                        code=entry.code,
                        category=entry.category,
                        question_summary=entry.question_summary,
                        answer_template=entry.answer_template,
                        allowed_variables=entry.allowed_variables,
                        version=101,
                        status=entry.status,
                    )
                )


def cop(amount: int) -> str:
    return present_variables({"deposit_amount": amount})["deposit_amount"]


async def outboxes(harness: Harness) -> list[Outbox]:
    return sorted(await harness.rows(Outbox), key=lambda row: row.id)


async def accept(
    api: AsyncClient, evidence: PaymentEvidence, amount: int, *, request_id: str
) -> dict[str, Any]:
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers={**await login_headers(api, "90000000"), "X-Request-ID": request_id},
        json={"amount_cop": amount, "note": "Monto validado por el asesor de prueba"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def unlinked_evidence(harness: Harness) -> PaymentEvidence:
    await harness.seed()
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        message = Message(
            external_message_id=f"payment-message-unlinked-{uuid4().hex}",
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="image",
            content={"image": {"id": "synthetic-payment-evidence"}},
        )
        session.add(message)
        await session.flush()
        evidence = PaymentEvidence(
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            message_id=message.id,
            reservation_id=None,
            media_id="synthetic-unlinked-payment",
            mime_type="image/jpeg",
            declared_sha256="0" * 64,
            review_status="PENDING_REVIEW",
        )
        session.add(evidence)
        await session.flush()
        return evidence


async def corrupt_template(harness: Harness, response_code: str) -> None:
    async with harness.db.begin() as session:
        latest = await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == response_code)
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )
        assert latest is not None
        session.add(
            KnowledgeEntry(
                code=response_code,
                category=latest.category,
                question_summary="Plantilla sintética con variable obligatoria ausente",
                answer_template=latest.answer_template + " Falta {synthetic_required_missing}.",
                allowed_variables=[*latest.allowed_variables, "synthetic_required_missing"],
                version=latest.version + 1,
                status="APPROVED",
            )
        )


async def assert_render_failure_observed(
    harness: Harness,
    logs: list[dict[str, Any]],
    response_code: str,
    request_id: str,
) -> None:
    conversation = await harness.conversation()
    errors = [
        log
        for log in logs
        if log.get("log_level") == "error" and log.get("response_code") == response_code
    ]
    assert errors, "Falta log ERROR de la plantilla aprobada que no pudo renderizarse"
    assert any(
        log.get("conversation_id") == conversation.id and log.get("request_id") == request_id
        for log in errors
    ), "El ERROR debe identificar conversación y request, sin incluir variables privadas"
    audits = [
        audit
        for audit in await harness.rows(AuditEvent)
        if audit.request_id == request_id
        and isinstance(audit.new_value, dict)
        and audit.new_value.get("response_code") == response_code
        and audit.new_value.get("conversation_id") == conversation.id
    ]
    assert audits, "Falta auditoría del error de render con código y conversación"
    assert any(
        "MISSING_VARIABLE" in str(audit.new_value) or "MISSING_VARIABLE" in (audit.reason or "")
        for audit in audits
    )
    assert all(
        "synthetic_required_missing" not in row.payload["text"]["body"]
        and "{" not in row.payload["text"]["body"]
        for row in await outboxes(harness)
    ), "No se debe encolar texto con placeholders incompletos"


@pytest.mark.parametrize(
    "response_code,version",
    [(code("PARTIAL"), 3), (UNLINKED_CODE, 4), (PENDING_CODE, 1)],
)
def test_g2_payment_copy_has_explicit_approved_publication_versions(
    response_code: str, version: int
) -> None:
    entries = {entry.code: entry for entry in iter_seed_entries()}
    assert response_code in entries, f"Falta la plantilla aprobada {response_code}"
    assert entries[response_code].status == "APPROVED"
    assert entries[response_code].version == version


@pytest.mark.parametrize("amount,already_paid", [(45596, 0), (124999, 0), (74999, 50000)])
async def test_g2_partial_receipt_reports_received_required_missing_and_payment_instructions(
    harness: Harness, api: AsyncClient, amount: int, already_paid: int
) -> None:
    evidence = await review_fixture(harness)
    async with harness.db.begin() as session:
        reservation = await session.get(Reservation, evidence.reservation_id)
        assert reservation is not None
        reservation.amount_paid_cop = already_paid
    result = await accept(api, evidence, amount, request_id="g2.payment.partial")
    assert result["result"] == "PARTIAL"
    assert result["customer_notification"] == "ENQUEUED"
    reservations = await harness.rows(Reservation)
    assert len(reservations) == 1
    assert reservations[0].status == "PAYMENT_PENDING"
    assert reservations[0].amount_paid_cop == amount + already_paid
    assert harness.calendar.created_event_ids == []
    rows = await outboxes(harness)
    assert len(rows) == 1, "El aviso parcial debe incluir sus instrucciones en un solo mensaje"
    body = rows[0].payload["text"]["body"]
    for value in (
        amount,
        amount + already_paid,
        DEPOSIT_AMOUNT,
        DEPOSIT_AMOUNT - amount - already_paid,
    ):
        assert cop(value) in body
    assert "50 %" in body
    assert "Banco Ficticio" in body
    assert "Ahorros" in body
    assert "000123456" in body
    assert "Club de Prueba" in body
    assert "Llave Bre-B: CEIBA-BREB-TEST" in body
    assert "comprobante" in body.casefold()
    assert "fecha aún no queda separada" in body.casefold()
    assert "reserva está confirmada" not in body.casefold()
    assert "fecha quedó oficialmente separada" not in body.casefold()
    assert "disponible hoy" not in body.casefold()
    assert "{" not in body
    saved_evidence = (await harness.rows(PaymentEvidence))[0]
    assert saved_evidence.amount_cop == amount
    assert rows[0].delivery_context == payment_review_context(saved_evidence)
    async with harness.db() as session:
        conversation = await session.get(Conversation, rows[0].conversation_id)
        assert conversation is not None
        assert (await eligibility(session, conversation, rows[0]))[0] == "ELIGIBLE"
    assert await harness.rows(AIExecution) == []


@pytest.mark.parametrize("amount", [125000, 125001, 250000])
async def test_g2_human_amount_at_or_above_deposit_confirms_exactly_once(
    harness: Harness, api: AsyncClient, amount: int
) -> None:
    evidence = await review_fixture(harness)
    result = await accept(api, evidence, amount, request_id="g2.payment.deposit")
    assert result["result"] == "RESERVED"
    reservation = (await harness.rows(Reservation))[0]
    assert reservation.status == "RESERVED"
    assert reservation.amount_paid_cop == amount
    assert harness.calendar.created_event_ids == [reservation.reservation_id.hex]
    assert len(await outboxes(harness)) == 1
    assert (
        "reserva está confirmada" in (await outboxes(harness))[0].payload["text"]["body"].casefold()
    )
    repeated = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(api, "90000000"),
        json={"amount_cop": amount},
    )
    assert repeated.status_code == 409
    assert len(await harness.rows(Reservation)) == len(await outboxes(harness)) == 1


@pytest.mark.parametrize("body", [{}, {"amount_cop": 0}, {"amount_cop": None}])
async def test_g2_absent_or_zero_amount_cannot_confirm_or_notify(
    harness: Harness, api: AsyncClient, body: dict[str, Any]
) -> None:
    evidence = await review_fixture(harness)
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(api, "90000000"),
        json=body,
    )
    assert response.status_code == 422
    reservation = (await harness.rows(Reservation))[0]
    assert reservation.status == "PAYMENT_REVIEW"
    assert reservation.amount_paid_cop == 0
    assert (await harness.rows(PaymentEvidence))[0].review_status == "PENDING_REVIEW"
    assert await outboxes(harness) == []
    assert harness.calendar.created_event_ids == []
    assert not any(
        audit.action in {"PAYMENT_EVIDENCE_ACCEPTED", "RESERVATION_STATUS_CHANGED"}
        for audit in await harness.rows(AuditEvent)
    )


async def test_g2_unlinked_human_payment_acknowledges_amount_without_holding_date(
    harness: Harness, api: AsyncClient
) -> None:
    evidence = await unlinked_evidence(harness)
    result = await accept(api, evidence, RECEIPT_AMOUNT, request_id="g2.payment.unlinked")
    assert result["result"] == "NO_RESERVATION"
    assert result["customer_notification"] == "ENQUEUED"
    assert await harness.rows(Reservation) == []
    assert harness.calendar.created_event_ids == []
    rows = await outboxes(harness)
    assert len(rows) == 1
    body = rows[0].payload["text"]["body"]
    assert cop(RECEIPT_AMOUNT) in body
    assert any(
        text in body.casefold()
        for text in (
            "no asegura",
            "no está asegurada",
            "no ha quedado asegurada",
            "no separa",
            "no está separada",
        )
    ), "Sin reserva vinculada debe decir expresamente que no se asegura una fecha"
    assert "fecha quedó oficialmente separada" not in body.casefold()
    assert "50 %" not in body and "50%" not in body
    saved = (await harness.rows(PaymentEvidence))[0]
    assert saved.amount_cop == RECEIPT_AMOUNT
    assert rows[0].delivery_context == payment_review_context(saved)


@pytest.mark.parametrize("outside", [False, True])
async def test_g2_fresh_booking_always_sends_payment_v3_without_advisor_transfer(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, outside: bool
) -> None:
    set_human_clock(monkeypatch, outside=outside)
    await to_confirmation(harness)
    await harness.send("sí")
    await harness.assert_completed()
    assert harness.codes == [code("PAYMENT")]
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert await harness.rows(Handoff) == []
    rows = await outboxes(harness)
    settings = get_settings()
    expected = await render_response(
        harness.db,
        code("PAYMENT"),
        {
            "deposit_amount": DEPOSIT_AMOUNT,
            "bank_name": settings,
            "account_type": settings,
            "account_number": settings,
            "account_holder": settings,
            "breb_key": settings,
        },
    )
    assert rows[-1].payload["text"]["body"] == expected
    assert "Llave Bre-B: CEIBA-BREB-TEST" in expected
    reservations = await harness.rows(Reservation)
    assert len(reservations) == 1 and reservations[0].status == "PAYMENT_PENDING"
    assert harness.calendar.created_event_ids == []
    assert await harness.rows(AIExecution) == []


@pytest.mark.parametrize("outside", [False, True])
async def test_g2_existing_pending_request_keeps_global_guard_and_explains_payment_handoff(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, outside: bool
) -> None:
    set_human_clock(monkeypatch, outside=outside)
    await to_confirmation(harness)
    conversation = await harness.conversation()
    plan = await selected_plan(harness)
    async with harness.db.begin() as session:
        event = await session.scalar(
            select(Event).where(Event.lead_id == conversation.active_lead_id)
        )
        assert event is not None
        prior = Reservation(
            lead_id=conversation.active_lead_id,
            event_id=event.event_id,
            plan_id=plan.plan_id,
            customer_id=conversation.customer_id,
            conversation_id=None,
            starts_at=START + timedelta(days=1),
            ends_at=START + timedelta(days=1, hours=3),
            price_cop=plan.price_cop,
            amount_paid_cop=0,
            status="PAYMENT_PENDING",
            calendar_status="NONE",
        )
        session.add(prior)
        await session.flush()
        prior_id = prior.reservation_id
    await harness.send("sí")
    await harness.assert_completed()
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert [row.reservation_id for row in await harness.rows(Reservation)] == [prior_id]
    assert harness.codes == [PENDING_CODE]
    body = (await outboxes(harness))[-1].payload["text"]["body"].casefold()
    assert "pendiente" in body and "pago" in body
    assert "asesor" in body and "horario" in body
    handoffs = await harness.rows(Handoff)
    assert len(handoffs) == 1
    assert handoffs[0].reason == "RESERVATION_CONFIRMATION"
    assert "solicitud pendiente de pago" in handoffs[0].summary
    notice = (await outboxes(harness))[-1]
    assert notice.delivery_context["origin"] == "HANDOFF_NOTICE"
    assert notice.delivery_context["case_id"] == handoffs[0].id
    async with harness.db() as session:
        paused = await session.get(Conversation, notice.conversation_id)
        assert paused is not None and paused.state == "WAITING_FOR_HUMAN"
        assert (await eligibility(session, paused, notice))[0] == "ELIGIBLE"
    assert await harness.rows(AIExecution) == []


async def test_g2_booking_payment_missing_placeholder_logs_error_and_audits(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await to_confirmation(harness)
    await corrupt_template(harness, code("PAYMENT"))
    request_uuid = uuid4()
    original_process = visit_helpers.process_whatsapp_webhook

    async def process_with_valid_request(
        payload: dict[str, Any], sessionmaker: Any, **kwargs: Any
    ) -> None:
        # The webhook parser accepts UUID correlation IDs. The shared harness's
        # legacy g2.189.N identifier is deliberately not a valid request UUID.
        kwargs["request_id"] = request_uuid
        await original_process(payload, sessionmaker, **kwargs)

    monkeypatch.setattr(visit_helpers, "process_whatsapp_webhook", process_with_valid_request)
    with capture_logs() as logs:
        await harness.send("sí")
        await harness.assert_completed()
    await assert_render_failure_observed(harness, logs, code("PAYMENT"), str(request_uuid))


@pytest.mark.parametrize("linked", [False, True])
async def test_g2_admin_payment_missing_placeholder_logs_error_and_audits(
    harness: Harness, api: AsyncClient, linked: bool
) -> None:
    evidence = await review_fixture(harness) if linked else await unlinked_evidence(harness)
    response_code = code("CONFIRMED") if linked else UNLINKED_CODE
    await corrupt_template(harness, response_code)
    request_id = f"g2.payment.render.{linked}"
    with capture_logs() as logs:
        result = await accept(api, evidence, DEPOSIT_AMOUNT, request_id=request_id)
    assert result["customer_notification"] == "DEFERRED"
    await assert_render_failure_observed(harness, logs, response_code, request_id)
    assert await outboxes(harness) == []
