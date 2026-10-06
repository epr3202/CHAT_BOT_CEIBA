# Catálogo explícito de precio fijo y contexto de reserva — conversación 205

Base: `main` `621eeead1aad96f301854ffca7e805ee02871a25`. Rama nueva:
`fix/fixed-price-catalog-context`. Un solo push; PR draft hacia main. Sin merge,
sin migraciones, sin plantillas nuevas, sin nuevos estados ni pending_action.

## G1 — mini-censo antes de implementar

El [censo original](G1.md) conserva las líneas del SHA base. No se encontró condición de STOP.

| Hallazgo | Traza en el SHA base y conclusión |
| --- | --- |
| M1 | `app/orchestrator/service.py:2505`, `:2530`, `:2565`, `:2599`, `:2628`: entidad firme de precio fijo → lead/evento → apply_event_type → texto aprobado → DOCUMENT PROACTIVE → FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO. Con contexto libre termina BOT_ACTIVE, pending None y pregunta RESP-EVENTS-{ROMANTIC,PROPOSAL}-001. `app/channel/inbox.py:227` obtiene contexto del backend; `service.py:507`, `:585`, `app/conversation/fixed_price_booking.py:90`, `:121`, `app/orchestrator/booking_flow.py:241` seleccionan planes y autoservicio por SELF_SERVICE_BOOKING_REASON. La solicitud final es PAYMENT_PENDING; RESERVED exige humano. |
| M2 | `app/orchestrator/service.py:2448` retornaba desde catalog_request antes de M1. `app/catalog/service.py:83` enviaba EXPLICIT_REQUEST sin crear lead/evento ni aplicar tipo. Sin lead, `catalog/service.py:334` omitía CatalogSend. `service.py:4293` solo persistía last_intent. La diferencia explica el turno siguiente de la conversación 205. |
| M3 | `app/orchestrator/service.py:1259`, `:1432`: SCHEDULE_VISIT reiniciaba el borrador y reinterpretaba texto, sin consumir la entidad de fecha; una fecha pendiente terminaba en RESP-VISIT-003. Existe RESP-EVENT-DATA-003 APPROVED, variable resolved_date, `docs/conversation/approved-responses.md:1022`. `booking_flow.py:331`, `:677` ya confirmaban esa fecha en reserva; CONFIRM_VISIT_DATE ya existe en `app/conversation/pending_actions.py:19`. |
| M4 | Conversación romántica 196, teléfono ***6242: estado actual CLOSED, pending/last_question/active_lead vacíos, reserva RESERVED. A las 2026-10-02 19:48:15.894851 UTC, SYSTEM creó lead/evento/tipo, auditó catálogo de precio fijo y restauró BOT_ACTIVE. Leandro confirmó RESERVED a las 20:02:40.230657 UTC; Calendar se creó a las 20:02:41.085120 UTC. |

[M4 literal: estado y 26 audits vinculados](M4-results.out), [SQL](M4.sql),
[stdout completo con esquemas](M4.out), [wrapper exacto](commands.txt).
Solo se ejecutó M4 en producción: SSH BatchMode al usuario permitido,
PGOPTIONS read-only, BEGIN READ ONLY, esquemas antes de cada SELECT, ROLLBACK.
Los audits se vinculan por conversation/lead/event/reservation; el resultado no
pretende incluir audits que únicamente contienen un ID de outbox.

El primer intento de M4 falló al aplicar jsonb_each a un JSON null. Se corrigió
solo el SELECT con jsonb_typeof y se repitió M4; la conexión fallida cerró la
transacción de solo lectura. El segundo terminó con exit 0 y ROLLBACK.
Se conserva la salida del intento fallido y no hubo otras consultas de producción.

## R1–R4 — implementación final

| Requisito | Ruta:línea y resultado |
| --- | --- |
| R1 | `app/orchestrator/service.py:2506`, `:2524`, `:2549`, `:2619`, `:2681`, `:2719`: catalog_request de tipo fijo pasa a la rama existente. Fuente: matcher único → entidad del clasificador → contexto backend. Solo las entidades PROVIDED/CORRECTED sin confirmación fijan tipo. Se crea/reutiliza Lead/Event y se audita apply_event_type; texto aprobado y PDF PROACTIVE; con autoservicio activo el texto precede al DOCUMENT. Una sola llamada de envío y dedupe por lead/asset. Auditoría FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO, mismo estado/pending del flujo romántico. Tipos no fijos y captura de catálogo conservan su ruta. |
| R2 | `app/conversation/fixed_price_booking.py:24`, `:35`, `:90`, `:95`, `:129`; `app/orchestrator/service.py:586`, `:593`, `:605`: contexto fijo + reserva usa autoservicio; visita explícita tiene prioridad antes de los atajos de fecha/plan/catálogo. Pendientes, pausas y bloqueos de solicitudes activas mantienen su precedencia. No se duplica vocabulario. |
| R3 | `app/appointment/service.py:70`, `:237`; `app/orchestrator/service.py:1437`, `:1473`, `:1514`: el/día N usa el parser público de fecha con guardas, conserva candidata y confirma con RESP-EVENT-DATA-003. «Sí» valida agenda; «no» descarta la candidata; respuesta desconocida repite. Otra fecha parcial confirma de nuevo y una absoluta aceptada se valida; otras relativas conservan RESP-VISIT-003. `app/orchestrator/booking_flow.py:207`, `:331`, `:677` consume la misma fecha y conserva date_confirmation hasta sí, antes de pedir hora. No hubo cambio de esquema. |
| R4 | `docs/conversation/flows.md:504`, `docs/conversation/states.md:3013`, `:704`, `docs/conversation/entities.md:2722`, `docs/decisions.md:249`, `:267`, `:280`: regla de catálogo explícito de precio fijo, conservación del contexto y confirmación del mes inferido. Código y docs de cada regla están en el mismo commit. |

Vocabulario único existente de reserva: **agendar, reservar, separar, apartar,
programar, cuadrar, quiero la fecha**. Visita: **visita, visitar, conocer el lugar,
ir a ver**. `is_explicit_visit_request` reutiliza la tabla y excluye los atajos
antes de llegar al clasificador; no calcula disponibilidad ni reserva nada.

Con autoservicio activo, tras el catálogo libre: **BOT_ACTIVE, pending None**, Lead/Event del tipo resuelto.
Tras «Me gustaría agendar para el 14»: **COLLECTING_EVENT_DATA,
SELECT_BOOKING_PLAN**, planes del tipo correcto y fecha candidata pendiente de
confirmación. Después de seleccionar plan se confirma la fecha antes de hora.

Fixtures de planes reutilizan `scripts/load_plans.py:19` sin consulta adicional a
producción: PROPOSAL PETALOS_ESTRELLAS 450000, CONFESION_LUNA 900000,
NOCHE_INOLVIDABLE 2500000 (exclusivo); ROMANTIC_DINNER RITUAL_CORAZON 250000,
ROMANCE_COPAS 400000, MANANAS_ENCANTO 450000 (fin de semana), CINEMA_AMOR 700000,
REFUGIO_DOS 1000000. Todos duran 180 minutos. Assets PROACTIVE de ambos tipos.

Los stubs usan el parsed_output 3455 literal, 611 bytes, SHA-256
`473d354b1395113d5e40cd4959880e4c1c3fb0a7ba72d3b083500bbe0ffbb7af`.
El harness existente aprueba sintéticamente versiones de los textos existentes
para los tests. Runtime conserva su validación de aprobación y handoff ante
KnowledgeRenderError; no se modifican plantillas ni aprobaciones. No se consultó
knowledge_entry en producción porque solo M4 estaba autorizado.
OpenRouter/Meta mockeados; Calendar fake con guardas de transacción, sin HTTP
bajo transacción abierta. El backend decide estado y pending; audit_event,
ai_execution y message siguen append-only.

## G2 rojo, commits y excepciones declaradas

[G2 rojo íntegro](G2-red.out), antes de modificar código:

```text
27 failed, 14 passed in 105.53s (0:01:45)
```

Los 27 fallos son AssertionError, sin ImportError ni errores de setup. Por ejemplo:
PDF-only frente al contrato TEXT + DOCUMENT y fecha None frente a la candidata
inferida. [Regresiones anteriores en rojo](G2-legacy-red.out): 3 failed,
34 deselected in 21.27s, también por AssertionError.

- `aac914e test:`: 41 casos G2, tras demostrar rojo.
- `f1ef944 test:`: tres contratos previos de catálogo explícito fijo ahora esperan
  Lead/Event, TEXT + DOCUMENT y PROACTIVE conforme a R1. Declarados antes del código.
- `7b32b4b fix:`: R1 y docs de catálogo/contexto.
- `6da2dda test:`: única corrección de expectativa congelada autorizada explícitamente
  por Emerson («Sí, corregir conforme a R3»). G2-1 exigía ausencia de fecha por error;
  ahora exige candidata 2026-10-14 y date_confirmation=True. El reloj del harness
  está en septiembre; por eso la candidata es octubre. [Diff exacto, gzip](G2-authorized-expectation.diff.gz).
  Se volvió a acreditar [rojo de esa corrección](G2-authorized-date-red.out):
  **1 failed in 6.01s**, None frente a 2026-10-14, antes de R3.
- `4d48af1 test:`: nueve límites adicionales de resolución/visita, sin modificar G2.
- `7718391 fix:`: R2 y decisión documentada.
- `e3787ce test:`: nueve casos adicionales de confirmación y límites del calendario.
- `7444c36 fix:`: R3 y docs.

[Hashes originales](G2.sha256) y [hashes tras la corrección autorizada](G2-authorized.sha256).
Solo cambia esa aserción; los tres archivos G2 finales coinciden byte por byte con
el congelado autorizado. No se cambiaron tests G2-2–G2-6 para hacerlos pasar.

Discrepancia previa reportada en G1: entities.md exige confirmar día+mes sin año,
pero los tests actuales aceptan esas fechas sin confirmación. Se conserva ese
contrato anterior; R3 añade confirmación del día sin mes. Para días inexistentes
en el mes siguiente (el 31), se conserva la próxima ocurrencia válida del parser
público. «día N» también usa esa regla; números aislados/cantidades no la disparan.
Durante la construcción de tests, antes del rojo oficial y del commit G2, se cambió
el acceso a clave por .get para evitar KeyError. El rojo oficial ya contiene solo
fallos de expectativa. No hay cambios de mecanismo ocultos ni plantillas nuevas.

## Verificación final

700 casos distintos en los cuatro subsets afectados, todos verdes. G2 contiene
41 de esos casos y se ejecutó también de forma independiente tras R3.

```text
G2:       41 passed in 64.26s (0:01:04)
Reservas: 193 passed in 428.67s (0:07:08)
Catálogo: 147 passed, 7 warnings in 445.40s (0:07:25)
Visitas:  191 passed in 193.65s (0:03:13)
Unitarios:169 passed in 1.18s
Ruff:     All checks passed!
git diff --check: OK
```

[Salida G2](G2-green.out), [reservas](final-booking-green.out),
[catálogo/general information](final-catalog-green.out), [visitas](final-visits-green.out),
[unitarios](final-units-green.out), [Ruff](final-ruff.out),
[comandos reproducibles](local-test-commands.txt), [diff --stat completo](diff-stat.out).
Los siete warnings son deprecaciones de HTTP_422_UNPROCESSABLE_ENTITY de
Starlette en rutas admin existentes. No hay fallos pendientes.

Las vistas .out eliminan espacios terminales y líneas vacías finales generados por pytest/psql
para mantener git diff --check limpio. Los originales byte por byte de las capturas
que tenían esos espacios se preservan en los archivos .gz junto a cada salida,
verificados contra la captura original: [hashes](literal-output-sha256.txt).
El diff de la corrección autorizada también se archiva exacto en gzip.

La suite completa se ejecuta exclusivamente en CI. Las bases locales usadas por
cada subset son independientes y contienen test en su nombre.

CI: este PR draft lanza un único workflow pull_request. El enlace al run y su
estado se añaden a la descripción del PR y al reporte de entrega después del
único push. No se hará merge; Claude debe revisar el diff.
