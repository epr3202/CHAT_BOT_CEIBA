# Prompt Codex — Slice 2B-3: Cableado del flujo conversacional de visitas

## Contexto y motivación

El Slice 2B-1 construyó `VisitSchedulingService` (app/appointment/service.py) con
toda la lógica de agendamiento, y el 2B-2 lo conectó a Google Calendar real. Pero
**el orquestador nunca fue cableado**: `SCHEDULE_VISIT`, `RESCHEDULE_VISIT` y
`CANCEL_VISIT` siguen en `TRANSIENT_UNSUPPORTED_INTENTS` (destino: handoff), y
`git grep VisitSchedulingService app/orchestrator/` devuelve vacío. Un motor
completo sin cable al chasis.

Además, una prueba real en producción (2026-08-17, conversación 14) demostró el
bug de absorción: un cliente en `COLLECTING_EVENT_DATA` que dijo "quiero agendar
una visita" no fue enrutado; su siguiente mensaje ("el 19 de agosto", la fecha de
la VISITA) sobrescribió la fecha del EVENTO capturada antes (20 de febrero). Este
slice cablea el flujo Y define la política de interrupción que impide ese cruce.

Trabaja en un branch nuevo `slice-2b3-wiring` creado desde `origin/main`. Lee
`AGENTS.md` completo. Fuentes de verdad, en orden: este documento,
`docs/prompts/slice-2b1-agenda-prompt.md` (flujo y semántica de visitas),
`docs/conversation/` (estados, flujos, casos de prueba, respuestas aprobadas).

## Restricciones globales (innegociables)

- PROHIBIDO modificar `VisitSchedulingService` y `app/scheduling/`. Si el cableado
  revela un gap real en el servicio, DETENTE y repórtalo.
- PROHIBIDO crear migraciones. La suspensión/reanudación de captura debe usar el
  mecanismo existente de `app/conversation/pending_actions.py` y/o campos JSON ya
  existentes en `Conversation`. Si resulta imposible, DETENTE y repórtalo.
- PROHIBIDO todo texto nuevo hacia el cliente. Solo las plantillas RESP-* ya
  aprobadas en `docs/conversation/approved-responses.md` (RESP-VISIT-001…010,
  RESP-VISIT-DATA-*, RESP-VISIT-TIME-*, RESP-VISIT-CONFIRM-*, RESP-RESCHEDULE-*,
  RESP-CANCEL-VISIT-*, RESP-CALENDAR-ERROR-*). Si algún paso del flujo necesita
  un mensaje sin plantilla aprobada, DETENTE y reporta exactamente qué texto se
  necesita — la aprobación es de Leandro, no tuya.
- PROHIBIDO tocar: recordatorios (`process_due_reminders` — queda para otro
  slice), la selección de preguntas de captura, auth/admin, catálogos,
  `docker-compose*`, CI.
- Los mensajes internos (nombres de slots, labels, ids) JAMÁS se renderizan al
  cliente — regla de composición de respuestas vigente.
- Un commit por tarea, prefijos convencionales, sin amend/rebase de lo pusheado.

## Fase 0 — Descubrimiento con gate de aprobación

**Tarea 0.1**: `git switch -c slice-2b3-wiring origin/main`. Copia este documento
a `docs/prompts/slice-2b3-wiring-prompt.md`. Commit:
`docs: add slice 2B-3 specification as test source of truth`.

**Tarea 0.2 — GATE A (bloqueante, requiere aprobación humana)**: Construye y
reporta la TABLA DE CABLEADO completa antes de escribir cualquier test o código.
Para cada combinación relevante de (estado conversacional × intención/entrada del
cliente), la tabla declara: función o método del servicio invocado → response
code(s) posibles → estado destino → efectos (qué se persiste). Cúbrelo para:

- Inicio de agendamiento (`SCHEDULE_VISIT` desde estado limpio y desde
  `COLLECTING_EVENT_DATA`)
- `WAITING_FOR_APPOINTMENT_DATE` (fecha válida / inválida / no interpretable)
- `WAITING_FOR_APPOINTMENT_SELECTION` (slot válido / fuera de oferta / no
  interpretable)
- `APPOINTMENT_PENDING_CONFIRMATION` (sí / no / otra cosa)
- `RESCHEDULE_VISIT` y `CANCEL_VISIT` (con cita activa / sin cita)
- Fallo de calendario en cada punto donde el servicio lo reporta

La tabla se deriva de la firma real de los métodos del servicio, los
`VisitServiceResult.response_code` que retornan, y los flujos en
`docs/conversation/`. Donde el servicio y los docs discrepen, repórtalo como
hallazgo en vez de elegir por tu cuenta. DETENTE tras reportar la tabla y espera
aprobación explícita.

## Especificación del enrutamiento

**R1. Grupos de intención**: elimina `SCHEDULE_VISIT`, `RESCHEDULE_VISIT` y
`CANCEL_VISIT` de `TRANSIENT_UNSUPPORTED_INTENTS` (deja
`RESERVATION_INFORMATION`). Crea
`VISIT_INTENTS = {"SCHEDULE_VISIT", "RESCHEDULE_VISIT", "CANCEL_VISIT"}`.

**R2. Precedencia del routing** (orden exacto de evaluación; lo no mencionado no
cambia de posición):

1. Guards existentes de takeover/pausa/handoff activo — intactos.
2. `SENSITIVE_HANDOFF_INTENTS` — precedencia absoluta, intacta. Un
   `HUMAN_REQUEST` o `EMERGENCY` en cualquier estado de agenda va a handoff.
3. **NUEVO — estados de agenda**: si el estado es
   `WAITING_FOR_APPOINTMENT_DATE`, `WAITING_FOR_APPOINTMENT_SELECTION` o
   `APPOINTMENT_PENDING_CONFIRMATION`, el handler del estado interpreta el
   mensaje vía las funciones del servicio (`resolve_visit_date_text`,
   `interpret_visit_time`, confirmación). Un mensaje no interpretable o
   clasificado `UNKNOWN` en estos estados re-pregunta con la plantilla del
   estado y NO transiciona ni cae a `handle_unknown`. Un `VISIT_INTENT` de
   cambio de rumbo dentro de estos estados (p. ej. `CANCEL_VISIT` mientras
   espera fecha) se enruta según la tabla del Gate A.
4. **NUEVO — `intent in VISIT_INTENTS`**: enruta al flujo de visitas. Esta rama
   va ANTES del check de `COLLECTING_EVENT_DATA` — es la corrección del bug de
   absorción — con la política de interrupción I1.
5. Check de `COLLECTING_EVENT_DATA` / `COLLECTION_INTENTS` — intacto.
6. Resto — intacto.

**R3. Los handlers no contienen lógica de negocio**: llaman al servicio, encolan
la plantilla del `response_code` retornado, transicionan estado según la tabla, y
persisten vía los mecanismos existentes (`transition_conversation`,
`set_pending_action`, `enqueue_template`). Toda validación vive en el servicio.

## I1. Política de interrupción (captura ↔ visita)

- **Interrupción con confianza alta**: si el estado es `COLLECTING_EVENT_DATA` y
  llega un `VISIT_INTENT`, la visita gana SOLO si la confianza de la
  clasificación supera el umbral alto ya existente en el código (localiza la
  constante/mecanismo que ya usa el orquestador para decisiones por confianza —
  p. ej. lo que alimenta `CREATE_HANDOFF_LOW_CONFIDENCE`. Si no existe umbral
  reutilizable, repórtalo en el Gate A con tu propuesta; no inventes números).
  Con confianza baja, la captura conserva la prioridad actual (absorbe).
- **Suspensión sin pérdida**: al interrumpir, TODO lo capturado se preserva
  intacto. Se registra un marcador de reanudación con el mecanismo de
  `pending_actions` existente. La captura NO se cancela: se suspende.
- **Invariante de aislamiento de fechas**: mientras la conversación está en
  estados de agenda, ningún dato interpretado escribe campos del evento/lead
  (fecha, tipo, personas, presupuesto). Y a la inversa: el flujo de visitas
  jamás lee la fecha del evento como si fuera la de la visita. La fecha de la
  visita vive solo en `Appointment`. (Vigente además: "el silencio no es
  UNKNOWN" — nada de resolver `event_date_type` por ausencia.)
- **Reanudación**: al llegar a `APPOINTMENT_CONFIRMED` (o al cancelar el intento
  de agendamiento a mitad de camino), si existe marcador de reanudación, el
  orquestador re-encola la SIGUIENTE pregunta pendiente de captura usando las
  plantillas de captura ya aprobadas — no hay texto conector nuevo. Si la
  captura ya no está pendiente, no se reanuda nada.

## Fase 1 — Suite adversarial end-to-end (ANTES de implementar)

Esta es la lección del incidente: la suite de 2B-1 probó el servicio en
aislamiento y dio verde sobre un flujo inalcanzable. Esta suite prueba el nivel
que faltó: **webhook entrante → orquestador → servicio → plantilla saliente →
estado**, reutilizando el harness existente de los tests de integración (fixtures
de webhook simulado y fake de Meta ya presentes en `tests/`). El fake de
calendario es el adapter de siempre.

Archivo: `tests/test_slice2b3_wiring_adversarial.py`, casos TC-WIRE-001…, mínimo:

1. **Camino feliz completo**: mensajes de webhook desde estado limpio →
   `SCHEDULE_VISIT` → pregunta de fecha → fecha válida → oferta de slots →
   selección → confirmación → "sí" → estado `APPOINTMENT_CONFIRMED`, evento
   presente en el fake con fecha/hora correctas, plantillas correctas en cada
   paso (asertar response codes encolados).
2. **Reproducción del incidente 2026-08-17**: captura en curso con fecha de
   evento 2027-02-20 registrada → "quiero agendar una visita" (confianza alta)
   → "el 19 de septiembre" → la fecha del EVENTO sigue siendo 2027-02-20; la
   fecha propuesta de VISITA es la interpretada. El caso que faltó.
3. **Reanudación**: tras confirmar la visita del caso 2, el bot re-pregunta la
   siguiente pregunta de captura pendiente; completar la captura llega a
   `QUOTE_REQUEST_READY` con los datos del evento intactos.
4. **Confianza baja no interrumpe**: `VISIT_INTENT` con confianza bajo el umbral
   durante captura → la captura sigue (comportamiento actual preservado).
5. **Sin handoff espurio**: `SCHEDULE_VISIT` desde estado limpio NO crea
   handoff ni pausa (regresión contra el comportamiento previo al slice).
6. **`RESERVATION_INFORMATION` sigue en handoff** (regresión).
7. **Precedencia sensible**: `HUMAN_REQUEST` en `WAITING_FOR_APPOINTMENT_DATE`
   → handoff, estado de agenda abandonado según la tabla del Gate A.
8. **Slot ocupado excluido**: fake con intervalo ocupado → la oferta de slots
   no lo incluye (freebusy end-to-end).
9. **Reprogramación e2e**: cita confirmada → `RESCHEDULE_VISIT` → nueva
   fecha/hora → el evento del fake tiene el horario NUEVO (asertar vía
   `get_event`, no contadores).
10. **Cancelación e2e**: `CANCEL_VISIT` → confirmación → evento ausente del
    fake, estado final según tabla.
11. **`UNKNOWN` dentro de estado de agenda**: mensaje no interpretable en
    `WAITING_FOR_APPOINTMENT_DATE` → re-pregunta con la plantilla del estado,
    estado sin cambio, cero escrituras al lead.
12. **Calendario caído en confirmación**: fake con `raise_on` → plantilla
    `RESP-CALENDAR-ERROR-*` según el código del servicio, sin cita confirmada,
    estado coherente con la tabla.
13. **Sin cita activa**: `RESCHEDULE_VISIT` y `CANCEL_VISIT` sin cita → los
    response codes que el servicio define para ese caso.

Commit: `test: add end-to-end adversarial suite for visit flow wiring (13+ cases)`.
**GATE B**: la suite debe estar EN ROJO (el cableado no existe). Reporta el
conteo exacto de rojos y DETENTE si algún caso pasa en verde — un verde
prematuro significa que el caso no prueba lo que dice.

## Fase 2 — Implementación

Hasta suite completa del repo en verde, cero regresiones. Commits:

1. `feat: route visit intents to scheduling flow in orchestrator`
2. `feat: add appointment state handlers wired to VisitSchedulingService`
3. `feat: implement capture interruption and resumption policy`

(Si el corte natural difiere, propón el ajuste en el reporte del Gate A.)

## Reporte final

Tabla de cableado final (si cambió tras el Gate A, marca qué), commits, números
exactos de la suite (rojo inicial de la Fase 1 y verde final), y desviaciones —
que deben ser ninguna. Recuerda: cualquier necesidad de plantilla nueva, gap del
servicio, o imposibilidad sin migración = DETENTE y reporta, no improvises.

---

# Enmienda 1 al prompt Slice 2B-3 — Autorizaciones post-Gate A y re-alcance

Agrega este documento al final de `docs/prompts/slice-2b3-wiring-prompt.md`.
El Gate A queda APROBADO con re-alcance: el slice ahora es "completar la capa
conversacional de 2B-1 + cablear". La tabla de cableado reportada se adopta como
anexo normativo de la spec, con las resoluciones de abajo donde marcaba
"no determinable" o "bloqueado".

## Proceso (vigente para esta máquina sin DB local)

- Commits `docs:` requieren solo ruff verde, no pytest.
- Hasta que exista PostgreSQL local: los commits de código se permiten con ruff
  verde local, y el gate verde de pytest se verifica en el CI de GitHub Actions
  con cada push del branch (el workflow existente corre la suite en PRs).
  PROHIBIDO absoluto: push a `main` desde esta máquina; todo por PR.
- Los archivos `tests/unit/test_ai_client.py` y
  `tests/unit/test_event_type_contract_adversarial.py` con cambios preexistentes:
  NO los toques ni los incluyas en ningún commit. Su diagnóstico (probable CRLF)
  es tarea humana, no tuya.

## Autorizaciones y resoluciones

**A1 — Migración única `0018`** (excepción explícita a la prohibición original):
`conversation.visit_draft JSONB NULL`; agregar `VISIT_SCHEDULED` al constraint de
estado de `Lead`; agregar `LATE_CANCEL` al constraint de `Appointment`. Nada más
en esa migración.

**A2 — `app/appointment/service.py` abierto**, acotado a los gaps de la tabla:

1. `resolve_visit_date_text` → parser determinista real de fechas en español:
   absolutas ("19 de septiembre", "19/09", "19 de septiembre de 2026"),
   relativas según `docs/conversation/` ("mañana", "próximo sábado", etc.), con
   inferencia de año a la próxima ocurrencia futura (nunca resolver a pasado) y
   resultado ternario: EXACTA / RELATIVA (needs_confirmation) / NO_INTERPRETABLE.
   Sin LLM. Si existe utilidad reutilizable en la captura, evalúa reutilizarla
   SIN modificar el parser de captura (su bug de "enero de 2027" es backlog
   aparte); si no, impleméntalo en el módulo appointment.
2. `interpret_visit_time` → interpretación real que distinga: slot válido de la
   oferta / hora válida fuera de oferta (`RESP-VISIT-TIME-004`) / no
   interpretable (`RESP-VISIT-TIME-003`) / caso 2 p. m. (`RESP-VISIT-TIME-002`).
3. `prepare_confirmation_summary` → selección correcta entre
   `RESP-VISIT-CONFIRM-001/002`, validación de nombre obligatorio, y variables
   de renderizado completas.
4. `VisitServiceResult` gana `variables: dict[str, str]` (default vacío,
   no-rompiente) y los campos necesarios para que los handlers rendericen
   `RESP-RESCHEDULE-001` y `RESP-CANCEL-VISIT-001` sin consultar modelos
   directamente.
5. `request_cancellation` y `request_reschedule` con MÚLTIPLES citas activas →
   `needs_handoff=True` con el response code que la tabla asigna. PROHIBIDO
   elegir una cita en silencio.
6. `_is_slot_available` → propaga `CalendarUnavailableError`; jamás la confunde
   con slot ocupado. Los puntos de la tabla "confunde caída con conflicto"
   quedan corregidos con esto.
7. `cancel_appointment` → aplica `LATE_CANCEL` según la regla de `flows.md`.
8. Falta el método de resumen de reprogramación (`RESP-RESCHEDULE-003` →
   `APPOINTMENT_PENDING_CONFIRMATION`): créalo espejo de
   `prepare_confirmation_summary`.

**A3 — Borrador de visita**: `visit_draft` acumula fecha → oferta de slots →
hora → asistentes → motivo a través de los webhooks; se limpia al confirmar,
cancelar el intento, o entrar a handoff. Los `pending_action` de visita ya
existentes marcan el paso; el draft lleva el payload. El invariante I1 se
re-enuncia: el draft JAMÁS escribe ni lee campos del lead/evento.

**A4 — Comportamientos interinos con plantillas aprobadas** (desviaciones
DOCUMENTADAS de `states.md`, pendientes de textos de Leandro):
- Fecha RELATIVA interpretada: re-preguntar con `RESP-VISIT-003` (sin plantilla
  de confirmación "¿te refieres al X?" aún).
- "No" en la confirmación: limpiar hora/fecha del draft (conservar nombre,
  asistentes, motivo) y volver a `RESP-VISIT-003`.
Marca ambos puntos con `# INTERIM(states.md):` en el código para localizarlos
cuando lleguen las plantillas.

**A5 — Umbral de interrupción**: `settings.ai_confidence_safe`. La banda
0.50–0.70 conserva su comportamiento actual de confirmación
(`RESP-FALLBACK-004`) — la interrupción de captura solo ocurre en la banda safe.

**A6 — Adapter compartido**: `get_calendar_adapter` se cachea a nivel de
aplicación (una instancia por proceso) para que el fake persista entre webhooks
en los e2e. Los tests lo sobreescriben vía la inyección existente.

**A7 — Estado de agenda × `SCHEDULE_VISIT`** (el "no determinable"): reiniciar
el intento — limpiar `visit_draft` y volver a `RESP-VISIT-003`. Estado de agenda
× `CANCEL_VISIT`: cancela el INTENTO en curso (limpia draft, vuelve a
`BOT_ACTIVE` o reanuda captura suspendida), no una cita confirmada; para citas
confirmadas la intención se atiende desde fuera del flujo de agendamiento.

## Fases re-alcanzadas

**Fase A — Completar el servicio.** Tests primero
(`tests/test_slice2b3a_service_completion_adversarial.py`) derivados de
`flows.md`/`states.md` y de esta enmienda: parser de fechas (absolutas,
relativas, no interpretables, inferencia de año, nunca pasado), diferenciación
TIME-003/004, variables de renderizado, multi-cita → handoff, freebusy caído
distinto de ocupado, LATE_CANCEL. GATE B-A: suite en rojo, reporta conteo.
Luego implementación (incluye migración 0018). Commits separados por gap.

**Fase B — Cableado.** Exactamente el prompt original (routing R1–R3, política
I1 con las resoluciones de esta enmienda, suite TC-WIRE e2e completa). GATE B-B:
suite en rojo antes de implementar; ningún caso verde prematuro.

Reporte final: agrega a lo original el resultado de ambas fases y el estado del
CI en el PR.

## Enmienda A7-bis — Interpretación determinista antes de intenciones de visita

Dentro de `APPOINTMENT_FLOW_STATES`, el intento de interpretación determinista
del mensaje según el estado se evalúa antes que `VISIT_INTENTS`:

- En `WAITING_FOR_APPOINTMENT_DATE`, una interpretación `EXACTA` o `RELATIVA`
  se despacha al handler de fecha e ignora la intención clasificada. Solo con
  `NO_INTERPRETABLE` aplican `SCHEDULE_VISIT`, `CANCEL_VISIT` o
  `RESCHEDULE_VISIT`.
- En `WAITING_FOR_APPOINTMENT_SELECTION`, cualquier interpretación de hora
  distinta de `NO_INTERPRETABLE` se despacha al handler de selección e ignora
  la intención clasificada. Solo si la hora no es interpretable aplican las
  intenciones de visita.
- En `APPOINTMENT_PENDING_CONFIRMATION`, la interpretación contextual de sí/no
  se despacha al handler de confirmación antes que las intenciones de visita.
  Solo si el mensaje no expresa confirmación ni rechazo aplican las intenciones
  de visita.

Las intenciones sensibles conservan precedencia absoluta en el routing, fuera
del despachador de estados de agenda. A7 continúa vigente cuando la
interpretación determinista correspondiente falla.
