"""Present the confirmed booking interval independently of the original website form."""

from datetime import datetime
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
_SCHEDULE_LABELS = {
    "fecha deseada",
    "fecha estimada",
    "fecha estimada del evento",
    "fecha estimada de la boda",
    "horario preferido",
    "fecha confirmada",
    "horario confirmado",
}


def without_request_schedule(description: str) -> str:
    lines = []
    for line in description.splitlines():
        label, separator, _ = line.partition(":")
        key = label.strip().casefold()
        if separator and key in _SCHEDULE_LABELS:
            continue
        lines.append(line)
    return "\n".join(lines)


def reservation_calendar_description(description: str, start: datetime, end: datetime) -> str:
    local_start = start.astimezone(BOGOTA)
    local_end = end.astimezone(BOGOTA)
    end_format = "%H:%M" if local_start.date() == local_end.date() else "%d/%m/%Y %H:%M"
    lines = [
        f"Fecha confirmada: {local_start:%d/%m/%Y}",
        f"Horario confirmado: {local_start:%H:%M} – {local_end.strftime(end_format)} (Bogotá)",
        without_request_schedule(description),
    ]
    return "\n".join(line for line in lines if line)
