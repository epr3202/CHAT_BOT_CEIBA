"""Deterministic fixed-price slots. Only human settlement can reserve a slot."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import IntentClassification
from app.appointment.service import parse_visit_time_text, resolve_visit_date_text
from app.calendar.adapter import CalendarUnavailableError
from app.config.settings import Settings
from app.conversation.catalog_event_type import normalize_catalog_event_type_label
from app.conversation.confirmation import AFFIRMATIONS, DENIALS, normalize_confirmation_text
from app.conversation.fixed_price_booking import (
    is_fixed_price_catalog_followup,
    match_booking_plan,
)
from app.conversation.knowledge import (
    KnowledgeRenderError,
    get_latest_response,
    variables_in_template,
)
from app.conversation.service import transition_conversation
from app.plan.models import Plan
from app.reservation.availability import (
    BookingAvailability,
    fetch_booking_context,
    validate_booking_window,
)
from app.reservation.booking import create_pending_reservation, deposit_amount
from app.reservation.models import Reservation

if TYPE_CHECKING:
    from app.orchestrator.service import OrchestrationInput

BOGOTA = ZoneInfo("America/Bogota")


class BookingAgendaService:
    def __init__(self, sessionmaker: Any, settings: Settings) -> None:
        self.sessionmaker, self.settings = sessionmaker, settings

    async def booking_availability(
        self,
        plan_id: UUID,
        starts_at: datetime,
        duration_minutes: int,
    ) -> BookingAvailability | None:
        from app.orchestrator import service as core

        async with self.sessionmaker() as session:
            async with session.begin():
                plan = await session.get(Plan, plan_id)
                if plan is None or not plan.active or plan.duration_minutes != duration_minutes:
                    return None
                session.expunge(plan)
            try:
                return await fetch_booking_context(
                    session,
                    plan=plan,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=duration_minutes),
                    calendar=core.get_calendar_adapter(self.settings),
                    settings=self.settings,
                )
            except CalendarUnavailableError:
                # Replay the failure as a value so the local turn can safely hand off.
                return None


async def handoff(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
    detail: str,
    *,
    reason: str = "RESERVATION_CONFIRMATION",
    response_code_override: str | None = None,
) -> None:
    from app.orchestrator import service as core

    turn.conversation.booking_draft = None
    await core.create_handoff_and_pause(
        session,
        settings,
        sm,
        turn,
        IntentClassification(
            primary_intent="HUMAN_REQUEST",
            sub_intent=None,
            confidence=0,
            requested_action="CREATE_HANDOFF",
            needs_confirmation=False,
            needs_human=True,
            handoff_reason=reason,
            priority="NORMAL",
            reasoning_code="BOOKING_HANDOFF",
        ),
        reason=reason,
        priority="NORMAL",
        detail=detail,
        response_code_override=response_code_override,
    )


async def send(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
    name: str,
    variables: dict[str, Any] | None = None,
) -> None:
    from app.orchestrator import service as core

    try:
        await core.enqueue_template(
            session,
            sm,
            turn.conversation,
            turn.customer,
            turn.inbound_message,
            f"RESP-BOOKING-{name}-001",
            variables or {},
            strict=True,
            request_id=str(turn.request_id) if turn.request_id is not None else None,
        )
    except KnowledgeRenderError:
        await handoff(
            session,
            settings,
            sm,
            turn,
            "plantilla de reserva no aprobada o incompleta",
            reason="TEMPLATE_UNAVAILABLE",
        )


async def plans_for_turn(session: AsyncSession, turn: OrchestrationInput) -> list[Plan]:
    from app.orchestrator import service as core

    event = await core.active_event(session, await core.active_lead(session, turn.conversation))
    return (
        list(
            await session.scalars(
                select(Plan)
                .where(
                    Plan.active.is_(True),
                    Plan.event_type == event.event_type,
                )
                .order_by(Plan.sort_order, Plan.code)
            )
        )
        if event is not None
        else []
    )


async def ask_plan(
    session: AsyncSession, settings: Settings, sm: Any, turn: OrchestrationInput
) -> None:
    plans = await plans_for_turn(session, turn)
    if not plans:
        await handoff(session, settings, sm, turn, "No hay planes activos para esta experiencia")
        return
    turn.conversation.pending_action = "SELECT_BOOKING_PLAN"
    await send(session, settings, sm, turn, "PLAN", {"plan_options": plans})


def resolve_booking_clock(
    message: str, *, only_time_expected: bool, hours_start: str, latest_start: str
) -> time | None:
    # Only booking accepts a bare number; visit interpretation stays unchanged.
    # Bare mañana is the next day; only a morning phrase supplies an AM period.
    morning = re.search(r"\b(?:de|en|por)\s+la\s+ma[ñn]ana\b", message.casefold())
    time_message = message if morning else re.sub(r"\bma[ñn]ana\b", "", message, flags=re.I)
    clock = parse_visit_time_text(time_message, require_explicit=not only_time_expected)
    if clock is None:
        return None
    marker = re.search(r"\b(?:[ap]\.?\s*m\.?|tarde|noche)\b", time_message.casefold()) or morning
    if marker or not 1 <= clock.hour <= 11:
        return clock
    start, latest = time.fromisoformat(hours_start), time.fromisoformat(latest_start)
    afternoon = clock.replace(hour=clock.hour + 12)
    if start <= afternoon <= latest and not start <= clock <= latest:
        return afternoon
    return clock


def extract_booking_name(message: str) -> str | None:
    value = message.strip().strip("¡!¿?.,;:")
    value = re.sub(
        r"^(?:hola|buenos días|buenas tardes|buenas noches|buen día|buen dia|buenas)"
        r"(?:[\s!¡.,:;]+|$)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:me llamo|mi nombre es|soy|habla|con)(?:\s+|$)", "", value, flags=re.IGNORECASE
    )
    value = " ".join(value.strip("¡!¿?.,;: ").split())
    if not 2 <= len(value) <= 60 or not 1 <= len(value.split()) <= 5:
        return None
    if not any(c.isalpha() for c in value) or any(not (c.isalpha() or c in " '-") for c in value):
        return None
    return value.title()


def consume_date_time(
    draft: dict, message: str, today: date, *, settings: Settings, only_time_expected: bool = False
) -> bool:
    date_message = re.sub(r"\b(?:de|en|por)\s+la\s+ma[ñn]ana\b", "", message, flags=re.I)
    decision = resolve_visit_date_text(
        date_message, today=today, require_absolute_confirmation=True
    )
    recognized = decision.resolved_date is not None
    if recognized:
        draft["date"] = decision.resolved_date.isoformat()
        draft["date_confirmation"] = decision.needs_confirmation
    clock = resolve_booking_clock(
        message,
        only_time_expected=only_time_expected,
        hours_start=settings.booking_hours_start,
        latest_start=settings.booking_latest_start,
    )
    if clock is not None:
        draft["time"] = clock.strftime("%H:%M")
    return recognized or clock is not None


async def has_pending_request(session: AsyncSession, customer_id: int) -> bool:
    existing = await session.scalar(
        select(Reservation.reservation_id)
        .where(
            Reservation.customer_id == customer_id,
            Reservation.status.in_(("PAYMENT_PENDING", "PAYMENT_REVIEW")),
        )
        .limit(1)
    )
    return existing is not None


async def handle_booking_start(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
) -> None:
    from app.orchestrator import service as core

    event = await core.active_event(session, await core.active_lead(session, turn.conversation))
    catalog_followup = is_fixed_price_catalog_followup(
        event.event_type if event is not None else None, turn.conversation.last_question_code
    )
    # A catalog reply may prepare a proposal; confirmation still checks all of
    # the customer's pending requests before creating another reservation.
    if not catalog_followup and await has_pending_request(session, turn.customer.id):
        await handoff(
            session,
            settings,
            sm,
            turn,
            "Ya existe una solicitud pendiente de pago",
            response_code_override="RESP-BOOKING-PENDING-001",
        )
        return
    draft = dict(turn.conversation.booking_draft or {}) if catalog_followup else {}
    turn.conversation.booking_draft = draft
    turn.conversation.pending_confirmation = None
    if turn.conversation.state == "NEW":
        await transition_conversation(
            session,
            turn.conversation,
            "BOT_ACTIVE",
            actor="SYSTEM",
            reason="Primera solicitud de experiencia de precio fijo",
        )
    if turn.conversation.state != "COLLECTING_EVENT_DATA":
        await transition_conversation(
            session,
            turn.conversation,
            "COLLECTING_EVENT_DATA",
            actor="SYSTEM",
            reason="Reserva autoservicio de precio fijo",
        )
    consume_date_time(
        draft, turn.message_text, core.current_bogota_datetime().date(), settings=settings
    )
    turn.conversation.booking_draft = draft
    turn.conversation.failed_understanding_count = 0
    turn.conversation.pending_fields = []
    plans = list(
        await session.scalars(
            select(Plan)
            .where(Plan.active.is_(True))
            .order_by(
                Plan.sort_order,
                Plan.code,
            )
        )
    )
    if catalog_followup:
        plans = [plan for plan in plans if plan.event_type == event.event_type]
    named = match_booking_plan(
        turn.message_text, [{"plan_id": str(plan.plan_id), "name": plan.name} for plan in plans]
    )
    if named is not None:
        plan = next(plan for plan in plans if str(plan.plan_id) == named["plan_id"])
        _, event = await core.get_or_create_capture_models(
            session,
            turn.conversation,
            turn.customer,
            request_id=turn.request_id,
        )
        from app.ai.schemas import ExtractedEntity

        core.apply_event_type(
            session,
            event,
            ExtractedEntity(
                entity="event_type",
                raw_value=plan.name,
                normalized_value=plan.event_type,
                quality_status="PROVIDED",
                confidence=1.0,
            ),
            turn.request_id,
        )
        draft = {**draft, "plan_id": str(plan.plan_id)}
        turn.conversation.booking_draft = draft
        await continue_slots(session, settings, sm, turn, plan)
        return
    if catalog_followup:
        turn.conversation.booking_draft = {**draft, "catalog_plan_selection": True}
    await ask_plan(session, settings, sm, turn)


async def continue_slots(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
    plan: Plan,
) -> None:
    from app.orchestrator import service as core
    from app.orchestrator.inbox_effects import defer_agenda_service

    conversation = turn.conversation
    draft = dict(conversation.booking_draft or {})
    if draft.get("date_confirmation"):
        conversation.pending_action = "SELECT_BOOKING_DATETIME"
        try:
            await core.enqueue_template(
                session,
                sm,
                conversation,
                turn.customer,
                turn.inbound_message,
                "RESP-EVENT-DATA-003",
                {"resolved_date": date.fromisoformat(draft["date"])},
                strict=True,
                request_id=str(turn.request_id) if turn.request_id is not None else None,
            )
        except KnowledgeRenderError:
            await handoff(session, settings, sm, turn, "Confirmación de fecha no disponible")
        return
    if not draft.get("date"):
        conversation.pending_action = "SELECT_BOOKING_DATETIME"
        await send(session, settings, sm, turn, "DATETIME")
        return
    if not draft.get("time"):
        conversation.pending_action = "SELECT_BOOKING_TIME"
        await send(session, settings, sm, turn, "TIME")
        return
    starts_at = datetime.combine(
        date.fromisoformat(draft["date"]), time.fromisoformat(draft["time"]), tzinfo=BOGOTA
    )
    ends_at = starts_at + timedelta(minutes=plan.duration_minutes)
    window = validate_booking_window(
        starts_at, ends_at, settings, today=core.current_bogota_datetime().date()
    )
    if not window.ok:
        if window.reason in {"OUTSIDE_HOURS", "CROSSES_MIDNIGHT"}:
            await ask_booking_time(session, settings, sm, turn)
            return
        await ask_booking_datetime(session, settings, sm, turn)
        return
    try:
        availability = await defer_agenda_service(
            BookingAgendaService(sm, settings)
        ).booking_availability(plan.plan_id, starts_at, plan.duration_minutes)
    except (CalendarUnavailableError, ValueError):
        await handoff(
            session,
            settings,
            sm,
            turn,
            "No se pudo consultar la disponibilidad",
            reason="SYSTEM_ERROR",
        )
        return
    if availability is None:
        await handoff(
            session,
            settings,
            sm,
            turn,
            "No se pudo consultar la disponibilidad",
            reason="SYSTEM_ERROR",
        )
        return
    if not availability.available:
        await unavailable(session, settings, sm, turn)
        return
    draft["price_cop"], draft["duration_minutes"] = plan.price_cop, plan.duration_minutes
    conversation.booking_draft = draft
    if turn.customer.full_name is None:
        conversation.pending_action = "COLLECT_BOOKING_NAME"
        await core.enqueue_template(
            session,
            sm,
            conversation,
            turn.customer,
            turn.inbound_message,
            "RESP-CUSTOMER-001",
            {},
            strict=True,
            request_id=str(turn.request_id) if turn.request_id is not None else None,
        )
        return
    conversation.pending_action = "CONFIRM_BOOKING"
    await send(
        session,
        settings,
        sm,
        turn,
        "CONFIRM",
        {
            "plan_name": plan,
            "booking_date": starts_at.date(),
            "booking_time": draft["time"],
            "total_amount": plan.price_cop,
            "deposit_amount": deposit_amount(plan),
        },
    )


async def unavailable(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
) -> None:
    await ask_booking_datetime(session, settings, sm, turn, response_kind="UNAVAILABLE")


async def ask_booking_datetime(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
    *,
    response_kind: str = "DATETIME",
) -> None:
    draft = dict(turn.conversation.booking_draft or {})
    for field in ("date", "time", "date_confirmation"):
        draft.pop(field, None)
    turn.conversation.booking_draft = draft
    turn.conversation.pending_action = "SELECT_BOOKING_DATETIME"
    await send(session, settings, sm, turn, response_kind)


async def ask_booking_time(
    session: AsyncSession, settings: Settings, sm: Any, turn: OrchestrationInput
) -> None:
    draft = dict(turn.conversation.booking_draft or {})
    draft.pop("time", None)
    turn.conversation.booking_draft = draft
    turn.conversation.pending_action = "SELECT_BOOKING_TIME"
    turn.conversation.failed_understanding_count = 0
    await send(session, settings, sm, turn, "TIME")


async def not_understood(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
    plan: Plan | None,
) -> None:
    conversation = turn.conversation
    conversation.failed_understanding_count += 1
    if conversation.failed_understanding_count >= 2:
        await handoff(
            session,
            settings,
            sm,
            turn,
            "No se entendieron dos respuestas de reserva",
            reason="LOW_CONFIDENCE",
        )
    elif conversation.pending_action == "SELECT_BOOKING_PLAN":
        await ask_plan(session, settings, sm, turn)
    elif conversation.pending_action in {"CONFIRM_BOOKING", "SELECT_BOOKING_DATETIME"}:
        await continue_slots(session, settings, sm, turn, plan)
    else:
        await send(session, settings, sm, turn, "TIME")


async def handle_booking_step(
    session: AsyncSession,
    settings: Settings,
    sm: Any,
    turn: OrchestrationInput,
) -> None:
    from app.orchestrator import service as core

    conversation = turn.conversation
    if not settings.self_service_booking_enabled:
        await handoff(session, settings, sm, turn, "Reserva autoservicio deshabilitada")
        return
    draft = dict(conversation.booking_draft or {})
    action = conversation.pending_action
    plans = await plans_for_turn(session, turn)
    if action == "SELECT_BOOKING_PLAN":
        normalized = normalize_catalog_event_type_label(turn.message_text)
        named = match_booking_plan(
            turn.message_text, [{"plan_id": str(plan.plan_id), "name": plan.name} for plan in plans]
        )
        plan = next(
            (
                p
                for i, p in enumerate(plans, 1)
                if normalized == str(i) or named is not None and str(p.plan_id) == named["plan_id"]
            ),
            None,
        )
        if plan is None:
            if draft.get("catalog_plan_selection"):
                await ask_plan(session, settings, sm, turn)
            else:
                await not_understood(session, settings, sm, turn, None)
            return
        draft.pop("catalog_plan_selection", None)
        draft["plan_id"] = str(plan.plan_id)
    else:
        plan = next((p for p in plans if str(p.plan_id) == draft.get("plan_id")), None)
        if plan is None:
            await ask_plan(session, settings, sm, turn)
            return
        normalized = normalize_confirmation_text(turn.message_text)
        if action == "COLLECT_BOOKING_NAME":
            name = extract_booking_name(turn.message_text)
            if name is None:
                conversation.failed_understanding_count += 1
                if conversation.failed_understanding_count >= 2:
                    await handoff(
                        session,
                        settings,
                        sm,
                        turn,
                        "Nombre no reconocido en reserva",
                        reason="LOW_CONFIDENCE",
                    )
                else:
                    await core.enqueue_template(
                        session,
                        sm,
                        conversation,
                        turn.customer,
                        turn.inbound_message,
                        "RESP-CUSTOMER-003",
                        {},
                        strict=True,
                        request_id=str(turn.request_id) if turn.request_id is not None else None,
                    )
                return
            old = {"full_name": turn.customer.full_name}
            turn.customer.full_name = name
            core.audit_domain_change(
                session,
                "CUSTOMER_NAME_CAPTURED",
                "customer",
                old,
                {"customer_id": turn.customer.id, "full_name": name},
                "Nombre capturado en flujo de reserva",
                turn.request_id,
            )
        elif action == "CONFIRM_BOOKING":
            if normalized in DENIALS:
                draft = {"plan_id": str(plan.plan_id)}
            elif normalized in AFFIRMATIONS:
                if (draft.get("price_cop"), draft.get("duration_minutes")) != (
                    plan.price_cop,
                    plan.duration_minutes,
                ):
                    await continue_slots(session, settings, sm, turn, plan)
                    return
                payment_template = await get_latest_response(sm, "RESP-BOOKING-PAYMENT-001")
                requires_breb_key = (
                    payment_template is not None
                    and payment_template.status == "APPROVED"
                    and "breb_key" in variables_in_template(payment_template.answer_template)
                )
                bank_fields = (
                    "booking_bank_name",
                    "booking_account_type",
                    "booking_account_number",
                    "booking_account_holder",
                )
                if requires_breb_key:
                    bank_fields += ("bank_breb_key",)
                if not all(getattr(settings, field).strip() for field in bank_fields):
                    await handoff(session, settings, sm, turn, "datos bancarios no configurados")
                    return
                # Recheck the advisory availability on confirmation. The deferred read
                # rolls this turn back until it can run without the inbox transaction.
                from app.orchestrator.inbox_effects import defer_agenda_service

                start = datetime.combine(
                    date.fromisoformat(draft["date"]),
                    time.fromisoformat(draft["time"]),
                    tzinfo=BOGOTA,
                )
                window = validate_booking_window(
                    start,
                    start + timedelta(minutes=plan.duration_minutes),
                    settings,
                    today=core.current_bogota_datetime().date(),
                )
                if not window.ok:
                    if window.reason in {"OUTSIDE_HOURS", "CROSSES_MIDNIGHT"}:
                        await ask_booking_time(session, settings, sm, turn)
                        return
                    await ask_booking_datetime(session, settings, sm, turn)
                    return
                try:
                    context = await defer_agenda_service(
                        BookingAgendaService(sm, settings)
                    ).booking_availability(plan.plan_id, start, plan.duration_minutes)
                except (CalendarUnavailableError, ValueError):
                    await handoff(
                        session, settings, sm, turn, "No se pudo consultar la disponibilidad"
                    )
                    return
                if context is None:
                    await handoff(
                        session,
                        settings,
                        sm,
                        turn,
                        "No se pudo consultar la disponibilidad",
                        reason="SYSTEM_ERROR",
                    )
                    return
                if not context.available:
                    await unavailable(session, settings, sm, turn)
                    return
                if await has_pending_request(session, turn.customer.id):
                    await handoff(
                        session,
                        settings,
                        sm,
                        turn,
                        "Ya existe una solicitud pendiente de pago",
                        response_code_override="RESP-BOOKING-PENDING-001",
                    )
                    return
                lead, event = await core.get_or_create_capture_models(
                    session,
                    conversation,
                    turn.customer,
                    turn.request_id,
                )
                # A draft is a request only: it does not block D3 or write Calendar.
                await create_pending_reservation(
                    session,
                    lead=lead,
                    event=event,
                    plan=plan,
                    conversation=conversation,
                    customer=turn.customer,
                    starts_at=start.astimezone(UTC),
                    actor="SYSTEM",
                    request_id=turn.request_id,
                )
                conversation.booking_draft = None
                conversation.pending_action = None
                await transition_conversation(
                    session,
                    conversation,
                    "BOT_ACTIVE",
                    actor="SYSTEM",
                    reason="Solicitud pendiente de pago; sin bloqueo",
                )
                payment_variables: dict[str, Any] = {
                    "deposit_amount": deposit_amount(plan),
                    "bank_name": settings,
                    "account_type": settings,
                    "account_number": settings,
                    "account_holder": settings,
                }
                if requires_breb_key:
                    payment_variables["breb_key"] = settings
                await send(
                    session,
                    settings,
                    sm,
                    turn,
                    "PAYMENT",
                    payment_variables,
                )
                return
            else:
                await not_understood(session, settings, sm, turn, plan)
                return
        elif draft.get("date_confirmation") and normalized in AFFIRMATIONS:
            draft["date_confirmation"] = False
        elif draft.get("date_confirmation") and normalized in DENIALS:
            draft = {"plan_id": str(plan.plan_id)}
        elif not consume_date_time(
            draft,
            turn.message_text,
            core.current_bogota_datetime().date(),
            settings=settings,
            only_time_expected=action == "SELECT_BOOKING_TIME",
        ):
            await not_understood(session, settings, sm, turn, plan)
            return
    conversation.failed_understanding_count = 0
    conversation.booking_draft = draft
    await continue_slots(session, settings, sm, turn, plan)
