# Entrega para revisión de Claude — noviazgo / PROPOSAL

Base: `main 3e01706ffd98a9bb40bf822f1df047065f4c0ac2`.
Rama: `fix/proposal-noviazgo-catalog-capture`, creada en worktree limpio bajo
`~/g1-noviazgo-2026-10-05/worktree`. El main y sus archivos ajenos sin seguimiento
permanecen intactos. No migraciones, estados, pending_action ni plantillas nuevas.
No despliegue, merge, tag, amend, rebase ni force push.

## G1 — hallazgos reportados antes de implementar

### M1 — call sites y punto de integración

En el SHA base, todos los consumidores de `resolve_catalog_event_type_label` son:
`app/event/event_type.py:18`, `app/orchestrator/service.py:620` (clasificación
previa al LLM) y `app/orchestrator/service.py:804` (captura). El único consumidor
de `resolve_fixed_price_information_type` es `app/orchestrator/service.py:2340`.

Una GENERAL_INFORMATION/catalog_request sin entidad pasa por
`service.py:2388–2415`: busca lead/event activos y llama
`app/catalog/service.py:94–154`. Allí `candidate = classified_event_type or
 event_type`; si ninguno existe, encola RESP-CATALOG-002. Se puede resolver el
texto en el handler de información antes de esa llamada. La integración que
**evita** el clasificador está en `app/channel/inbound.py:271–275` →
`deterministic_booking_or_catalog_classification`, antiguo `service.py:619–633`.

El normalizador estructurado de `app/event/event_type.py` sigue usando igualdad
completa; la captura textual y la información usan el nuevo matcher. No se
ensancha la validación de enums del backend a frases arbitrarias.

### M2 — exclusión del extractor

`git log -S 'intentionally remains excluded'` y blame de inbound.py:50–54
atribuyen el comentario y la lista a `6ce8b76` (2026-08-24), «feat: route capture
interruptions and preserve service order». El diff no da razón funcional para
excluir catálogo. `git log -S RESP-CATALOG-002` sobre states/decisions muestra
`4c0c70c`, documentación de captura contextual sin estado nuevo; no justifica
excluir el extractor. No se encontró una razón documentada que contradiga R4.

Flows.md conservaba la regla anterior de igualdad completa y precedencia de la
entidad; se alineó explícitamente con R2/R3/R4. No fue una condición de STOP de M2.

### M3 — secuencias existentes (fijadas en G2)

Solicitud explícita/captura con tipo PROPOSAL conocido y mapa PROACTIVE:
`handle_explicit_catalog_request` permite modos ON_REQUEST y PROACTIVE, usa
trigger EXPLICIT_REQUEST y encola **solo DOCUMENT** con el asset solicitado y
caption renderizado desde RESP-CATALOG-001. No hay texto independiente antes del
PDF. Cuando existe lead, crea catalog_send vinculado a ese outbox. Sin lead,
la ruta existente envía DOCUMENT y no crea catalog_send (no inicia captura de lead).

Información de precio fijo: RESP-EVENTS-PROPOSAL-001 más el DOCUMENT con caption
RESP-CATALOG-001 y catalog_send/PROACTIVE. Con SELF_SERVICE_BOOKING_ENABLED=true:
TEXT → DOCUMENT, con after_outbox_id. Con el flag apagado: DOCUMENT → TEXT,
conservando la secuencia previa. G2 fija el flag true y seed de lead para verificar
el registro catalog_send en ambas rutas. La deduplicación PROACTIVE se conserva.

### M4 — fallback y preguntas con variables

`handle_ai_unavailable` primero audita AI_UNAVAILABLE. Los estados críticos son
APPOINTMENT_PENDING_CONFIRMATION, WAITING_FOR_APPOINTMENT_DATE,
WAITING_FOR_APPOINTMENT_SELECTION y QUOTE_REQUEST_READY: crean handoff SYSTEM_ERROR
URGENT. Luego tiene prioridad la pregunta de ubicación → RESP-LOCATION-002 con
map_url. Estas ramas se conservaron y se verificaron para cada estado.

Se consulta `get_latest_response(sessionmaker, last_question_code)`: última
versión de KnowledgeEntry, sin revivir una versión APPROVED anterior a una DRAFT.
La consulta y el render usan el repositorio de conocimiento existente. No es HTTP.

Inventario de preguntas reales y aplicación de R5, fuera de estados críticos y
ubicación (los grupos dependen también de la última pregunta, no solo del pending):

| Pending_action | Pregunta sin variables: repetir si APPROVED | Pregunta con variables: RESP-DISCOVERY-002 |
| --- | --- | --- |
| COLLECT_CATALOG_EVENT_TYPE | RESP-CATALOG-002 | — |
| COLLECT_EVENT_TYPE | RESP-EVENT-DATA-013; RESP-GREETING-001; RESP-PRICE-001 | — |
| COLLECT_GUEST_COUNT | RESP-EVENT-DATA-004 | RESP-EVENT-DATA-005: guest_count_range, si fuera la última pregunta |
| COLLECT_EVENT_DATE | RESP-EVENT-DATA-001 | RESP-EVENT-DATA-003: resolved_date |
| COLLECT_CUSTOMER_NAME / COLLECT_BOOKING_NAME | RESP-CUSTOMER-001 / 003 | RESP-CUSTOMER-002: customer_name, si fuera la última pregunta |
| COLLECT_BUDGET | RESP-BUDGET-001 | — |
| COLLECT_SERVICES | RESP-EVENT-DATA-006; RESP-SERVICES-RETRY-001 | — |
| CLASSIFY_MESSAGE | RESP-FALLBACK-001 / 002 / 004 | — |
| SELECT_VISIT_DATE | RESP-VISIT-003 | —; estado crítico tiene prioridad |
| CONFIRM_VISIT_DATE | Depende de la pregunta guardada | RESP-EVENT-DATA-003: resolved_date |
| SELECT_VISIT_TIME | RESP-VISIT-TIME-002 / 004 | RESP-VISIT-TIME-001: appointment_options, visit_date; 003: appointment_options |
| COLLECT_VISIT_ATTENDEES | RESP-VISIT-DATA-001 / 002 | — |
| COLLECT_VISIT_REASON | RESP-VISIT-DATA-003 | — |
| CONFIRM_APPOINTMENT / CONFIRM_RESCHEDULE | Depende de la pregunta guardada | RESP-VISIT-CONFIRM-001: event_type, visit_attendee_count, visit_date, visit_time; 002: visit_attendee_count, visit_date, visit_time; 003: visit_date, visit_time |
| CONFIRM_VISIT_CANCELLATION | Depende de la pregunta guardada | RESP-CANCEL-VISIT-001: visit_date, visit_time |
| CONFIRM_QUOTE_REQUEST | Depende de la pregunta guardada | RESP-QUOTE-001: missing_field; resúmenes 002/003/005/008 requieren variables |
| SELECT_BOOKING_PLAN | — | RESP-BOOKING-PLAN-001: plan_options |
| SELECT_BOOKING_DATETIME | RESP-BOOKING-DATETIME-001; RESP-BOOKING-UNAVAILABLE-001 | RESP-EVENT-DATA-003: resolved_date |
| SELECT_BOOKING_TIME | RESP-BOOKING-TIME-001; RESP-BOOKING-UNAVAILABLE-001 | — |
| CONFIRM_BOOKING | — | RESP-BOOKING-CONFIRM-001: booking_date, booking_time, deposit_amount, plan_name, total_amount |

El catálogo incluye además pending de despacho (ANSWER_INFORMATION, SEND_CATALOG,
CONFIRM_EVENT_CANCELLATION) sin una pregunta propia fija: se aplica la misma
condición a last_question_code. WAIT_FOR_HUMAN, WAIT_FOR_PAYMENT_REVIEW y
WAIT_FOR_RESERVATION_CONFIRMATION no habilitan respuestas en conversaciones
pausadas: los guards anteriores al fallback permanecen. None/NONE, código ausente,
no encontrado, última versión no APPROVED o allowed_variables distinto de []
conservan RESP-DISCOVERY-002 y la acción/contador previos. El nombre del pending
jamás se toma de context_reference del LLM.

### M5 — frecuencia INVALID_JSON, solo lectura

Resultado literal del censo de los últimos 30 días (`created_at >= now() - interval
'30 days'`), agrupado por task y prompt_version:

```text
          task           |      prompt_version      | total | invalid_json | percentage | failed_min_length | failed_median_length | failed_max_length
-------------------------+--------------------------+-------+--------------+------------+-------------------+----------------------+-------------------
 EVENT_TYPE_EXTRACTION   | event_type_extraction_v1 |    41 |            0 |       0.00 |                   |                      |
 INTENT_CLASSIFICATION   | intent_v4                |   204 |            4 |       1.96 |                13 |                   62 |               324
 RECEIPT_EXTRACTION      | receipt_v1               |     2 |            0 |       0.00 |                   |                      |
 SERVICES_CLASSIFICATION | services_v1              |     1 |            0 |       0.00 |                   |                      |
(4 rows)
```

[M5.out](M5.out) conserva stdout completo; [M5.sql](M5.sql) es la consulta exacta.
Cliente local intent_v4: **max_tokens no se envía**; temperature=0;
response_format={"type":"json_object"}; timeout explícito configurable
OPENROUTER_TIMEOUT_SECONDS, default 15 s (client.py:64/83, 318–319 y settings.py:154).
No se cambió el cliente, el prompt, sus parámetros ni el extractor IA.

### M6 — mapas 9/10 y envíos del asset

Asset `d34aebc0-6d51-44e2-99be-dc214afe672f`. Resultado literal:

```text
 map_id | event_type | send_mode |     map_created_at_utc     | audit_id |  actor  |            action            |    audit_created_at_utc
--------+------------+-----------+----------------------------+----------+---------+------------------------------+----------------------------
      9 | WEDDING    | PROACTIVE | 2026-10-05 13:30:13.544269 |     6900 | Leandro | CATALOG_EVENT_TYPES_REPLACED | 2026-10-05 13:30:13.544269
     10 | PROPOSAL   | PROACTIVE | 2026-10-05 13:30:13.544269 |     6900 | Leandro | CATALOG_EVENT_TYPES_REPLACED | 2026-10-05 13:30:13.544269
(2 rows)

 outbox_id | created_at_utc | conversation_id | phone_masked | status | sent_at_utc | catalog_send_id | trigger | current_lead_event_type | historical_type_note
-----------+----------------+-----------------+--------------+--------+-------------+-----------------+---------+-------------------------+----------------------
(0 rows)
```

No hay envíos de ese asset desde 2026-10-05 13:30 UTC, ni evidencia de un cliente
que lo haya recibido por WEDDING en esa ventana. catalog_send/outbox carecen de
columna histórica event_type: el query identifica explícitamente el tipo actual
del lead como tal, sin presentarlo como tipo histórico. Todos los teléfonos
habrían salido enmascarados con *** y cuatro dígitos; la consulta devolvió cero.

Audit 6900, Leandro, creó ambos mapas. Audit 6902 (13:31:34.124825 UTC) desactivó el
asset; 6903 (13:31:36.143344 UTC) lo reactivó. La evidencia más reciente del censo
es **6933**, Leandro, **2026-10-05 23:42:12.049075 UTC**, active=false. Esto difiere
de la condición activa del contexto inicial: el fix no activa PDFs de producción.

La primera consulta de auditoría filtró entity=catalog_event_type_map y devolvió
0 filas: la app registra CATALOG_EVENT_TYPES_REPLACED con otra entidad. La consulta
por acción/asset del mismo M6 identificó 6900; M6-maps corroboró ids 9/10 y tiempos.
No se ejecutaron otras consultas de producción fuera de M5/M6.

[M6.out](M6.out), [M6-maps.out](M6-maps.out), [M6.sql](M6.sql),
[M6-maps.sql](M6-maps.sql) y [commands.txt](commands.txt) contienen resultados,
esquemas, queries y comandos exactos. Wrapper G1-A:
`ssh -o BatchMode=yes ceiba-staging-deploy`, docker compose exec -T db,
PGOPTIONS default_transaction_read_only=on y statement_timeout=15000. Cada archivo
entra por stdin, empieza BEGIN READ ONLY, termina ROLLBACK y usa \d para las tablas
antes de cada SELECT. Sin sudo, su ni cambio de usuario.

### M7 — mensajes no textuales sin respuesta propia

Los tipos admitidos sin respuesta propia son **sticker** y **reaction**. Los tipos
image/document/audio/video tienen respuesta de archivo o rutas de pago/caption;
location/contacts/interactive/button tienen su ruta; unsupported/unknown escalan.
R6 se fijó con tests sin cambiar route_non_text_in_session ni Inbox.

### M8 — BD local

Docker disponible, PostgreSQL local 16.14, contenedor chat_bot_ceiba-db-1 con IP
172.18.0.2 (sin puerto publicado). Se comprobó conexión local de solo lectura.
Los helpers exigen TEST_DATABASE_URL con 'test' en el nombre antes de preparar
schema. Se usaron exclusivamente bases ceiba_test_noviazgo* locales; no se tocó la
base de aplicación. El worktree reutiliza el intérprete del .venv original.
La suite completa se reserva a CI. No se agregaron migraciones, así que no se
necesitó make migrate-cycle local (CI lo ejecuta por su workflow existente).

## Requisitos implementados y referencias

| Requisito | Ruta:línea | Resultado |
| --- | --- | --- |
| R1 | app/conversation/catalog_event_type.py:15,127,138 | Alias pedidos, una sola tabla/matcher; precio fijo devuelve PROPOSAL o None y conserva prioridad comercial aclarada |
| R2 | app/conversation/catalog_event_type.py:57,91,115,122; docs/conversation/entities.md:588; docs/decisions.md:205 | Normalización, límites de palabra, descarte de coincidencias contenidas y ambigüedad |
| R3a | app/orchestrator/service.py:630,830 | Captura por frase antes del LLM; cierre y secuencia explícita |
| R3b | app/orchestrator/service.py:643; app/channel/inbound.py:271; service.py:2438 | Catálogo + tipo único sin pregunta ni clasificador; atajo PROPOSAL sin catálogo autorizado |
| R3c | app/orchestrator/service.py:202,218,868,2447,2509,4431 | Audit SYSTEM CATALOG_EVENT_TYPE_RESOLVED con event_type/matched_label/source; log DETERMINISTIC por turno |
| R4 | app/channel/inbound.py:52,344,949; app/orchestrator/service.py:889 | Extractor en captura y pregunta de catálogo; abandono después de ambas capas |
| R5 | app/orchestrator/service.py:4093,4151; docs/conversation/approved-responses.md:389 | Última pregunta APPROVED sin variables; conserva captura/contador, mantiene auditoría y ramas prioritarias |
| R6 | tests/test_noviazgo_catalog_capture_g2.py:280; app/channel/inbound.py:407 | Contrato sticker/reaction, sin IA ni cambios de estado/captura/contador |

No HTTP nuevo ni HTTP en transacción abierta; selección y envío siguen separados
por outbox/commit. audit_event y ai_execution solo reciben inserciones. Ningún
pending_action procede del LLM. app/catalog/service.py quedó sin cambios: se
reutilizó su comportamiento existente.

## G2 rojo, G3 verde y comandos

G2 fue commiteada roja en 0f1c220 antes de la implementación. La salida acreditada
es [G2-red.out](G2-red.out): 61 fallos por AssertionError y 3 verdes, sin ImportError.
Ejemplos literales:

```text
E   AssertionError: R2 must expose its phrase resolver before any import is required
E   assert False
E    +  where False = callable(None)
61 failed, 3 passed in 31.59s
```

Los dos archivos G2 son byte-idénticos al commit rojo, comprobados con [G2.sha256](G2.sha256).
La parametrización de todos los labels recoge automáticamente los nuevos alias;
por eso aumentó el número de casos después de G3 sin cambiar los bytes de tests.
No hubo corrección de mecanismo de G2 ni commit test adicional de ese tipo.

Comando G2 / comprobación final G3 del mismo contenido:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ceiba:ceiba@172.18.0.2:5432/ceiba_test_noviazgo_final \
  /home/emerson/desarollo/chat_bot_ceiba/.venv/bin/python -m pytest \
  tests/unit/test_noviazgo_catalog_resolver_g2.py \
  tests/test_noviazgo_catalog_capture_g2.py -q --tb=short
```

```text
79 passed in 34.34s
```

[G3-green.out](G3-green.out) acredita 94 verdes de G2 + fronteras antes del último
ajuste de procedencia. [audit-red.out](audit-red.out) demuestra el fallo específico
LLM vs DETERMINISTIC en la frase mixta. [audit-green.out](audit-green.out) acredita
16 fronteras verdes después de ese ajuste; [G2-final-green.out](G2-final-green.out)
acredita 79 verdes de G2 con el código final. [extraction-green.out](extraction-green.out)
acredita 44 verdes de normalización, extractor y orquestador previo.

[subsets-green.out](subsets-green.out) acredita el subset previo de catálogo,
medios, precio fijo y captura/extracción contextual:

```text
172 passed in 471.92s (0:07:51)
44 passed in 50.70s
16 passed in 50.69s
All checks passed!
```

Cobertura combinada: 311 casos distintos en los subsets afectados. La ejecución
inicial G3 de 94 y las repeticiones enfocadas de 79/16 no se suman como casos
nuevos. G2 y las fronteras se repitieron tras el último cambio de procedencia.

Subsets finales (la lista es deliberadamente parcial, no pytest global):

```bash
python -m pytest tests/test_fix2a_catalog_capture_adversarial.py \
  tests/test_w2a_inbound_media_adversarial.py \
  tests/conversational/test_romantic_catalog.py \
  tests/test_pr_b1_trigger_interruptions_adversarial.py \
  tests/unit/test_fixed_price_booking.py -q --tb=short
python -m pytest tests/unit/test_orchestrator.py \
  tests/unit/test_event_type_normalization.py \
  tests/test_pr_b_event_type_extraction_adversarial.py -q --tb=short
python -m pytest tests/test_noviazgo_fallback_boundaries.py -q --tb=short
ruff check .
```

## Decisiones y desviaciones declaradas

1. Emerson aclaró conservar prioridad PROPOSAL en precio fijo ante frases mixtas,
   resolviendo el conflicto R1/R2; el catálogo mantiene ambigüedad. El matcher es
   común y no se añadió regex de precio fijo. Los tests de prioridad existentes
   se conservan.
2. Emerson autorizó extender el determinismo a una mención única PROPOSAL sin la
   palabra catálogo y sin captura. Así el transcript completo G2-1 evita consumir
   3449 después de cerrar la captura en T1. Ruta y textos existentes.
3. Se actualizó la expectativa previa de EVENT_TYPE_QUESTION_CODES en
   tests/test_pr_b1_trigger_interruptions_adversarial.py conforme a R4. No se
   alteró ninguna expectativa G2.
4. Se corrigió la descripción obsoleta de flows.md además de los docs pedidos;
   es documentación dentro del alcance autorizado. No se tocó otro dominio.
5. El commit rojo test y los commits por área siguen el protocolo explícito del
   prompt, que prevalece sobre la regla general AGENTS de no commitear un rojo.
   Los commits de código se verificaron con su subset y ruff antes de commitear.
6. El extractor existente devuelve tipo validado o None; no tiene un campo de
   confianza en su schema. Se reutilizó su validación actual y el puente de entidad
   con confianza 1.0. No se cambió app/ai/client.py ni se reconstruyeron payloads.

## Diff de código, docs funcionales y tests frente al SHA base

Antes de incorporar los archivos de evidencia de esta carpeta:

```text
 app/channel/inbound.py                             |  11 +-
 app/conversation/catalog_event_type.py             |  96 +++++-
 app/orchestrator/service.py                        | 134 ++++++++-
 docs/conversation/approved-responses.md            |   8 +-
 docs/conversation/entities.md                      |  31 +-
 docs/conversation/flows.md                         |  30 +-
 docs/conversation/states.md                        |  32 +-
 docs/decisions.md                                  |  29 ++
 tests/test_noviazgo_catalog_capture_g2.py          | 327 +++++++++++++++++++++
 tests/test_noviazgo_fallback_boundaries.py         | 168 +++++++++++
 ...test_pr_b1_trigger_interruptions_adversarial.py |   2 +-
 tests/unit/test_noviazgo_catalog_resolver_g2.py    |  52 ++++
 12 files changed, 863 insertions(+), 57 deletions(-)
```

La entrega final incluye el diff --stat completo y el enlace real del único run
CI disparado al abrir el PR draft tras el único push. El workflow de la rama base
solo ejecuta push sobre main y pull_request: el push de esta rama no lanza otro
run. El despliegue está restringido a push sobre main.

Detenerse para revisión de Claude; no merge.
