from __future__ import annotations

import asyncio
import sys
import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar.adapter import CalendarUnavailableError, EventNotFoundError
from app.calendar.google_adapter import GoogleCalendarAdapter
from app.config.settings import get_settings

BOGOTA = ZoneInfo("America/Bogota")
DIAGNOSTIC_SUMMARY = "[diagnóstico] verificación de acceso — borrar si aparece"


def tomorrow_bogota(today: date | None = None) -> date:
    return (today or datetime.now(BOGOTA).date()) + timedelta(days=1)


def parse_calendar_ids(value: str) -> list[str]:
    return [calendar_id.strip() for calendar_id in value.split(",") if calendar_id.strip()]


async def check_freebusy(adapter: GoogleCalendarAdapter, calendar_ids: list[str]) -> bool:
    ok = True
    target_date = tomorrow_bogota()
    for calendar_id in calendar_ids:
        try:
            intervals = await adapter.get_busy_intervals(target_date, [calendar_id])
        except CalendarUnavailableError as exc:
            print(f"FAIL {calendar_id} — {exc}")
            ok = False
            continue
        print(f"OK {calendar_id} — {len(intervals)} intervalos ocupados")
    return ok


async def check_write_cycle(adapter: GoogleCalendarAdapter) -> bool:
    target_date = tomorrow_bogota()
    event_id = f"ceibadiag{int(time_module.time()):x}"
    start = datetime.combine(target_date, time(6, 0), tzinfo=BOGOTA)
    end = start + timedelta(minutes=15)
    moved_start = start + timedelta(minutes=15)
    moved_end = moved_start + timedelta(minutes=15)
    created = False
    ok = True

    try:
        await adapter.create_event(event_id, DIAGNOSTIC_SUMMARY, start, end)
        created = True
        print(f"OK {adapter.calendar_id} — evento de diagnóstico creado: {event_id}")

        created_event = await adapter.get_event(event_id)
        if created_event.start != start or created_event.end != end:
            print(f"FAIL {adapter.calendar_id} — lectura posterior a create no coincide")
            ok = False
        else:
            print(f"OK {adapter.calendar_id} — evento de diagnóstico leído")

        await adapter.update_event(event_id, DIAGNOSTIC_SUMMARY, moved_start, moved_end)
        print(f"OK {adapter.calendar_id} — evento de diagnóstico actualizado")

        updated_event = await adapter.get_event(event_id)
        if updated_event.start != moved_start or updated_event.end != moved_end:
            print(f"FAIL {adapter.calendar_id} — lectura posterior a update no coincide")
            ok = False
        else:
            print(f"OK {adapter.calendar_id} — horario actualizado verificado")
    except (CalendarUnavailableError, EventNotFoundError, ValueError) as exc:
        print(f"FAIL {adapter.calendar_id} — ciclo de escritura: {exc}")
        ok = False
    finally:
        if created:
            try:
                await adapter.delete_event(event_id)
                print(f"OK {adapter.calendar_id} — evento de diagnóstico borrado")
            except (CalendarUnavailableError, EventNotFoundError) as exc:
                print(f"FAIL {adapter.calendar_id} — borrado de diagnóstico: {exc}")
                ok = False
    return ok


async def main() -> int:
    settings = get_settings()
    freebusy_calendar_ids = parse_calendar_ids(settings.google_freebusy_calendar_ids)
    missing = [
        name
        for name, value in {
            "GOOGLE_CALENDAR_ID": settings.google_calendar_id,
            "GOOGLE_SERVICE_ACCOUNT_FILE": settings.google_service_account_file,
            "GOOGLE_FREEBUSY_CALENDAR_IDS": settings.google_freebusy_calendar_ids,
        }.items()
        if not value.strip()
    ]
    if settings.calendar_adapter != "google":
        print("CALENDAR_ADAPTER debe ser google para ejecutar este diagnóstico")
        return 2
    if missing:
        print("Falta configuración requerida: " + ", ".join(missing))
        return 2

    adapter = GoogleCalendarAdapter(
        calendar_id=settings.google_calendar_id,
        service_account_file=settings.google_service_account_file,
    )
    freebusy_ok = await check_freebusy(adapter, freebusy_calendar_ids)
    write_ok = await check_write_cycle(adapter)
    return 0 if freebusy_ok and write_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
