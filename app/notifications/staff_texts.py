import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.conversation.presentation import _present_cop, format_date_natural
from app.customer.models import Customer
from app.plan.models import Plan

BOGOTA = ZoneInfo("America/Bogota")
STAFF_TEXTS = {
    "EVIDENCE_RECEIVED": "Nuevo comprobante de pago de {1} para {2} el {3}. Abono esperado: {4}. "
    "Revísalo en el panel para confirmarlo.",
    "PAYMENT_PENDING_CREATED": "Nueva solicitud de reserva de {1}: {2} el {3}. "
    "Queda pendiente del abono de {4}; te avisaremos cuando llegue el "
    "comprobante.",
    "BALANCE_OVERDUE": "Saldo vencido: {1} tiene {2} sin pagar de la reserva de {3} el {4}. "
    "Según la política, la reserva no se realiza sin el pago completo. Revísala en el panel.",
}
STAFF_TEXTS["TEST"] = STAFF_TEXTS["EVIDENCE_RECEIVED"]
PANEL_URL = "https://admin.ceibaclubhouse.com"


def sanitize_param(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:120].strip() or "-"


def present_phone(phone: str) -> str:
    if re.fullmatch(r"\+573\d{9}", phone):
        return f"+57 {phone[3:6]} {phone[6:9]} {phone[9:]}"
    return phone


def present_start(starts_at: datetime) -> str:
    local = starts_at.astimezone(BOGOTA)
    period = "a. m." if local.hour < 12 else "p. m."
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {period}"
    return f"{format_date_natural(local.date())} a las {clock}"


def build_params(
    *, customer: Customer, plan: Plan, starts_at: datetime, deposit_cop: int
) -> list[str]:
    phone = present_phone(customer.phone_number)
    identity = f"{customer.full_name} ({phone})" if customer.full_name else phone
    return [
        sanitize_param(value)
        for value in (identity, plan.name, present_start(starts_at), _present_cop(deposit_cop))
    ]


def render_staff_text(event_kind: str, params: list[str]) -> str:
    if len(params) != 4 or any(not isinstance(p, str) or sanitize_param(p) != p for p in params):
        raise ValueError("Staff parameters must be four sanitized strings")
    template = STAFF_TEXTS[event_kind]
    # Substitute once: braces in a parameter never become another substitution.
    body = re.sub(r"\{([1-4])\}", lambda match: params[int(match.group(1)) - 1], template)
    return f"{body}\nPanel: {PANEL_URL}"


def template_for(event_kind: str, settings: Settings) -> str:
    if event_kind == "BALANCE_OVERDUE":
        return settings.staff_template_overdue_name.strip()
    return (
        settings.staff_template_pending_name
        if event_kind == "PAYMENT_PENDING_CREATED"
        else settings.staff_template_evidence_name
    ).strip()


def window_until(last_inbound_at: datetime | None, settings: Settings) -> datetime | None:
    if last_inbound_at is None:
        return None
    return last_inbound_at + timedelta(hours=24, minutes=-settings.staff_window_safety_minutes)
