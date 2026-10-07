# Selección de plan después del catálogo — conversación 206

Base: `main` `f703533`. Rama: `fix/plan-selection-after-catalog`.
Este informe recoge la auditoría y la corrección de las partes A/B. El mandato
de Emerson autoriza continuar con CI, merge sin squash del fix y después del
PR #43, despliegue y verificación, sin revisión intermedia de Claude. Los
resultados de producción se registran por separado después del CD; este
documento no acredita que esas operaciones hayan terminado.

## G1 — cadena causal antes de G2

La auditoría se completó y comunicó antes de modificar la implementación.
Ventana: **2026-10-06 11:55–12:10 UTC**. El wrapper habitual usa SSH BatchMode,
`PGOPTIONS` con `default_transaction_read_only=on` y `statement_timeout=15000`,
`psql -X -v ON_ERROR_STOP=1`, `BEGIN READ ONLY`, inspección de esquemas y
`ROLLBACK`. [G1 detallado](G1.md) conserva las rutas y líneas del SHA base;
[evidencia acotada](G1.json) omite teléfonos. La captura inicial con datos
personales y otras conversaciones queda fuera del repositorio.

| Paso | Evidencia y conclusión |
| --- | --- |
| A1 — T1 | Mensaje 6883, **12:03:24.516516 UTC**: «Hola Me gustaría agendar una pedida de mano para el 14». Audits 6946–6954: NEW → BOT_ACTIVE → ANSWERING_INFORMATION → BOT_ACTIVE, lead/evento PROPOSAL y catálogo PROACTIVE, outbox 3421. La restauración del pendiente y la ausencia de alimentación del borrador en esa rama permiten reconstruir `pending_action = NULL` y `booking_draft = NULL` después de T1. Los audits registran estados; no contienen un snapshot histórico de esos dos campos. |
| A1 — T2 | Mensaje 6886, **12:04:30.795875 UTC**: «Me interesa confesión bajo la luna». Audit 6955: `HANDOFF_CREATED`, razón `RESERVATION_CONFIRMATION`, detalle «Ya existe una solicitud pendiente de pago». Audit 6956: BOT_ACTIVE → WAITING_FOR_HUMAN. La consulta actual devuelve `WAIT_FOR_HUMAN`, `RESP-HANDOFF-002` y borrador NULL. |
| A2 — clasificación | **Cero ai_execution** de la conversación 206 en la ventana. Las ejecuciones 3456/3457 son de la conversación 205; no son parsed_output de T2. El guard era elegible: BOT_ACTIVE, pending NULL, bot habilitado y autoservicio activo. `inbound.py:923` construye el contexto base; `inbox.py:227–229` incorpora `booking_event` desde `service.booking_event_context:508`, que consulta planes activos PROPOSAL/ROMANTIC_DINNER con el flag activo. El paso observado por autoservicio acredita esa ruta; no existe un snapshot persistido de facts para afirmar una lectura literal de su contenido. |
| A2 — matcher | REPL local con los ocho nombres/códigos de producción, iguales a PLAN_SEED: `match_booking_plan(T2, plans)` devuelve **CONFESION_LUNA**, PROPOSAL, precio del servidor **900000 COP**. El normalizador elimina tildes; las stop words eliminan «la» y conservan «bajo». |
| A3 — handoff | `inbound.classify_message:271` → `service.deterministic_booking_or_catalog_classification:595` → SELF_SERVICE_BOOKING → `service.orchestrate:295–302` → `booking_flow.handle_booking_start:249` → `has_pending_request:229–238` → `booking_flow.handoff:68` → `service.create_handoff_and_pause:4293`. La comprobación global por cliente encontró `f3fb9b04-1f40-4172-b9e2-b157b1ecf41a`, PAYMENT_PENDING, creada **2026-10-02 20:09:28.943665 UTC** en conversación **197**, antes de seleccionar el plan. Una conversación y lead nuevos no eliminan esa solicitud. |
| A4 — fecha | `service.handle_general_information:2619–2638` crea/reutiliza lead/evento; `:2681–2689` encola el catálogo; `:2716` restaura el pendiente. Esa rama no invocaba `resolve_visit_date_text` ni `consume_date_time`; además `booking_flow.handle_booking_start:252,270` reiniciaba el borrador. Por eso «el 14» no llegaba al parser de día sin mes ya implementado en #42. |

El handoff fue una decisión determinista del backend por una solicitud anterior
del cliente. No hubo fallo del matcher, JSON del LLM ni parsed_output real de T2
para congelar como stub. Los tests usan los dobles existentes para detectar
cualquier llamada inesperada; no atribuyen una clasificación ficticia al turno.

## R1–R4 — corrección

Las líneas de esta tabla corresponden a la propuesta actual; las del apartado
G1 corresponden exclusivamente a `f703533`.

| Requisito | Ruta:línea y comportamiento |
| --- | --- |
| R1 | `app/conversation/fixed_price_booking.py:112`; `app/orchestrator/service.py:597`; `app/orchestrator/booking_flow.py:252`, `:296`: la última pregunta aprobada de información de precio fijo y el tipo del lead identifican una continuación de catálogo. Solo se consideran planes activos de ese tipo. Una coincidencia única del matcher selecciona plan y continúa fecha/hora sin LLM, con «me interesa X», «quiero X», «el de X» o el nombre solo, con o sin tildes. La continuación puede preparar el borrador aunque exista una solicitud anterior; las demás entradas conservan el bloqueo inicial `:258`. |
| R2 | `app/conversation/fixed_price_booking.py:119`; `app/orchestrator/service.py:617`; `app/orchestrator/booking_flow.py:327`, `:530`: dos coincidencias o una respuesta de selección sin coincidencia preguntan `RESP-BOOKING-PLAN-001` con la lista existente. Se añade `catalog_plan_selection = true` al JSON del borrador solo al pedir la lista. Cada respuesta ambigua/desconocida en ese paso vuelve a preguntar sin agotar contador, llamar al LLM ni producir handoff. `:536` retira la marca al elegir plan. Los demás pasos y entradas genéricas conservan el escalamiento por dos fallos. |
| R3 | `app/orchestrator/service.py:2714`; `app/orchestrator/booking_flow.py:261`, `:344`, `:694`: la rama informativa consume una fecha interpretable con el resolvedor existente y conserva `date`/`date_confirmation` en booking_draft, sin instalar pending_action ni cambiar estado. Elegir plan preserva esa candidata y pregunta `RESP-EVENT-DATA-003` antes de hora cuando requiere confirmar la fecha absoluta. El parser de #42 conserva su contrato, incluida la siguiente ocurrencia válida de «el 31». |
| R4 | `docs/conversation/flows.md:2726`, `docs/conversation/states.md:2436`, `:2967`, `docs/decisions.md:296`: selección tras catálogo, repetición de la lista, fecha candidata y excepción inicial documentadas junto con la evidencia y el mandato operativo. |

El control global de duplicados permanece en
`app/orchestrator/booking_flow.py:644`, antes de `create_pending_reservation`.
Si existe PAYMENT_PENDING/PAYMENT_REVIEW del cliente, incluso manual o de otra
conversación, confirmar escala y no crea otra solicitud. Elegir un plan y
completar el borrador no bloquea una franja ni crea un evento de Calendar.

Se conservan las precedencias de humano explícito, visitas, FAQ y catálogo.
Los estados pausados mantienen silencio; el contrato existente no impide que
la clasificación se ejecute antes de aplicar ese silencio. La fecha meramente
informativa conserva la ruta del clasificador. Meta/OpenRouter se mockean con
respx y Calendar usa el fake del harness; ningún test llama servicios reales.

No se añaden migraciones, plantillas, estados ni pending_action. No se modifican
los servicios de reserva, los adaptadores ni el canal. La excepción a la
comprobación inicial de solicitudes se declara expresamente en states.md; el
control final obligatorio queda intacto. No se amplía la autoridad de la IA.

## G2 rojo y G3

| Ejecución | Resultado observado | Evidencia |
| --- | --- | --- |
| G2 inicial, antes del fix | **16 failed, 18 passed**, fallos de expectativa `AssertionError` | [G2-red.out](G2-red.out) |
| Transcript literal aislado con solicitud previa | **1 failed**; se reproduce WAITING_FOR_HUMAN en T2 | [G2-transcript-red.out](G2-transcript-red.out) |
| G3 adicional: elección ambigua/desconocida con fecha y repetición | **4 failed, 25 deselected**, antes de corregir esos límites | [G3-boundaries-red.out](G3-boundaries-red.out) |
| Primer intento de G2 verde | **33 passed, 1 failed**, expectativa nueva incorrecta sobre el día actual | [G2-first-green-attempt.out](G2-first-green-attempt.out) |
| Primer intento conjunto G2/G3 | **61 passed, 3 failed**, tres expectativas nuevas de G3 ajenas al contrato vigente | [G2-G3-first-green-attempt.out](G2-G3-first-green-attempt.out) |
| Reejecución de esos tres casos G3 corregidos | **3 passed, 26 deselected** | [G3-adjusted-boundaries-green.out](G3-adjusted-boundaries-green.out) |
| Catálogo completo, primer intento | **307 passed, 1 failed**; estímulo de un test existente incompatible con R2 | [catalog-first-attempt.out](catalog-first-attempt.out) |

Las correcciones de tests se declaran para evitar confundirlas con cambios de
producto:

1. Una expectativa nueva suponía que, siendo hoy 31 de octubre, «el 31» debía
   pasar al mes siguiente. El parser de #42 usa `>= today` y devuelve el mismo
   **31 de octubre**. Se corrigió esa expectativa y se añadió el caso
   **1 de noviembre + «el 31» → 31 de diciembre**. No se modificó el parser.
2. Un caso nuevo de G3 reenviaba literalmente T1 con «agendar» y suponía que
   debía volver a la rama informativa de catálogo. Con el contexto ya creado,
   ese mensaje inicia BOOKING según el contrato existente. Se corrigió el
   caso para probar por separado reentrega idempotente y repetición explícita
   de catálogo.
3. Dos variantes nuevas de G3, WAITING_FOR_HUMAN/HUMAN_ACTIVE, exigían además
   ausencia de LLM. El contrato existente exige silencio y ausencia de efectos
   de negocio. Se retiró únicamente esa suposición de clasificación.

Se alinea también un test existente, en un commit `test:` declarado:
`tests/test_noviazgo_fallback_boundaries.py` comprobaba procedencia FALLBACK con
«indefinido» después de información de precio fijo. R2 ahora mantiene esa
respuesta desconocida en selección de plan. El estímulo cambia a «quiero
información de los espacios», que conserva la ruta del clasificador; las
aserciones de procedencia DETERMINISTIC/FALLBACK permanecen intactas. Se vuelve
a ejecutar el archivo completo afectado; los otros 307 casos ya pasaron.

Los dos archivos nuevos son
`tests/booking_conversation/test_plan_selection_after_catalog_g2.py` y
`tests/booking_conversation/test_plan_selection_after_catalog_edges.py`.
Cubren el transcript, las variantes, los ocho planes, homónimos, tipos de lead,
fechas, Cinema y Amor, repetición de desconocidos, interrupciones, pausas,
flag apagado, reentregas y el bloqueo global al confirmar.

## Verificación y reproducción

Los subsets usan una base sintética local `ceiba_plan_test` en PostgreSQL de
Docker. `TEST_DATABASE_URL` debe apuntar a esa base de pruebas con el driver
`postgresql+asyncpg`; no debe apuntar a producción. La dirección privada del
contenedor depende del entorno.

```bash
.venv/bin/pytest tests/booking_conversation/test_plan_selection_after_catalog_g2.py -q
.venv/bin/pytest tests/booking_conversation/test_plan_selection_after_catalog_g2.py tests/booking_conversation/test_plan_selection_after_catalog_edges.py -q
.venv/bin/pytest tests/booking_conversation -q
.venv/bin/pytest tests/test_slice2a_catalogs_adversarial.py tests/test_fix2a_catalog_capture_adversarial.py tests/test_noviazgo_catalog_capture_g2.py tests/test_noviazgo_fallback_boundaries.py tests/conversational/test_romantic_catalog.py tests/unit/test_noviazgo_catalog_resolver_g2.py tests/unit/test_fixed_catalog_dates_g2.py tests/unit/test_fixed_price_booking.py -q
.venv/bin/ruff check .
git diff --check
```

El subset de booking incluye las G2 nuevas y las G2 de #42; el subset de
catálogo incluye las G2 de #41 y los unitarios de fechas de #42.

| Comprobación final | Estado al redactar este informe | Evidencia |
| --- | --- | --- |
| Booking completo, incluidas las 64 G2/G3 nuevas y #42 | **257 passed in 735.37s** | [booking-green.out](booking-green.out) |
| Catálogo y regresiones #41/#42 | **307 casos pasados; archivo afectado completo: 16 passed in 55.00s**, incluido el único fallo alineado | [primer intento](catalog-first-attempt.out), [reejecución verde](catalog-fallback-alignment-green.out) |
| Ruff sobre propuesta en árbol limpio | **All checks passed!** | [ruff-clean-tree.out](ruff-clean-tree.out) |
| Suite completa del PR | Pendiente del push y CI | El run se informará después del push |

Ruff sobre todo el workspace original detectó **210 errores en nueve scripts
untracked preexistentes de A13/A14**. No se modificaron ni se incluyeron en la
propuesta. Ruff pasó sobre los archivos versionados y los dos tests nuevos;
también pasó sobre `/tmp/ceiba-plan-selection-lint`, generado desde `f703533`
más el diff de la propuesta y esos tests. CI ejecutará el control completo en
un checkout limpio. Esta limitación del workspace no se oculta como un verde
de `ruff check .` sobre el árbol original.

No se añaden migraciones; el workflow estándar de CI ejecuta igualmente
`make migrate-cycle`. Los resultados de CI y producción se informan en el cierre
de la tarea, después del único push de la parte B.
