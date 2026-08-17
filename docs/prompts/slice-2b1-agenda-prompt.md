# Prompt Codex — Slice 2B-1: Agenda de visitas (motor local + FakeCalendarAdapter)

**Destino de este archivo:** `docs/prompts/slice-2b1-agenda-prompt.md` — commitearlo ANTES de iniciar la implementación (`docs: add slice 2B-1 specification as test source of truth`). Es la fuente de verdad de la suite adversarial.

**Repositorio:** CHAT_BOT_CEIBA
**Rama sugerida:** `slice-2b1-agenda`
**Tag al cierre:** `slice-2b1-agenda`
**Convención:** un commit por tarea; `ruff` + `pytest` completo en verde antes de cada commit. El push lo hace Emerson.

---

## 1. Contexto y alcance

Implementar el dominio completo de visitas comerciales (UC-013, UC-014, FL-009, FL-010, FL-011; BR-APT-001→023) con el proveedor de calendario **abstraído tras un `CalendarAdapter` cuya única implementación en este slice es un fake**. La integración real con Google Calendar es el Slice 2B-2 y NO se implementa aquí — no instalar librerías de Google, no leer credenciales.

**Modelo de disponibilidad (decisión de arquitectura, fija):**

```text
slots_disponibles(fecha) =
      reglas_deterministas(fecha)            # martes-sábado, no festivo, no bloqueada,
                                             # >= 3 días de anticipación, slots 08/09/10/11
    ∩ sin_cita_local_activa(fecha, slot)     # Appointment en estado activo — resuelve bot-vs-bot
    ∩ sin_ocupacion_freebusy(fecha, slot)    # CalendarAdapter.get_busy_intervals — resuelve bot-vs-humano
```

Cada fuente arbitra un conflicto distinto: el constraint local cubre dos clientes de WhatsApp compitiendo por el mismo slot (el freebusy no ve la cita del otro porque su evento externo aún no existe); el freebusy cubre eventos creados manualmente por Leandro en cualquiera de los calendarios del negocio. Ninguna fuente sola es suficiente.

**Semántica de solapamiento:** un slot `s` queda ocupado si algún intervalo busy intersecta `[s, s+45min)`. Intervalo que termina exactamente en `s` NO ocupa `s`. Todo en `America/Bogota`.

**Configuración (en `.env.example`, valores reales los pone Emerson):**

```text
GOOGLE_CALENDAR_ID=            # calendario de escritura ("Visitas La Ceiba")
GOOGLE_FREEBUSY_CALENDAR_IDS=  # lista separada por comas: escritura + principal del negocio
CALENDAR_ADAPTER=fake          # 2B-2 agregará "google"
```

El freebusy consulta TODOS los calendarios de la lista y une los intervalos.

## 2. Invariantes (AGENTS.md + nuevas de este slice)

- Ningún HTTP dentro de transacciones abiertas (el adapter se invoca siempre fuera de txn, aunque el fake no haga red — la disciplina se prueba con el fake).
- INV-002: `appointment_status = CONFIRMED ⇒ external_calendar_id IS NOT NULL`. Sin excepciones.
- `pending_action` solo del catálogo oficial de `states.md`; la IA solo propone.
- Toda respuesta saliente desde `KnowledgeEntry` aprobada. Las plantillas RESP-VISIT-*, RESP-VISIT-TIME-*, RESP-VISIT-DATA-*, RESP-VISIT-CONFIRM-*, RESP-RESCHEDULE-*, RESP-CANCEL-VISIT-* y RESP-CALENDAR-ERROR-* ya están APPROVED en el catálogo: verificar existencia al inicio; si alguna falta, detenerse y reportar (gate).
- `AppointmentChange` es append-only.
- ID de evento externo = `appointment_id.hex` (base32hex-compatible): identidad local y externa alineadas para reconciliación. El fake debe imponer la misma unicidad que Google (segundo create con el mismo id ⇒ `AlreadyExistsError`).
- Migraciones: rebasar sobre `main` primero y tomar la siguiente revisión libre (la `0017` puede estar ocupada por el frente paralelo — verificar `alembic history` tras el rebase, nunca asumir el número).

## 3. Tareas ordenadas

### T1 — `test:` Suite adversarial (ANTES de implementar)

`tests/test_slice2b1_agenda_adversarial.py`, derivada EXCLUSIVAMENTE de este documento, `business-rules.md`, `flows.md`, `use-cases.md` y `conversation-test-cases.md`. Prohibido derivar de la implementación. En rojo/xfail en este commit.

**Grupo A — Reglas deterministas de fecha (BR-APT-001→009)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-001 | Fecha en lunes | Rechazo con RESP-VISIT-006 |
| TC-AGD-002 | Fecha en domingo | Rechazo con RESP-VISIT-006 |
| TC-AGD-003 | Festivo colombiano | Rechazo con RESP-VISIT-007 |
| TC-AGD-004 | Fecha bloqueada manualmente | Rechazo con RESP-VISIT-008 |
| TC-AGD-005 | Mismo día | Rechazo con RESP-VISIT-004 |
| TC-AGD-006 | Día siguiente | Rechazo con RESP-VISIT-005 |
| TC-AGD-007 | Anticipación de 2 días | Rechazo (mínimo 3, BR-APT-007) |
| TC-AGD-008 | Anticipación de exactamente 3 días, martes hábil | Aceptada; se consultan slots |
| TC-AGD-009 | Festivo trasladado por ley Emiliani presente en seed | La tabla de festivos contiene el traslado, no la fecha original |

**Grupo B — Disponibilidad por slots (BR-APT-003→006, BR-APT-016)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-010 | Día hábil sin ocupación | Se ofrecen exactamente 08:00, 09:00, 10:00, 11:00; end = start+45min |
| TC-AGD-011 | Cita local activa a las 10:00 | Slot 10 excluido aunque freebusy esté vacío |
| TC-AGD-012 | Cita local CANCELLED a las 10:00 | Slot 10 disponible (el índice parcial solo cubre estados activos) |
| TC-AGD-013 | 4 citas activas en el día | RESP-VISIT-009 (día completo) |
| TC-AGD-014 | Freebusy: evento manual 09:00–09:30 | Slot 9 excluido; 8, 10, 11 ofrecidos |
| TC-AGD-015 | Freebusy: evento manual 08:30–10:30 | Slots 8, 9 y 10 excluidos; solo 11 |
| TC-AGD-016 | Freebusy: evento termina exactamente 09:00 | Slot 9 disponible (frontera sin solape) |
| TC-AGD-017 | Freebusy con dos calendarios: busy solo en el principal | El slot igual se excluye (unión de calendarios) |
| TC-AGD-018 | Freebusy lanza excepción al consultar | RESP-CALENDAR-ERROR-001; NO se inventan slots; ruta de registro para revisión (TC-CALENDAR-001) |

**Grupo C — Recolección y selección (FL-009, FL-010, BR-APT-010→013)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-019 | Fecha relativa "el próximo sábado" | Se confirma en absoluto antes de consultar slots (FL-009) |
| TC-AGD-020 | "A las 2 de la tarde" | RESP-VISIT-TIME-002 (solo horarios de mañana) |
| TC-AGD-021 | Selección contextual "la de las 9" con opciones ofrecidas | `preferred_visit_time = 09:00` |
| TC-AGD-022 | 4 asistentes | RESP-VISIT-DATA-002; si el cliente pide excepción ⇒ handoff |
| TC-AGD-023 | Resumen previo a confirmación | RESP-VISIT-CONFIRM-001 con fecha, hora, asistentes y motivo; estado `APPOINTMENT_PENDING_CONFIRMATION` (BR-APT-013) |

**Grupo D — Creación con doble validación (UC-014, BR-APT-014→017, INV-002)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-024 | Confirmación feliz | txn1: revalida + inserta PENDING; adapter fuera de txn; txn2: external_id + CONFIRMED + recordatorio programado (un día antes) + lead VISIT_SCHEDULED + auditoría; RESP-VISIT-CONFIRM-003 |
| TC-AGD-025 | Leandro crea evento entre oferta y confirmación (freebusy cambia) | Segunda validación lo detecta; no se crea; RESP-VISIT-CONFIRM-005; regresa a `WAITING_FOR_APPOINTMENT_SELECTION` (BR-APT-015) |
| TC-AGD-026 | Dos confirmaciones concurrentes del mismo slot | Una gana; la otra recibe violación del índice único parcial y RESP-VISIT-CONFIRM-005; jamás dos citas activas en el mismo horario (BR-APT-016, probar contra la DB, no con mock) |
| TC-AGD-027 | Adapter falla al crear (TC-CALENDAR-004) | Cita queda PENDING_CONFIRMATION, NUNCA CONFIRMED; RESP-CALENDAR-ERROR-002; ruta de reconciliación registrada |
| TC-AGD-028 | Timeout del adapter tras crear (TC-CALENDAR-002) | Reintento con el mismo id ⇒ `AlreadyExistsError` del fake ⇒ se persiste external_id y se confirma; cero duplicados |
| TC-AGD-029 | Fallo del mensaje de confirmación tras crear (TC-MESSAGE-001) | La cita sigue creada; se reintenta solo el mensaje; no se crea otra cita |
| TC-AGD-030 | Cita confirmada | `timezone = America/Bogota` persistida; `end_time = start + 45min` calculado, no capturado |

**Grupo E — Recordatorio (BR-NOT, TC-MESSAGE-002)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-031 | Recordatorio programado | Outbox con `scheduled_at` = un día antes a hora configurada; contenido de plantilla aprobada |
| TC-AGD-032 | Reintento del worker sobre el recordatorio | Un solo recordatorio lógico enviado |

**Grupo F — Reprogramación y cancelación (FL-011, BR-APT-021→023, TC-CALENDAR-005/006)**

| ID | Escenario | Esperado |
|---|---|---|
| TC-AGD-033 | Una cita activa, cliente pide cambio | RESP-RESCHEDULE-001 con datos actuales |
| TC-AGD-034 | Varias citas activas | RESP-RESCHEDULE-002 (pedir identificar) |
| TC-AGD-035 | Nuevo horario falla en el adapter (TC-CALENDAR-006) | La cita original permanece activa e intacta; RESP-CALENDAR-ERROR-003 |
| TC-AGD-036 | Reprogramación exitosa | `AppointmentChange` append-only con fecha/hora anterior y nueva, actor y timestamp; `reschedule_count` incrementa; el nuevo horario pasó validación completa como cita nueva (BR-APT-023) |
| TC-AGD-037 | Cancelación con confirmación | RESP-CANCEL-VISIT-001 antes; tras confirmar: estado CANCELLED, evento externo eliminado vía adapter, RESP-CANCEL-VISIT-002 |
| TC-AGD-038 | Fallo del adapter al cancelar (TC-CALENDAR-005) | Estado pendiente de reconciliación; RESP-CALENDAR-ERROR-004; no se declara cancelada |

Extender el `FakeCalendarAdapter` (T4) con: intervalos busy inyectables por calendario y por test, modo de fallo por operación (`raise_on: query|create|delete`), simulación de timeout-tras-crear (la operación surte efecto pero lanza), y unicidad de id de evento.

**Commit:** `test: add adversarial suite for slice 2B-1 visit scheduling (38 cases)`

### T2 — `feat:` Modelos y migración

`Appointment` y `AppointmentChange` exactamente según data-matrix §17 y §18. Índice único parcial: `(appointment_date, start_time)` WHERE `appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','RESCHEDULED')`. `Holiday` (`holiday_date` único, `name`, `source` enum `SEEDED|MANUAL`) y `BlockedDate` (`blocked_date`, `reason`, actor, timestamps). Registrar todos en `models_registry.py`. Revisión Alembic: la siguiente libre tras rebase.

**Commit:** `feat: add appointment, holiday and blocked-date models`

### T3 — `feat:` Seed de festivos

Dependencia `holidays` (PyPI) SOLO como herramienta de seed (script `scripts/seed_holidays.py`, años actual+2, Colombia con traslados Emiliani), nunca consultada en runtime — el runtime lee exclusivamente la tabla. El seed es idempotente (upsert por fecha) y no pisa registros `MANUAL`.

**Commit:** `feat: seed Colombian holidays table`

### T4 — `feat:` Interfaz CalendarAdapter y fake

`app/calendar/adapter.py`: protocolo con `get_busy_intervals(date, calendar_ids) -> list[BusyInterval]`, `create_event(event_id, summary, start, end) -> ExternalEventRef`, `delete_event(event_id)`, `get_event(event_id)`. Excepciones tipadas: `CalendarUnavailableError`, `AlreadyExistsError`, `EventNotFoundError`. `FakeCalendarAdapter` con los controles de test descritos en T1. Selección por `CALENDAR_ADAPTER` en configuración.

**Commit:** `feat: add calendar adapter protocol with fake implementation`

### T5 — `feat:` Motor de disponibilidad

`app/scheduling/availability.py`: servicio que implementa la triple intersección. Las reglas puras (día, festivo, bloqueo, anticipación, slots) en funciones deterministas sin IO, testeables aisladas — mismo principio que `select_next_question`. La consulta freebusy y la de citas locales se orquestan alrededor, nunca dentro de las funciones puras.

**Commit:** `feat: add availability engine with rules-local-freebusy intersection`

### T6 — `feat:` Flujo conversacional de visita

Estados `WAITING_FOR_APPOINTMENT_DATE → WAITING_FOR_APPOINTMENT_SELECTION → APPOINTMENT_PENDING_CONFIRMATION → APPOINTMENT_CONFIRMED` según states.md/flows.md, con recolección de fecha, selección contextual de hora, asistentes (máx 3, excepción ⇒ handoff), motivo y nombre, y resumen de confirmación (BR-APT-012/013).

**Commit:** `feat: wire visit scheduling conversation flow`

### T7 — `feat:` Creación en dos transacciones

El flujo de TC-AGD-024/027/028: txn corta de inserción PENDING con revalidación, adapter fuera de txn con id = `appointment_id.hex`, txn de confirmación. Rutas de fallo exactas de la suite.

**Commit:** `feat: two-phase appointment creation with external calendar sync`

### T8 — `feat:` Recordatorio

Reutilizar el outbox con `scheduled_at`; hora de envío configurable (`REMINDER_SEND_HOUR`, default 09:00 del día anterior). Dedupe lógico por cita.

**Commit:** `feat: schedule visit reminders via outbox`

### T9 — `feat:` Reprogramación y cancelación

FL-011 completo: identificación de cita activa, validación del nuevo horario como cita nueva, `AppointmentChange`, y cancelación con confirmación previa y eliminación del evento externo. La original nunca se pierde antes de confirmar la nueva.

**Commit:** `feat: add visit reschedule and cancellation flows`

### T10 — `feat:` Admin de fechas bloqueadas y festivos

Endpoints autenticados: CRUD de `BlockedDate`, alta manual de `Holiday`, listado de citas del día para el Business Manager.

**Commit:** `feat: add blocked dates and holidays admin API`

### T11 — `docs:` Cierre documental

Actualizar `AGENTS.md` con: modelo de triple intersección, id externo = `appointment_id.hex`, freebusy multi-calendario, festivos solo desde tabla. Verificar coherencia con states.md (los estados ya existen; si algo difiere, reportar, no improvisar).

**Commit:** `docs: record slice 2B-1 scheduling decisions`

## 4. Criterios de aceptación globales

1. 38/38 adversariales en verde sin modificar los tests (salvo corrección documentada contra regla escrita).
2. Suite completa + `ruff` + `make migrate-cycle` en verde (DB propia del worktree vía `CEIBA_DB_NAME`).
3. TC-AGD-026 probado contra Postgres real con concurrencia efectiva, no simulada.
4. Grep de verificación: ninguna importación de librerías de Google en `app/` (eso es 2B-2).
5. Las funciones de reglas de fecha son puras: sin sesión de DB, sin adapter, sin reloj implícito (el "hoy" entra como parámetro).

## 5. Fuera de alcance

- Integración real con Google Calendar (2B-2).
- Registro de NO_SHOW y métricas de inasistencia (post-MVP según BR-APT-018, solo el estado existe).
- Lista de espera por slot; notificaciones al Business Manager más allá del calendario.
