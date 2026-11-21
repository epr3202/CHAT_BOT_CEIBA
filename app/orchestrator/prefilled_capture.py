"""Apply the data of a prefilled website message before the turn is routed."""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIUnavailable
from app.ai.schemas import ExtractedEntity
from app.appointment.service import resolve_visit_date_text
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.prefilled_form import PrefilledForm, parse_prefilled_form
from app.customer.models import Customer
from app.event.models import EventServiceRequest
from app.plan.models import Plan
from app.reservation.booking import commercial_snapshot
from app.reservation.models import Reservation


def provided(entity: str, value: object, raw_value: str) -> ExtractedEntity:
    """Construye una entidad entregada explícitamente por el cliente en el formulario.

    Args:
        entity: nombre de la entidad del catálogo.
        value: valor normalizado.
        raw_value: texto que la originó.

    Returns:
        La entidad con calidad PROVIDED y confianza total.
    """
    return ExtractedEntity(
        entity=entity,
        raw_value=raw_value,
        normalized_value=value,
        quality_status="PROVIDED",
        confidence=1.0,
    )


async def apply_prefilled_form(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    message_text: str,
    request_id: str | None,
) -> PrefilledForm:
    """Guarda nombre, correo, invitados, presupuesto, adicionales y detalles del mensaje prellenado.

    Args:
        session: sesión de la transacción del turno.
        conversation: conversación del turno.
        customer: cliente que escribe.
        message_text: texto del mensaje.
        request_id: identificador de la petición para la auditoría.

    Returns:
        El formulario leído; vacío si el mensaje no trae campos etiquetados.
    """
    from app.orchestrator import service as core

    form = parse_prefilled_form(message_text, booking_active=True)
    pending = None
    if form.extra_followup and not conversation.booking_draft:
        pending = await session.scalar(
            select(Reservation)
            .where(
                Reservation.conversation_id == conversation.id,
                Reservation.lead_id == conversation.active_lead_id,
                Reservation.status.in_(("PAYMENT_PENDING", "PAYMENT_REVIEW")),
            )
            .order_by(Reservation.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if pending is None:
            form = parse_prefilled_form(message_text)
    if form.is_empty:
        return form
    if form.full_name and form.full_name != customer.full_name:
        await core.apply_full_name(
            session,
            conversation,
            customer,
            provided("full_name", form.full_name, form.full_name),
            request_id,
        )
    if form.email and form.email != customer.email:
        old = {"had_email": customer.email is not None}
        customer.email = form.email
        core.audit_domain_change(
            session,
            "CUSTOMER_EMAIL_CAPTURED",
            "customer",
            old,
            {"customer_id": customer.id, "had_email": True},
            "Correo tomado del mensaje prellenado",
            request_id,
        )
    if not (
        form.persons
        or form.guest_count_range
        or form.estimated_budget
        or form.requested_services
        or form.details
    ):
        return form
    lead, event = await core.get_or_create_capture_models(
        session, conversation, customer, request_id
    )
    if form.wedding_visit and event.event_type != "WEDDING":
        core.apply_event_type(session, event, provided("event_type", "WEDDING", "boda"), request_id)
    if form.estimated_date and form.estimated_date.strip(" .").casefold() in {
        "no se",
        "no sé",
        "por definir",
    }:
        core.apply_event_date(
            session,
            event,
            provided("event_date", {"event_date_type": "UNKNOWN"}, form.estimated_date),
            request_id,
        )
    if form.persons:
        core.apply_guest_count(
            session, event, provided("guest_count", form.persons, str(form.persons)), request_id
        )
    if form.guest_count_range:
        low, high = form.guest_count_range
        core.apply_guest_count_range(
            session,
            event,
            provided("guest_count_range", {"min": low, "max": high}, f"{low}-{high}"),
            request_id,
        )
    if form.estimated_budget is not None:
        core.apply_budget(
            session,
            lead,
            provided("estimated_budget", str(form.estimated_budget), str(form.estimated_budget)),
            request_id,
        )
    existing_services = set(
        await session.scalars(
            select(EventServiceRequest.service_name).where(
                EventServiceRequest.event_id == event.event_id
            )
        )
    )
    new_services = [code for code in form.requested_services if code not in existing_services]
    if new_services:
        core.apply_requested_services(
            session,
            event,
            provided("requested_services", new_services, ", ".join(form.extras)),
            request_id,
        )
    current = (event.special_requests or "").splitlines()
    added = [line for line in form.details if line not in current]
    if added:
        merged = "\n".join([*current, *added])
        core.apply_special_requests(
            session, event, provided("special_requests", merged, merged), request_id
        )
    if added and pending is not None and pending.event_id == event.event_id:
        previous = pending.commercial_details
        if previous:
            pending.commercial_details = "\n".join([previous, *added])
        else:
            plan = await session.get(Plan, pending.plan_id)
            pending.commercial_details = commercial_snapshot(event, plan, pending.price_cop)
        core.audit_domain_change(
            session,
            "RESERVATION_DETAILS_UPDATED",
            "reservation",
            {"commercial_details": previous},
            {
                "reservation_id": str(pending.reservation_id),
                "commercial_details": pending.commercial_details,
            },
            "Adicional solicitado por el cliente",
            request_id,
        )
    return form


async def suggest_booking_date(
    message_text: str,
    *,
    waiting_for_date: bool,
    conversation_id: int,
    external_message_id: str,
    today: date,
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: uuid.UUID | None,
    settings: Settings,
) -> date | None:
    raw = parse_prefilled_form(message_text).desired_date
    if not raw and waiting_for_date:
        reply = message_text.strip()
        # Only interpret short date replies. Other booking steps retain their own routing.
        if re.fullmatch(r"[\w\s.,/-]{3,100}", reply) and re.search(
            r"\b(?:mes|d[ií]a|semana|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre)\b",
            reply,
            re.I,
        ):
            raw = reply
    if not raw or len(raw) > 200:
        return None
    if (
        resolve_visit_date_text(
            raw, today=today, require_absolute_confirmation=True, include_explicit_past=True
        ).resolved_date
        is not None
    ):
        return None
    async with OpenRouterIntentClient(settings, sessionmaker) as client:
        try:
            interpretation = await client.classify_intent(
                raw,
                context={},
                conversation_id=conversation_id,
                external_message_id=external_message_id,
                request_id=request_id,
                booking_date_reference=today,
            )
        except AIUnavailable:
            return None
    dates = [e for e in interpretation.extracted_entities if e.entity == "event_date"]
    if len(dates) != 1:
        return None
    entity = dates[0]
    value = entity.normalized_value
    if (
        entity.quality_status not in {"PROVIDED", "CORRECTED"}
        or entity.validation_errors
        or entity.confidence < settings.ai_confidence_safe
        or entity.raw_value.strip(" .").casefold() != raw.strip(" .").casefold()
        or not isinstance(value, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    ):
        return None
    try:
        candidate = date.fromisoformat(value)
    except ValueError:
        return None
    day = re.match(r"(?:el\s+)?(\d{1,2})\s+de\s+", raw, re.I)
    if day and candidate.day != int(day[1]):
        return None
    years = re.findall(r"(?<!\d)\d{4}(?!\d)", raw)
    return candidate if all(int(year) == candidate.year for year in years) else None
