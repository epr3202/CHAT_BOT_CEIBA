# R9 — H03.outbox_previo / U12c: contrato previo al CI

BASE `068815555a266b784bafc8dd521ca618eabbf30a`, árbol
`de7eee5c909506b5679b7ffd62defadfcce1cec4`, run R8 `34496834405`, intento 1.
1336 nodos históricos; 701 focales contenidos en la suite. 26 migraciones,
head `20260908_0026`. Estado de este documento: diseño y reproducción por validar,
no informe GREEN. Los resultados posteriores quedan en informes locales separados.

## Fuentes y discrepancias

AGENTS raíz y BASE iguales. Se contrastaron U12c del plan local de auditoría,
BR-HAND-004/006/007/008/010/012, estados aprobados y respuestas aprobadas.
Los planes de auditoría son archivos locales posteriores a la base auditada y
se conservan: no se añaden ni reescriben. R1 aporta identidad de claim; R2 aplica
inbox bajo Customer → Conversation → InboxJob; R4 crea handoff determinista;
R5 guarda entrada pasiva bajo pausa y usa Handoff NOWAIT; R6/R7 validan propuestas;
R8 autoriza toma/respuesta/retorno por propietario actual, sin override ADMIN.

El texto inicial de architecture describe la auditoría anterior a R2, no el
consumidor vigente. WAITING_FOR_HUMAN puede conservar bot_enabled=true en BASE:
la política R9 y los guards R2 lo consideran pausa. BR-HAND-006 exige false al tomar.
No se detectó conflicto que impida aplicar la política de admisión aprobada R9.

## Inventario runtime y decisiones

| Productor | Propósito / autoridad actual | Persistencia BASE | Contrato R9 |
|---|---|---|---|
| orchestrator.enqueue_template, llamadas normales/degradaciones | Plantilla aprobada, decisión backend | Texto renderizado, conversación, mensaje; no código/origen/control | AUTO/TEMPLATE con período; pausa o CLOSED invalida |
| catalog.enqueue_catalogs_for_event_type, explícito/proactivo | PDF aprobado/asset/caption; backend | DOCUMENT, asset, CatalogSend y auditoría; no período | AUTO/CATALOG, mismo contrato; conservar deduplicación proactiva |
| catalog.enqueue_template_text | Pregunta tipo/fallback aprobado | Solo texto, sin procedencia | AUTO/TEMPLATE salvo acuse explícito de caso creado |
| orchestrator.create_handoff_and_pause | Transferencia, R4 y motivos críticos; overrides de calendario/fallback | PENDING Handoff y auditoría; no enlace Outbox-caso | HANDOFF_NOTICE ligado a ese caso y período de espera; no todos los mensajes del turno |
| preparación de cotización (RESP-QUOTE-004/009) | Solicitud registrada y pasada a equipo | Handoff QUOTE_PREPARATION, sin vínculo a Outbox | HANDOFF_NOTICE del caso creado; conserva negocio confirmado |
| catálogo no disponible (RESP-CATALOG-003) | Solicitud derivada al equipo | Caso CATALOG_NOT_AVAILABLE, bot false, texto encolado antes | Vincular únicamente ese aviso al caso devuelto por el productor |
| catalog.create_template_unavailable_handoff | Falta de plantillas aprobadas | Caso sin aviso | No inventar texto ni permiso |
| inbound no textual desconocido | Crea OTHER y pregunta genérica RESP-FALLBACK-001 | Caso y texto genérico separados | La pregunta no informa transferencia: sigue AUTO, se suprime bajo pausa |
| admin.create_agent_message | Propietario autorizado por R8 | payload.agent booleano true, audit AGENT_MESSAGE_ENQUEUED con outbox_id/conv | HUMAN_REPLY con origen servidor y prueba persistida; sobrevive pausa/retorno/reasignación |
| admin.review_payment_evidence | ADMIN decide ACCEPTED/REJECTED y notifica RESP-PAYMENT-004/005 | Decisión/evidence/agente/auditoría; Outbox sin enlace | PAYMENT_REVIEW_RESULT explícito ligado a decisión registrada; preserva aviso humano bajo pausa |

La última integración NO corrige H02.payment ni afirma reserva nueva: conserva
el productor existente autorizado y su condición de confirmación humana. No hay
bypass SYSTEM ni origen inferido por texto. No se implementan recordatorios.
Los mensajes especiales de emergencia no tienen productor independiente de
Outbox en BASE; el camino común existente usa handoff/plantilla aprobada.

Escritores: estado de Conversation se asigna en transition_conversation; R8 toma
pendiente/directa pasa WAITING → HUMAN_ACTIVE y bot false, retorno habilita bot;
catálogo no disponible/plantilla ausente deshabilitan bot y pasan WAITING;
create_handoff común pasa WAITING sin deshabilitar. Asignación solo R8. CLOSED está
en el servicio de transiciones, sin endpoint nuevo de cierre/pausa. Los resultados
de appointment son propuestas de estado consumidas por orquestador, no escritores
directos. R9 centraliza rotación en validadores del modelo para cubrir todos estos
escritores ORM, después de validar estado; no hay escritor runtime SQL directo.

Consumidor efectivo: worker reclama PENDING/vencido y ejecuta TEXT o DOCUMENT;
documento resuelve/upload/cache y puede enviar dos veces por media inválido.
MediaService separa HTTP de locks de cache. outbound es adaptador, no productor.
El reaper y los settlements son consumidores de identidad, no autorizaciones.

## Diseño previo al diff de producto

Una migración aditiva propuesta `20260910_0027_outbox_admission.py`, revisión
`20260910_0027` (nombre/revisión comprobados libres frente a las 26 de BASE).
Conversation.automation_epoch: UUID durable generado por servidor, sin reloj.
Cambiar a WAITING/HUMAN/CLOSED o deshabilitar bot rota UUID en la misma transacción;
retorno nunca reutiliza el anterior. Rollback revierte columna e invalidación.
Encolado guarda Outbox.delivery_context JSONB nullable: origen/propósito explícitos,
epoch para automatismos/avisos, case_id para aviso, agente para respuesta humana,
evidence_id/decisión para aviso de pago. Ningún cuerpo HTTP/IA rellena ese contexto.

Outbox.send_admission JSONB nullable registra UUID por intento, claim R1, fecha UTC
y fase del intento (admitido/resultado conocido o incierto). delivery_reason y
delivery_decided_at hacen observable SUPPRESSED o REVIEW. Campos nuevos no cambian
estados públicos de conversación. Las filas no se borran; Message/AuditEvent previos
permanecen append-only. SUPPRESSED no es SENT ni FAILED ni consume intentos Meta.
REVIEW conserva incertidumbre, nunca se adquiere automáticamente.

1. Encolar y origen comparten transacción de dominio.
2. Claim breve solo Outbox → commit; no permiso ni locks conservados.
3. Localización preliminar sin locks no autoriza. Admisión/settlement adquieren
   Customer → Conversation → (consulta del Handoff protegido por Conversation) →
   Outbox. Revalidan relación y token bajo locks. Customer se incluye por FK al
   insertar Message de salida. Nunca Outbox → Conversation. Reaper localiza IDs,
   vuelve a bloquear en el mismo orden y revalida caducidad/identidad.
4. Preflight documento comprueba vigencia antes de preparación, sin admitir send.
   Tras media, nueva transacción breve guarda admisión y confirma antes de SEND.
   Texto hace lo mismo junto a SEND. Cada segundo send tiene admisión propia.
   No HTTP/upload/backoff bajo locks; no autorización de lote ni bandera en memoria.
5. Pausa confirmada primero: suprimir durable sin SEND. Admisión confirmada primero:
   llamada todavía posible y su éxito real se registra aunque ya exista pausa.
   Fallo tardío o reaper de intento admitido ahora revocado termina en REVIEW,
   preservando error/incertidumbre y evitando reintento obsoleto. Token antiguo
   nunca altera resultado de adquisición nueva ni terminal SUPPRESSED/REVIEW.
6. Error al verificar DB/propiedad no concede permiso. Resultado distinto de
   supresión legítima. Admitido no prueba aceptación ni entrega del proveedor.

Aviso HANDOFF_NOTICE exige mismo período, conversación WAITING y caso propio
PENDING. Toma, resolución o retorno lo vuelven atrasado. Mensaje humano exige
payload.agent is True y contexto servidor: ninguna cadena truthy concede permiso.
La decisión de pago exige evidencia registrada del mismo cliente/conversación;
no depende del dueño posterior de atención. No se relajan nuevas acciones R8.

## Historia y futura activación (no ejecutada)

La migración no atribuye epoch actual a Outbox histórico. Columnas nuevas quedan
null; SENT/FAILED previos no cambian. PENDING/backoff/SENDING sin contexto se evalúan
en consumidor nuevo: solo respuesta humana probada por auditoría servidor exacta
outbox_id/conversation_id más payload.agent booleano true puede adoptarse. Lo demás
pasa a REVIEW, distinguiendo SENDING anterior potencialmente en vuelo. No replay
de Message/inbox/negocio para reconstruir origen, ni interpretación del texto.

Vía operativa documentada: inspeccionar REVIEW y evidencia del proveedor; registrar
decisión humana por procedimientos aprobados, mantener fila/historia original. Si
hace falta nueva comunicación, usar respuesta humana autorizada R8. No reactivar
masivamente cola ni mutar origen por conjetura; no se añade endpoint de reparación.
Antes de una activación futura: detener/drenar binarios antiguos y tratar vuelos
inciertos; respaldar, migrar y verificar compatibilidad en procedimiento aprobado
separado. No ejecutado aquí; downgrade no es rollback productivo autorizado.

## Verificación prevista

RED con producto BASE byte-idéntico: dos fallos funcionales esperados TEXT/DOCUMENT
encolados por productores reales y toma real autenticada; tres controles activos y
humano. Congelar tests/helpers solo tras inspeccionar fases y precondiciones remotas.
Suite completa y focal Alembic independientes, Python 3.12/Postgres 16 propios del
job, proveedores estrictos simulados y guard R0. Retener 1336 nodos; 701 focales son
subconjunto. Pruebas posteriores cubren origen, pausas/retorno, carreras/admisión,
media, reaper/callbacks, rollback SQL diferido, reinicio/muerte de proceso propio,
historia y R8/R5 bajo contención. No dar RED retroactivo a pruebas nuevas.

Allowlist exacta y cualquier adaptación histórica se publican antes de ejecutarse.
Ruff/colección/aislamiento/integridad/limpieza son gates reales. No pytest ni producto
local, no instalación, sin PR/merge/tag/main/deploy/SSH/activación. La autorización
R9 permite expresamente commit/push RED, excepción reportada al gate local AGENTS.


# Adaptaciones históricas declaradas antes del candidato

Se conservan los 1336 nodeids BASE. Ninguna adaptación es un RED nuevo. No hay
plugin que atribuya autorización a filas arbitrarias ni producto alternativo cargado.

| Archivo / nodo o fixture | Preparación / expectativa BASE | Cambio contractual y fortalecimiento |
|---|---|---|
| tests/remediation/test_r1_outbox.py::seed (consumida por R1 y otros controles) | Construye una salida automática sintética actual con Conversation BOT_ACTIVE | Añadir automatic_context de esa conversación al construirla, en el mismo TX. No cambiar aserciones de R1 ni filas legacy |
| tests/remediation/test_r1_outbox_ownership.py::test_claim_competition_and_independent_outputs | Copia salida válida para probar identidad de fila, texto intencionalmente repetido | Copiar también procedencia actual de la fila fuente; no copiar admisión/token. Mantener dos envíos y dos mensajes |
| tests/integration/test_outbox_worker.py::seed_pending_outbox | Outbox actual sintético para envío, retry, máximo y reaper | Procedencia automática explícita en creación, sin cambiar resultados del transporte |
| tests/test_slice2a_catalogs_adversarial.py::seed_document_outbox | Documento actual sintético para cache/upload/retry | Procedencia AUTO/CATALOG ligada al período actual; no modificar controles de PDF ni cache |
| tests/remediation/test_r1_outbox_migration.py::test_legacy_rows_upgrade_parity_recovery_and_downgrade[None / legacy_claimed_at1] | Ensaya 0024→0025, afirma preservación exacta y luego reenvía PENDING/SENDING sin origen | Mantener ensayo/reflexión/ciclo 0025 con expectativas exactas. Antes del consumidor actual, upgrade explícito 0027 y comprobar columnas nuevas null. Las dos filas ambiguas pasan REVIEW sin send, Message adicional, intentos ni auditoría Meta inventados. SENT/FAILED históricos permanecen exactos. Esta expectativa de reenvío legacy es precisamente conducta corregida R9 |
| tests/remediation/r2/test_r2_migration.py::test_0025_legacy_is_not_mass_replayed_and_new_head_parity | Fixture ORM actual sobre 0025; upgrade head que se compara literalmente a 0026; ciclo borra inbox y conserva historia | Seed SQL de revisión histórica, fijar upgrade de ensayo a 0026 y retener todas sus aserciones de columnas/checks/índices/versión. Upgrade 0027 explícito antes de ejecutar consumidor actual, esperar solamente las cuatro columnas Outbox null. En ciclo histórico, enumerar pérdida de esas columnas por downgrade y su reintroducción null, conservando todos los demás valores y Message/AuditEvent exactos. Nueva prueba R9 comprueba head 0027 independientemente |

No se alteran R8 ownership.py ni sus permisos/pruebas. La autorización R8 rechazada
debe seguir dejando instantánea completa sin cambios, incluido automation_epoch.
Otras tres construcciones directas de Outbox en tests que no invocan entrega se
mantienen sin contexto; no se les concede permiso de forma preventiva.

## Precisión adicional de inventario

states.md §14.4 recomienda FAQ durante WAITING. La instrucción explícita R9 limita
esa política: automatismos ordinarios se invalidan, igual que los guards runtime R2.
No se reescribe esa fuente aprobada ni se presenta la recomendación como garantía vigente.

Overrides reales de agenda revisados por código aprobado: VISIT-CONFIRM-006,
RESCHEDULE-006 y CANCEL-VISIT-005 sí informan transferencia, al igual que
CALENDAR-ERROR-001/002/003/004. VISIT-DATA-002 y RESCHEDULE-002 preguntan al cliente
y NO son acuses; aunque su productor cree un handoff en ese turno, conservan AUTO
y no reciben excepción por mera coincidencia temporal. Lo mismo sucede con
FALLBACK-001 de inbound desconocido. No se crea otra plantilla.

RED d8f72cc8af547954ad091558cec0bec00f0b26a4, run 34504123258 intento 1: suite 1339 PASS + 2 FAIL; focal 704 PASS + 2 FAIL. Solo fallan los envíos TEXT/DOCUMENT tras toma. Ruff PASS, fases completas, sin red inesperada; dos ZIP originales verificados. Tests/helpers RED congelados. Candidato y nueva migración pendientes de CI.

Detalle implementado: también se rota identidad al salir de un estado pausado o reactivar bot_enabled. Así, una salida ordinaria creada durante la espera tampoco revive al volver al bot. La admisión repetida de un claim ya admitido se descarta sin retirar su identidad mientras otro consumidor puede estar en vuelo.


## Ajuste del candidato tras focal C1

C1 6af641f2df85e61bdb276ba79cc20ab5ef4cfafa, run 34515315064: focal 766 PASS y dos fallos de fixture de pago. El seed mantiene RESP-PAYMENT-004/005 en DRAFT y el endpoint devuelve DEFERRED correctamente. Se prepara explícitamente APPROVED solo en la DB sintética para la rama positiva y se conserva control DRAFT/DEFERRED. Esto no modifica plantillas ni datos de producto. Ruff identificó orden de imports en dos fuentes (más la copia generada build/lib); se corrige ese orden.

Se añaden contención de admisión con denegación R8 y captura de comprobante R5, caso ajeno/propósito inválido/código sin caso, defaults SQL y ORM, reloj fijo y evidencia detallada por caso. Las pruebas añadidas después de RED no tienen RED retroactivo. La muerte de proceso usa ahora create_handoff real en el hijo propio, conserva guard R0 heredado y crea engine nuevo.

Inventario complementario: scripts/reset_local_conversation.py también escribe CLOSED, bot_enabled y asignación mediante ORM bajo Customer → Conversation → Handoff → Outbox. El validador central cubre su cambio de período. Su cancelación administrativa explícita de cola tiene contrato de reinicio local separado; no se ejecuta ni modifica en R9, que excluye reparaciones operativas. No se extiende la garantía del worker a binarios antiguos ni a alteraciones administrativas directas de filas.


# Adaptación adicional demostrada por suite C1, antes de editar la fixture

Suite C1 `6af641f2df85e61bdb276ba79cc20ab5ef4cfafa`, run `34515315064`: 1403 nodos,
1400 PASS y tres fallos. Dos son la preparación de aprobación de pago ya declarada.
El tercero es `tests/unit/test_slot_presentation_boundary.py::test_unregistered_variable_uses_controlled_render_failure_path`.

Ese test usa una Conversation simulada con SimpleNamespace, sin la nueva columna
automation_epoch. Falla por AttributeError antes de verificar el fallback, no por
cambio de plantilla ni de las reglas de variables. Se amplía la allowlist con ese
archivo y se completa exclusivamente su fixture con un UUID de período actual.
Se retienen el nodo y todas las aserciones del fallback; no se vuelve permisivo el
producto para aceptar objetos de dominio incompletos. No cambia ninguna fuente
aprobada de respuestas. Esta adaptación queda declarada antes del siguiente CI.


# Corrección de prueba nueva, antes de C3

C2 `148df9db37d7e74b3d89e2b78e8450da8bbee216`, run `34517107330`, intento 1:
suite 1409 PASS / 1 FAIL; focal 774 PASS / 1 FAIL; Ruff PASS en ambos jobs.
El único fallo es la nueva rama r5_capture de contención de entrega.

La instantánea independiente muestra un InboxJob PENDING, attempts=0, sin claim,
y el Outbox humano SENT. process_event persiste la recepción pero claim_inbox_batch
usa lock_context(skip=True): puede ceder el turno mientras la liquidación Outbox
retiene Customer/Conversation. Es comportamiento R2 conservado, no pérdida de evidencia.

Se corrige exclusivamente la prueba nueva para registrar ese resultado intermedio y
ejecutar una vuelta del worker real process_inbox_once después de terminar ambas
tareas. Se mantienen la prueba de bloqueo SQL con pg_blocking_pids, captura exacta
de un comprobante pendiente, Inbox COMPLETED, cero IA, estado HUMAN_ACTIVE y un
único envío humano. No se fuerza un claim, no se modifican filas ni se relajan
aserciones finales. No cambia producto ni los cinco nodos RED congelados.
