# Prompt Codex — Slice 2B-2: Adapter real de Google Calendar

## Contexto

Trabajas sobre el branch `slice-2b1-agenda` del repo CHAT_BOT_CEIBA. El Slice 2B-1
(motor local de agendamiento de visitas) está completo en este branch con
`FakeCalendarAdapter`. Este slice implementa el adapter real contra la API REST de
Google Calendar, cumpliendo exactamente el Protocol `CalendarAdapter` definido en
`app/calendar/adapter.py`. No se modifica el motor de disponibilidad ni el flujo
conversacional: solo se agrega el proveedor real, su factory, su configuración y un
script de diagnóstico operacional.

Lee y respeta `AGENTS.md` en su totalidad. Invariantes que aplican directamente aquí:

- Nunca ejecutar llamadas HTTP dentro de una transacción de base de datos abierta
  (este slice no toca la DB, pero el adapter será consumido por código que sí:
  el adapter no debe abrir sesiones ni recibir sesiones).
- Los documentos en `docs/` son la fuente de verdad. No improvises comportamiento
  no especificado aquí.
- Un commit por tarea, prefijos `feat:` / `test:` / `docs:` / `chore:`.
- Flujo obligatorio: spec (Fase 0) → suite adversarial (Fase 1) → implementación
  (Fase 2). La suite se deriva de este documento, NO de la implementación.

---

## Fase 0 — Spec como fuente de verdad

**Tarea 0.1** — Rebase del branch sobre `origin/main`:

```bash
git fetch origin
git rebase origin/main
```

El único commit nuevo en `main` es `2b2c3ac` (chore de volúmenes docker-compose,
sin overlap con este branch). Si el rebase produce cualquier conflicto, DETENTE y
repórtalo sin resolverlo.

**Tarea 0.2** — Copia este documento completo a
`docs/prompts/slice-2b2-gcal-prompt.md` y commitea:

```text
docs: add slice 2B-2 specification as test source of truth
```

**Tarea 0.3 — Gate de verificación (bloqueante)** — Antes de escribir tests,
verifica en `app/appointment/service.py` y en la spec de 2B-1
(`docs/prompts/slice-2b1-agenda-prompt.md`) que el flujo cancelar-y-reagendar
genera un **appointment nuevo con id nuevo** (nunca reutiliza el id de un
appointment cancelado para un nuevo evento de calendario). Esto es crítico porque
Google Calendar responde `410 Gone` para siempre al intentar crear un evento con
el id de un evento previamente borrado.

- Si se confirma: continúa, y deja constancia de la verificación (archivo y
  líneas) en el mensaje del commit de la Fase 1.
- Si NO se confirma o hay ambigüedad: DETENTE y repórtalo. No "arregles" el
  service por tu cuenta — está fuera del alcance de este slice.

---

## Especificación

### E1. Settings (`app/config/settings.py`)

```python
calendar_adapter: Literal["fake", "google"] = Field(default="fake", alias="CALENDAR_ADAPTER")
google_service_account_file: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_FILE")
```

(`google_calendar_id` y `google_freebusy_calendar_ids` ya existen; no los toques.)

Actualiza `.env.example` con las tres variables del adapter google y un comentario
de una línea por cada una. Valores de ejemplo, nunca reales.

### E2. Dependencia

Agrega `google-auth` a `dependencies` en `pyproject.toml`. Es la ÚNICA dependencia
nueva permitida. NO agregues `google-api-python-client` ni `google-auth-httplib2`:
el adapter habla con la REST API directamente vía `httpx` (ya presente), porque el
client oficial es síncrono y este stack es async.

### E3. `GoogleCalendarAdapter` (`app/calendar/google_adapter.py`)

Implementa el Protocol `CalendarAdapter` sin modificar `adapter.py` salvo lo
indicado en E4. Módulo nuevo para mantener `adapter.py` (protocolo + fake) libre
de dependencias de Google.

**Constructor con inyección explícita para testabilidad:**

```python
class GoogleCalendarAdapter:
    def __init__(
        self,
        calendar_id: str,
        service_account_file: str,
        http_client: httpx.AsyncClient | None = None,
        token_provider: Callable[[], Awaitable[str]] | None = None,
    ) -> None: ...
```

**Autenticación (token_provider por defecto):**

- `google.oauth2.service_account.Credentials.from_service_account_file(...)` con
  scope `https://www.googleapis.com/auth/calendar`.
- El refresh de google-auth es síncrono: ejecútalo con `asyncio.to_thread(...)`.
  El token expira en ~1h; cachea el token y refresca solo cuando
  `credentials.valid` sea falso o falten <300 segundos de vigencia.
- Si el archivo de credenciales no existe o es ilegible, el error debe emerger en
  la PRIMERA llamada del adapter como `CalendarUnavailableError` con mensaje
  claro (no en el constructor: el constructor no hace I/O).
- Nunca loguear contenido del credencial ni el token.

**Zona horaria:** todas las ventanas de tiempo se construyen en
`America/Bogota` (`zoneinfo.ZoneInfo`), consistente con el resto del proyecto.
Los datetimes devueltos son siempre timezone-aware.

**`get_busy_intervals(target_date, calendar_ids)`:**

- `POST https://www.googleapis.com/calendar/v3/freeBusy` con:
  - `timeMin` = `target_date` 00:00:00 America/Bogota en RFC3339
  - `timeMax` = `target_date` 23:59:59 America/Bogota en RFC3339
  - `timeZone` = `"America/Bogota"`
  - `items` = `[{"id": cal_id} for cal_id in calendar_ids]`
- Parsea `calendars.<id>.busy[]` de TODOS los calendarios a `BusyInterval` con
  datetimes aware.
- **REGLA CRÍTICA — fallo ruidoso:** si la respuesta contiene
  `calendars.<id>.errors` (lista no vacía) para CUALQUIER calendario solicitado,
  o si algún calendario solicitado NO aparece en la respuesta, lanza
  `CalendarUnavailableError` incluyendo el id del calendario afectado en el
  mensaje. La API devuelve HTTP 200 con calendarios inaccesibles marcados solo en
  ese campo `errors`; ignorarlo convertiría un sharing revocado en "todo libre" y
  produciría dobles reservas silenciosas. Este comportamiento es innegociable.

**`create_event(event_id, summary, start, end)`:**

- Valida `event_id` contra `^[0-9a-v]{5,1024}$` (charset base32hex minúscula que
  exige Google) ANTES de cualquier HTTP; si no cumple, lanza `ValueError`. Los
  UUID de appointment se mapean vía `uuid.hex` (sin guiones), que cumple el
  charset — la validación existe como defensa, no como transformación: el adapter
  NO transforma ids, los recibe ya normalizados.
- `POST /calendars/{calendar_id}/events` con body
  `{"id": event_id, "summary": summary, "start": {"dateTime": ..., "timeZone": "America/Bogota"}, "end": {...}}`.
- Devuelve `ExternalEventRef` construido desde la respuesta.

**`delete_event(event_id)`** → `DELETE /calendars/{calendar_id}/events/{event_id}`.

**`get_event(event_id)`** → `GET /calendars/{calendar_id}/events/{event_id}`;
si el evento devuelto tiene `status == "cancelled"`, trátalo como no encontrado.

**Mapeo de errores HTTP (tabla exhaustiva, igual en los cuatro métodos salvo
donde se indica):**

| Condición | Excepción |
|---|---|
| `httpx.TimeoutException`, `httpx.ConnectError`, cualquier `httpx.TransportError` | `CalendarUnavailableError` |
| HTTP 5xx, 429 | `CalendarUnavailableError` |
| HTTP 401, 403 | `CalendarUnavailableError` (mensaje debe indicar problema de credencial/permiso) |
| `create` → 409 o 410 | `AlreadyExistsError` (410 = id quemado por evento borrado; irrecuperable con ese id) |
| `delete` → 404 o 410 | `EventNotFoundError` |
| `get` → 404 o 410 | `EventNotFoundError` |

- Timeout de `httpx`: 10 segundos total.
- SIN retries dentro del adapter: la reconciliación de fallos (incluido el caso
  create-exitoso-pero-timeout) ya es responsabilidad del service, que la maneja
  vía `get_event` — el fake lo ensaya con `timeout_after_create`.

### E4. Factory (`app/calendar/adapter.py`)

Amplía `get_calendar_adapter(settings)`:

- `"fake"` → igual que hoy.
- `"google"` → valida que `google_calendar_id` y `google_service_account_file`
  sean no vacíos; si falta alguno, `ValueError` con mensaje que nombre la
  variable faltante. Si están, devuelve `GoogleCalendarAdapter` (import local
  dentro de la rama para no acoplar el módulo del protocolo a google-auth).
- Cualquier otro valor → `ValueError` (comportamiento actual).

NOTA: el factory NO decide qué calendarios consultar en freebusy — eso ya lo hace
el consumidor con `google_freebusy_calendar_ids`. No cambies esa responsabilidad.

### E5. Script de diagnóstico (`scripts/check_gcal_access.py`)

Script operacional permanente, ejecutable dentro del contenedor. Comportamiento:

1. Carga settings; si `calendar_adapter != "google"` o falta configuración,
   sale con código 2 y mensaje claro.
2. **Freebusy** contra TODOS los ids de `GOOGLE_FREEBUSY_CALENDAR_IDS`
   (separados por coma) para mañana (America/Bogota). Imprime por calendario:
   `OK <id> — N intervalos ocupados` o `FAIL <id> — <motivo>`.
3. **Ciclo de escritura** en `GOOGLE_CALENDAR_ID`: crea un evento de prueba con
   id `ceibadiag<epoch-en-hex>` (cumple el charset), summary
   `"[diagnóstico] verificación de acceso — borrar si aparece"`, duración 15
   minutos mañana a las 06:00; lo lee con `get_event`; lo borra con
   `delete_event`. Imprime cada paso.
4. Código de salida 0 solo si TODO pasó; 1 si cualquier paso falló. La salida
   debe permitir diagnosticar exactamente qué permiso falta (lectura freebusy
   del calendario principal vs escritura en Visitas La Ceiba).
5. El script usa el `GoogleCalendarAdapter` real (no reimplementa llamadas):
   es también una prueba de humo del adapter.

### E6. Documentación

Agrega a `AGENTS.md`, en la sección de calendario, dos líneas: (1) el campo
`errors` de freebusy siempre es fallo ruidoso, nunca se ignora; (2) los ids de
evento de Google derivan de `uuid.hex` del appointment y nunca se reutilizan
tras un borrado.

---

## Fase 1 — Suite adversarial (ANTES de implementar)

Archivo: `tests/test_slice2b2_gcal_adapter_adversarial.py`. Deriva los casos de
ESTA spec, no de tu implementación. Usa `respx` (ya en dev-deps) para mockear
HTTP con formas de respuesta reales de la API de Google. Para el token, inyecta
un `token_provider` falso — los tests NUNCA tocan google-auth ni leen archivos
de credenciales.

Casos mínimos (nómbralos TC-GCAL-001…):

**Freebusy**
1. Respuesta feliz con dos calendarios → intervalos de AMBOS, aware, correctos.
2. `errors` no vacío en UNO de los calendarios (HTTP 200) → `CalendarUnavailableError` con el id del calendario en el mensaje.
3. Calendario solicitado ausente de la respuesta → `CalendarUnavailableError`.
4. El request enviado contiene `timeMin`/`timeMax` del día correcto en America/Bogota y los ids solicitados (inspecciona el request capturado por respx).
5. HTTP 500 → `CalendarUnavailableError`; HTTP 403 → `CalendarUnavailableError` con mención de permisos.
6. Timeout de red → `CalendarUnavailableError`.

**Create**
7. Éxito → `ExternalEventRef` con id, summary y datetimes parseados del body de respuesta; el request incluye `"id"` y timeZone America/Bogota.
8. 409 → `AlreadyExistsError`.
9. 410 → `AlreadyExistsError`.
10. Timeout → `CalendarUnavailableError` (y NINGÚN retry: exactamente 1 request capturado).
11. `event_id` con guiones o mayúsculas → `ValueError` sin ningún request HTTP.

**Delete / Get**
12. Delete 404 → `EventNotFoundError`; delete 410 → `EventNotFoundError`.
13. Get 404 → `EventNotFoundError`.
14. Get de evento con `status: "cancelled"` en el body → `EventNotFoundError`.
15. Get feliz → `ExternalEventRef` correcto.

**Factory**
16. `CALENDAR_ADAPTER=google` con settings completos → instancia `GoogleCalendarAdapter`.
17. `CALENDAR_ADAPTER=google` sin `GOOGLE_SERVICE_ACCOUNT_FILE` → `ValueError` nombrando la variable; ídem sin `GOOGLE_CALENDAR_ID`.
18. `CALENDAR_ADAPTER=fake` sigue devolviendo el fake (sin regresión).

**Token**
19. El `token_provider` se invoca y su token viaja en `Authorization: Bearer` (inspecciona headers del request capturado).

Commit: `test: add adversarial suite for slice 2B-2 google calendar adapter (19+ cases)`
(incluye en el mensaje la constancia del gate 0.3). La suite debe estar EN ROJO
en este punto (el adapter no existe). Verifícalo y repórtalo.

## Fase 2 — Implementación

Implementa E1–E6 hasta que la suite completa del repo esté verde (la nueva Y las
existentes — cero regresiones en las suites de 2B-1, unit e integration).

Commits separados:
1. `feat: add google calendar settings and dependency`
2. `feat: implement google calendar adapter with loud freebusy failure`
3. `feat: extend calendar factory with google adapter`
4. `feat: add gcal access diagnostic script`
5. `docs: record google calendar invariants in AGENTS.md`

## Restricciones finales

- NO toques: `app/appointment/service.py`, `app/scheduling/`, migraciones,
  modelos, `docker-compose*`, `deploy.sh`, workflows de CI.
- NO agregues variables de negocio a `.env` (horarios, cupos, anticipación):
  eso pertenece a la futura tabla `Configuration` (scope.md §18.2).
- Si algo de esta spec resulta imposible o contradictorio con el código
  existente, DETENTE y repórtalo en lugar de improvisar una alternativa.

## Reporte final

Lista: commits creados, resultado de la suite (números exactos), constancia del
gate 0.3, y cualquier desviación — que debe ser ninguna.

---

# Enmienda 1 al prompt Slice 2B-2 — Resolución del gate 0.3 y tarea previa 2B-1.1

Esta enmienda extiende `docs/prompts/slice-2b2-gcal-prompt.md`. Agrégala al final de
ese documento y commitea antes de cualquier otra cosa:

```text
docs: amend slice 2B-2 spec with gate 0.3 resolution and reschedule fix
```

---

## Resolución del gate 0.3

El gate queda RESUELTO con dos veredictos, verificados por inspección arquitectónica:

**Veredicto A — cancelar-y-reagendar es seguro (sin cambios).**
`cancel_appointment` borra el evento externo vía `delete_event(external_calendar_id)`
y una reserva posterior inserta una fila `Appointment` nueva con `uuid.uuid4` →
id de evento nuevo. El escenario 410-por-id-quemado no ocurre en este flujo. La
línea de `AGENTS.md` sobre "los ids nunca se reutilizan tras un borrado" sigue
siendo el invariante correcto y este flujo lo cumple.

**Veredicto B — `reschedule_appointment` tiene un defecto funcional que este
slice DEBE corregir antes de implementar el adapter de Google.**
La reprogramación invoca `_create_or_reconcile_event` con el `event_id` de un
evento que ya existe (creado en la confirmación). `create_event` lanza
`AlreadyExistsError`, `_create_or_reconcile_event` lo traga (semántica correcta
para reconciliación post-timeout de la CONFIRMACIÓN, incorrecta aquí) y retorna
éxito. Consecuencia: la DB registra la nueva fecha/hora pero el evento de
calendario permanece en el horario anterior, silenciosamente. Con Google el
comportamiento sería idéntico (409 → tragado). La suite de 2B-1 no lo detectó
porque ningún caso asertaba el horario final del evento en el fake tras
reprogramar.

Por tanto se AUTORIZA modificar `app/appointment/service.py` y
`app/calendar/adapter.py` EXCLUSIVAMENTE en el alcance de la tarea 2B-1.1
descrita abajo. Todo lo demás de la restricción original sigue vigente.

---

## Tarea previa 2B-1.1 — `update_event` en el Protocol y corrección de reprogramación

Ejecutar ANTES de las Fases 1 y 2 del prompt original, con el mismo método:
spec (esta sección) → tests adversariales → implementación.

### Spec

**S1. Protocol (`app/calendar/adapter.py`)** — nuevo método:

```python
async def update_event(
    self,
    event_id: str,
    summary: str,
    start: datetime,
    end: datetime,
) -> ExternalEventRef: ...
```

Semántica: reemplaza summary/start/end del evento existente. Idempotente: aplicar
dos veces los mismos valores produce el mismo estado. Si el evento no existe →
`EventNotFoundError`.

**S2. `FakeCalendarAdapter`** — implementar `update_event`:
- Actualiza el `ExternalEventRef` almacenado (reemplazo del dataclass frozen).
- `"update" in raise_on` → `CalendarUnavailableError`.
- Evento inexistente → `EventNotFoundError`.
- Instrumentación consistente con el resto del fake: `update_call_count`,
  `updated_event_ids: list[str]`.

**S3. Service (`app/appointment/service.py`)** — nuevo método privado
`_update_or_reconcile_event(event_id, summary, start, end)`:
- Intenta `update_event`.
- `EventNotFoundError` → hace fallback a `create_event` (auto-reparación: si el
  evento se perdió externamente, reprogramar lo reconstruye). Si ese create
  lanza `AlreadyExistsError`, es una carrera imposible en este flujo: relanza
  como `CalendarUnavailableError`.
- `CalendarUnavailableError` → reintenta `update_event` UNA vez (el update es
  idempotente, el reintento simple es seguro — espejo del patrón existente en
  `_create_or_reconcile_event`). Si vuelve a fallar, propaga.

`reschedule_appointment` cambia EXACTAMENTE una llamada: usa
`_update_or_reconcile_event` en lugar de `_create_or_reconcile_event`. Nada más
cambia: ni el orden (validar slot → calendario → DB), ni los response codes
(`RESP-CALENDAR-ERROR-003` ante `CalendarUnavailableError`), ni la transacción.
`_create_or_reconcile_event` NO se modifica — su semántica es correcta para el
flujo de confirmación.

**S4. Fuera de alcance explícito**: el caso "calendario actualizado pero la
transacción de DB posterior falla por `IntegrityError`" ya existe en el diseño
actual de 2B-1 y NO se aborda aquí. No intentes resolverlo.

### Tests adversariales (antes de implementar S1–S3)

Archivo: `tests/test_slice2b11_reschedule_calendar_adversarial.py`, casos
TC-RESCHED-CAL-001…, derivados de esta spec:

1. **El caso que faltaba y motivó todo**: tras `reschedule_appointment` exitoso,
   el evento en el fake tiene el `start`/`end` NUEVOS (asertar contra
   `get_event`, no contra contadores).
2. `update_event` se invocó con el `event_id` original (mismo id, sin sufijos).
3. Evento ausente en el fake → fallback a `create_event` → reprogramación
   exitosa y evento con horario nuevo.
4. `raise_on={"update"}` transitorio (falla una vez, la segunda pasa) →
   reprogramación exitosa. [Nota: esto requiere que el fake permita fallo
   transitorio en update; espejo del patrón `timeout_after_create` — agrega
   `fail_update_once: bool` al fake si `raise_on` no basta.]
5. Fallo persistente de update → `RESP-CALENDAR-ERROR-003` y la fila
   `Appointment` conserva fecha/hora ORIGINALES (la DB no se toca si el
   calendario falló).
6. Doble reprogramación al mismo horario (idempotencia) → segundo update no
   rompe nada y el evento queda correcto.
7. Regresión: el flujo de CONFIRMACIÓN sigue usando `_create_or_reconcile_event`
   y su semántica de tragar `AlreadyExistsError` sigue intacta.

Commit tests: `test: add adversarial suite for reschedule calendar update (2B-1.1)`
— en rojo antes de implementar; verifícalo y repórtalo.

Commit implementación: `fix: reschedule now moves the external calendar event`

### Impacto en la Fase 2B-2 original (adapter de Google)

El `GoogleCalendarAdapter` implementa también `update_event`:
- `PATCH https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}`
  con body `{"summary": ..., "start": {...}, "end": {...}}` (mismos formatos que
  create).
- Mapeo de errores: fila adicional en la tabla —
  `update` → 404 o 410 → `EventNotFoundError`; el resto de la tabla aplica igual
  (timeouts/5xx/429/401/403 → `CalendarUnavailableError`). Sin retries en el
  adapter (el retry vive en el service, S3).

Casos adicionales para la suite de la Fase 1 del prompt original
(continúa la numeración TC-GCAL-):
- PATCH feliz → `ExternalEventRef` con los valores nuevos; el request capturado
  es método PATCH al path correcto con timeZone America/Bogota.
- PATCH 404 → `EventNotFoundError`; PATCH 410 → `EventNotFoundError`.
- PATCH timeout → `CalendarUnavailableError` con exactamente 1 request (sin
  retry en el adapter).

`scripts/check_gcal_access.py` extiende su ciclo de escritura: crear → leer →
**actualizar (mover 15 minutos)** → leer y verificar horario nuevo → borrar.

### Orden de ejecución final

1. Commit de esta enmienda (docs).
2. Tarea 2B-1.1: tests en rojo → implementación → suite completa verde.
3. Fases 1 y 2 del prompt original (con las adiciones de esta enmienda).
4. Reporte final único: agrega a lo pedido originalmente los resultados de
   2B-1.1 y la constancia de los dos veredictos del gate.
