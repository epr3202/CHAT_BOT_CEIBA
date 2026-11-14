"""Apply the data of a prefilled website message before the turn is routed."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import ExtractedEntity
from app.conversation.models import Conversation
from app.conversation.prefilled_form import PrefilledForm, parse_prefilled_form
from app.customer.models import Customer
from app.event.models import EventServiceRequest

MAX_SPECIAL_REQUESTS_LENGTH = 4000


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
        old = {"email": customer.email}
        customer.email = form.email
        core.audit_domain_change(
            session,
            "CUSTOMER_EMAIL_CAPTURED",
            "customer",
            old,
            {"customer_id": customer.id, "email": form.email},
            "Correo tomado del mensaje prellenado",
            request_id,
        )
    if not (
        form.guest_count_range or form.estimated_budget or form.requested_services or form.details
    ):
        return form
    lead, event = await core.get_or_create_capture_models(
        session, conversation, customer, request_id
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
        merged = "\n".join([*current, *added])[:MAX_SPECIAL_REQUESTS_LENGTH]
        core.apply_special_requests(
            session, event, provided("special_requests", merged, merged), request_id
        )
    return form
