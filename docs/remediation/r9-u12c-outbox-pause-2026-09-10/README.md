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
