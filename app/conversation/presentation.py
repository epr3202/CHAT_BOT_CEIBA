from __future__ import annotations

from datetime import date

from app.event.models import EVENT_TYPES

MONTH_NAMES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

EVENT_TYPE_LABELS = {
    "WEDDING": "una boda",
    "CIVIL_WEDDING": "una boda civil",
    "PROPOSAL": "una propuesta de matrimonio",
    "BIRTHDAY": "un cumpleaños",
    "GRADUATION": "una graduación",
    "ANNIVERSARY": "un aniversario",
    "ROMANTIC_DINNER": "una cena romántica",
    "CORPORATE_EVENT": "un evento empresarial",
    "FAMILY_EVENT": "un evento familiar",
    "BAPTISM": "un bautizo",
    "FIRST_COMMUNION": "una primera comunión",
    "BABY_SHOWER": "un baby shower",
    "WORKSHOP": "un taller",
    "POOL_DAY": "un día de piscina",
    "PRIVATE_DINNER": "una cena privada",
    "GENDER_REVEAL": "una revelación de género",
    "OTHER": "una celebración",
}


def format_event_type(event_type: str | None) -> str:
    if event_type is None:
        return "tu celebración"
    if event_type not in EVENT_TYPES or event_type not in EVENT_TYPE_LABELS:
        raise ValueError(f"Missing presentation label for event_type: {event_type}")
    return EVENT_TYPE_LABELS[event_type]


def format_date_natural(value: date) -> str:
    return f"{value.day} de {MONTH_NAMES[value.month]} de {value.year}"


def format_month_natural(value: str) -> str:
    year, month = value.split("-", maxsplit=1)
    return f"{MONTH_NAMES[int(month)]} de {year}"
