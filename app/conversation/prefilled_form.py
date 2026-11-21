"""Deterministic reader for the labeled messages prefilled by the website."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from app.conversation.entity_validation import InvalidEntity, amount_value
from app.conversation.services_catalog import match_requested_services, service_catalog_entries

MAX_EXTRAS = 10
MAX_DETAIL_LENGTH = 200
MAX_EMAIL_LENGTH = 254
EXTRA_DETAIL_PREFIX = "Adicional por cotizar: "

_LABELS: tuple[tuple[str, str], ...] = (
    ("name", r"Nombre"),
    ("email", r"Correo(?:\s+electr[oó]nico)?"),
    ("visit_date", r"Visita\s+solicitada"),
    ("visit_time", r"Hora"),
    ("estimated_date", r"Fecha\s+estimada(?:\s+del?(?:\s+la)?\s+[^\s:]+)?"),
    ("guests", r"Invitados"),
    ("budget", r"(?:Inversi[oó]n\s+contemplada|Presupuesto(?:\s+actualizado)?)(?:\s*\(COP\))?"),
    ("reason", r"Nos\s+gustar[ií]a\s+conocer\s+o\s+resolver"),
    ("plan_base", r"Plan\s+base"),
    ("extras", r"Detalles\s+adicionales"),
    ("subtotal", r"Subtotal\s+definido"),
    ("desired_date", r"Fecha\s+deseada"),
    ("preferred_time", r"Horario\s+preferido"),
    ("occasion", r"Ocasi[oó]n"),
)
_DETAIL_FIELDS = (
    "estimated_date",
    "desired_date",
    "visit_date",
    "visit_time",
    "guests",
    "budget",
    "plan_base",
    "subtotal",
    "preferred_time",
    "occasion",
)
_LABEL_PATTERN = re.compile(
    "|".join(rf"(?<!\S)(?P<{key}>{pattern})\s*:" for key, pattern in _LABELS),
    flags=re.IGNORECASE,
)
_INTRODUCTION_NAME = re.compile(
    r"\bsoy\s+(?P<name>[^\s,.;:]+(?:\s+[^\s,.;:]+){0,4}?)\s+y\s+quiero\s+consultar\b",
    flags=re.IGNORECASE,
)
_NAME_CORRECTION = re.compile(r"\bmi nombre correcto es\s+([^.,!?\n]+)", re.I)
_EMAIL_REJECTED = re.compile(
    r"\bno\s+(?:us\w*|utili\w*|autorizo|guard\w*|quiero que us\w*)\b"
    r"[^.!?\n]{0,70}\b(?:correo|email)\b"
    r"|\b(?:correo|email)\b[^!?\n]{0,130}?\bno es (?:el )?m[ií]o\b",
    re.I,
)
_ADD_EXTRA = re.compile(
    r"^(?:tambi[eé]n\s+)?(?:(?:quiero|quisiera|me gustar[ií]a)\s+)?"
    r"(?:agregar|a[nñ]adir|sumar|incluir)\s+(?:como adicional\s+)?(.+?)\s*[.!]?$",
    re.I,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class PrefilledForm:
    full_name: str | None = None
    email: str | None = None
    email_rejected: bool = False
    persons: int | None = None
    desired_date: str | None = None
    schedule_text: str | None = None
    estimated_date: str | None = None
    wedding_visit: bool = False
    extra_followup: bool = False
    guest_count_range: tuple[int, int] | None = None
    estimated_budget: Decimal | None = None
    visit_reason: str | None = None
    requested_services: tuple[str, ...] = ()
    extras: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Indica si el mensaje no aportó ningún dato del formulario.

        Returns:
            True cuando ningún campo quedó con valor.
        """
        return self == PrefilledForm()


def rejects_email(text: str) -> bool:
    return bool(_EMAIL_REJECTED.search(text))


def parse_prefilled_form(text: str, *, booking_active: bool = False) -> PrefilledForm:
    """Lee los campos etiquetados de un mensaje prellenado por el sitio web.

    Args:
        text: texto del mensaje tal como lo envió el cliente.

    Returns:
        Los datos reconocidos y validados; vacío si el mensaje no trae etiquetas ni la
        presentación "Soy ... y quiero consultar".
    """
    text = _clean(text, keep_lines=True)
    refused = rejects_email(text)
    if refused:
        text = _EMAIL.sub("[correo omitido]", text)
    fields = _labeled_values(text)
    services: list[str] = []
    extras: list[str] = []
    extra_details: list[str] = []
    addition = _ADD_EXTRA.fullmatch(text) if booking_active else None
    extras_value = fields.get("extras", ("", ""))[1] or (addition[1] if addition else "")
    for item in _bullets(extras_value):
        label = item.split(":", 1)[0].strip()
        if not label:
            continue
        if len(extras) < MAX_EXTRAS:
            extras.append(_bounded(label))
        extra_details.append(f"{EXTRA_DETAIL_PREFIX}{item}")
        for code in match_requested_services(item) or []:
            if code not in services:
                services.append(code)
    details = [
        _bounded(f"{fields[key][0]}: {fields[key][1]}")
        for key in _DETAIL_FIELDS
        if key in fields and fields[key][1]
    ]
    correction = _NAME_CORRECTION.search(text)
    persons = re.search(r"[·•]\s*(\d{1,5})\s+personas?\b", text, re.I)
    schedule = " ".join(
        fields[field][1]
        for field in ("desired_date", "preferred_time", "visit_date", "visit_time")
        if field in fields
    )
    wedding = "visit_date" in fields and bool(re.search(r"\bboda\b", text, re.I))
    reason = fields.get("reason", ("", ""))[1]
    if wedding and "boda" not in reason.casefold():
        reason = ("Boda. " + reason).strip()
    return PrefilledForm(
        email_rejected=refused,
        persons=int(persons[1]) if persons and "plan_base" in fields else None,
        desired_date=fields.get("desired_date", ("", None))[1],
        schedule_text=schedule or None,
        estimated_date=fields.get("estimated_date", ("", None))[1],
        wedding_visit=wedding,
        extra_followup=bool(addition or booking_active and set(fields) == {"extras"}),
        full_name=(_name(correction[1]) if correction else None)
        or _name(fields.get("name", ("", ""))[1])
        or _introduced_name(text),
        email=None if refused else _email(fields.get("email", ("", ""))[1]),
        guest_count_range=_guest_range(fields.get("guests", ("", ""))[1]),
        estimated_budget=_budget(fields.get("budget", ("", ""))[1]),
        visit_reason=_bounded(reason) or None,
        requested_services=tuple(services),
        extras=tuple(extras),
        details=tuple([*details, *extra_details]),
    )


def extras_to_quote(special_requests: str | None) -> tuple[str, ...]:
    """Lista los adicionales sin precio cargado guardados en los detalles del evento.

    Args:
        special_requests: detalles del evento, una línea por dato.

    Returns:
        El nombre de cada adicional por cotizar, en el orden guardado.
    """
    return tuple(
        line.removeprefix(EXTRA_DETAIL_PREFIX).split(":", 1)[0].strip()
        for line in (special_requests or "").splitlines()
        if line.startswith(EXTRA_DETAIL_PREFIX)
    )


def customer_detail_lines(
    email: str | None, service_codes: list[str], special_requests: str | None
) -> list[str]:
    """Arma las líneas de contexto del cliente para la descripción de un evento de calendario.

    Args:
        email: correo del cliente, si lo dio.
        service_codes: códigos de servicios solicitados para el evento.
        special_requests: detalles del evento, una línea por dato.

    Returns:
        Correo, servicios solicitados con su nombre visible y cada detalle, omitiendo los vacíos.
    """
    labels = {entry.code: entry.label for entry in service_catalog_entries()}
    lines = [f"Correo: {email}"] if email else []
    if service_codes:
        names = ", ".join(labels.get(code, code) for code in dict.fromkeys(service_codes))
        lines.append(f"Servicios solicitados: {names}")
    lines.extend(line for line in (special_requests or "").splitlines() if line.strip())
    return lines


def _clean(text: str, *, keep_lines: bool = False) -> str:
    """Quita caracteres de control y normaliza espacios.

    Args:
        text: texto a limpiar.
        keep_lines: si es True conserva los saltos de línea como separadores.

    Returns:
        El texto sin caracteres de control y con espacios simples.
    """
    kept = "".join(
        char
        if not unicodedata.category(char).startswith("C") or keep_lines and char == "\n"
        else " "
        for char in text
    )
    if keep_lines:
        return "\n".join(" ".join(line.split()) for line in kept.splitlines())
    return " ".join(kept.split())


def _labeled_values(text: str) -> dict[str, tuple[str, str]]:
    """Extrae el valor de cada etiqueta hasta la etiqueta siguiente o el cierre del mensaje.

    Args:
        text: mensaje limpio.

    Returns:
        Por cada campo reconocido, la etiqueta tal como se escribió y su valor.
    """
    matches = list(_LABEL_PATTERN.finditer(text))
    fields: dict[str, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        key = match.lastgroup
        if key is None or key in fields:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = re.split(r"[¿¡]", text[match.end() : end], maxsplit=1)[0]
        fields[key] = (_clean(match.group(key)), _clean(value))
    return fields


def _bullets(value: str) -> list[str]:
    """Separa la lista de adicionales en sus viñetas.

    Args:
        value: valor de "Detalles adicionales".

    Returns:
        Cada adicional sin la viñeta, en el orden escrito.
    """
    return [item.strip(" -") for item in re.split(r"[•·▪●]", value) if item.strip(" -")]


def _bounded(value: str) -> str:
    """Limita una línea de detalle a la longitud máxima permitida.

    Args:
        value: línea a guardar.

    Returns:
        La línea recortada a MAX_DETAIL_LENGTH caracteres.
    """
    return value[:MAX_DETAIL_LENGTH].rstrip()


def _name(value: str) -> str | None:
    """Valida un nombre de persona escrito por el cliente.

    Args:
        value: texto candidato a nombre.

    Returns:
        El nombre con mayúscula inicial si estaba todo en minúsculas; None si no parece un nombre.
    """
    value = _clean(value).strip(" .,;")
    words = value.split()
    if not 2 <= len(value) <= 60 or not 1 <= len(words) <= 5:
        return None
    if any(not (char.isalpha() or char in " '-") for char in value):
        return None
    return value.title() if value == value.lower() else value


def _introduced_name(text: str) -> str | None:
    """Toma el nombre de la presentación "Soy ... y quiero consultar" del sitio web.

    Args:
        text: mensaje limpio.

    Returns:
        El nombre validado, o None si la presentación no está o no trae un nombre válido.
    """
    match = _INTRODUCTION_NAME.search(text)
    return _name(match.group("name")) if match else None


def _email(value: str) -> str | None:
    """Valida el correo escrito por el cliente.

    Args:
        value: valor de la etiqueta de correo.

    Returns:
        El correo en minúsculas, o None si no es un correo válido o excede la longitud permitida.
    """
    candidate = value.split()[0] if value.split() else ""
    candidate = candidate.rstrip(".,;")
    if len(candidate) > MAX_EMAIL_LENGTH or not _EMAIL.fullmatch(candidate):
        return None
    return candidate.lower()


def _guest_range(value: str) -> tuple[int, int] | None:
    """Convierte el valor de invitados en un rango.

    Args:
        value: valor de la etiqueta de invitados, por ejemplo "Menos de 50".

    Returns:
        El rango (mínimo, máximo); "Menos de N" excluye N. None si no hay un número reconocible.
    """
    normalized = value.casefold()
    numbers = [int(number) for number in re.findall(r"\d+", normalized) if len(number) <= 10]
    if re.match(r"menos\s+de\s+\d+", normalized) and numbers:
        return (1, numbers[0] - 1) if numbers[0] > 1 else None
    if re.match(r"hasta\s+\d+", normalized) and numbers:
        return (1, numbers[0])
    if re.match(r"entre\s+\d+\s+y\s+\d+", normalized) and len(numbers) >= 2:
        low, high = sorted(numbers[:2])
        return (low, high)
    if numbers and re.fullmatch(r"\d+(?:\s+(?:personas|invitados))?", normalized.strip()):
        return (numbers[0], numbers[0])
    return None


def _budget(value: str) -> Decimal | None:
    """Toma el límite inferior de la inversión contemplada.

    Args:
        value: valor de la etiqueta de inversión, por ejemplo "Entre $15 y $20 millones".

    Returns:
        El monto en pesos, o None si no se reconoce un monto.
    """
    if not value:
        return None
    match = re.match(r"entre\s+(?P<low>.+?)\s+y\s+(?P<high>.+)$", value, flags=re.IGNORECASE)
    amount_text = value
    if match:
        amount_text = match.group("low")
        unit = re.search(r"mill[oó]n(?:es)?", match.group("high"), flags=re.IGNORECASE)
        if unit and not re.search(r"mill", amount_text, flags=re.IGNORECASE):
            amount_text = f"{amount_text} millones"
    try:
        amount_text = re.sub(
            r"(?<![\d.])\d{1,3}(?:\.\d{3})+(?![\d.])",
            lambda m: m[0].replace(".", ""),
            amount_text.strip().rstrip("."),
        )
        return amount_value(None, amount_text)
    except InvalidEntity:
        return None
