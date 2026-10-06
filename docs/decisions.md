# Decisiones y propuestas

## Propuestas de auditoría — 2026-09-07

**Estado: PROPUESTAS, no aceptadas ni implementadas.** Base HEAD 8935687. [Plan completo](audits/2026-09-07-8935687/remediation_plan.md).

- Ratificar alcance candidato y calendario de SLA (H18/H26).
- Separar identidad del mensaje y finalización durable, con claims verificables (H01/H02).
- Unificar pausa humana y autorización de acciones sobre casos (H03/H11).
- Definir operación durable y reconciliación de agenda (H07/H08).
- Promover artefacto/SHA probado y contenido versionado explícitamente (H13/H16).
- Acordar retención/minimización efectiva y evidencia de recuperación (H19/H20).

Las decisiones aceptadas anteriores continúan en sus documentos canónicos, especialmente D1 y otras decisiones de [observabilidad IA](product/ai-execution-observability.md). No se acepta una reducción del MVP, una nueva infraestructura ni excepciones a append-only por crear este índice. AGENTS.md permanece sin modificaciones.


## 2026-09-08 ? R1 H02.Outbox

Decision R1 limitada: UUID nullable por adquisicion, sin backfill de propietarios antiguos; liquidacion exige token obligatorio. Expiracion efectiva por reaper. No es segura la convivencia con workers antiguos que liquidan por ID. El procedimiento de activacion propuesto exige detenerlos; no se despliega.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

Decision R2 limitada: control durable por Message, orden local por conversacion, reintentos acotados, finalizacion silenciosa explicita y separacion de operaciones de agenda. No hay backfill de exito ni convivencia segura con API/worker/CLI antiguos. No completa H06/H07 ni modifica las reglas de negocio.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 conserva AIUnavailable y HTTP_ERROR para llamada fallida con subtipo sanitizado, TIMEOUT separado. No captura indiscriminadamente TransportError/Exception; configuracion, cancelacion y programacion conservan propagacion. No se cambian prompts ni rutas comerciales.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 — R4 solicitud explícita de asesor

R4 separa H05.solicitud_explicita de H05.agotamiento_fallback. Coincidencia completa de catálogo estrecho; ambiguos/mezclas mantienen ruta anterior. Procedencia determinista explícita, sin probabilidad calibrada ni cambios de umbrales IA.

[Contrato y validación R4](remediation/r4-h05-explicit-human-2026-09-08/README.md).


## R5 en validacion: H03.entrada_multimedia / U12a

Guard de medios pausados y captura pasiva en inbox R2; candidato pendiente de CI.
Sin cambios al worker de comprobantes ni invalidacion de Outbox previo (U12c).
Contrato y evidencia: [R5](remediation/r5-h03-media-2026-09-09/README.md).

## R6 en validación — H17.contrato_y_consumo_de_pendientes / U03

BASE R5 aprobada d237ad7/run 34364403706. R6 distingue propuestas de clasificación y
nombre de resoluciones inertes, valida contexto legacy y retira autoridad al negar o
reemplazar. Consumo y descarte permanecen bajo R2; sin migración ni activación.
[Contrato, RED y límites R6](remediation/r6-h17-confirmations-2026-09-09/README.md).

## R7 en validacion — H29 / U04

BASE R6 aprobada cfdc09b/run 34381466698. Contrato semantico de nueve entidades antes
de aplicarlas, sin migraciones ni activacion. RED sobre producto BASE intacto.
[Contrato y evidencia R7](remediation/r7-h29-entities-2026-09-09/README.md).

R7 candidato: frontera pura para las nueve entidades, revalidación en consumidores,
correcciones rechazadas con aclaración y conservación del valor previo. RED3:
962957346a93ce0fc177bee377af7ac9332983d8 / run 34397740618.
Seis expectativas R6 de propuesta de nombre se adaptan conforme al contrato documentado;
se conservan sus nodos. Validación remota pendiente. Cero migraciones; H29 agregado abierto.

## R8 — H11.propiedad_mutaciones_humanas / U12b (2026-09-10)

Contrato previo y reproduccion de propiedad en respuesta/retorno. BASE R7 `9af02027672049c1d73f998e9be1fe8c070e791f`; producto BASE intacto durante RED. ADMIN sin override automatico; reasignacion explicita pendiente. [Contrato R8](remediation/r8-h11-ownership-2026-09-10/README.md). H11 agregado permanece abierto; no activacion.

R8 candidato: propiedad por ID dentro de la transaccion y locks Conversation -> Handoff;
sin override ADMIN. Toma pendiente conserva WAITING_FOR_HUMAN; respuesta/retorno exigen
HUMAN_ACTIVE con bot pausado. Una fixture historica usa ahora la sesion de su propietario.
Resultado definitivo, SHA y evidencias quedan en el informe local post-CI; H11 agregado
y U12c siguen abiertos. Sin migraciones ni activacion.


## R9 — H03.outbox_previo / U12c (2026-09-10)

Contrato previo y RED sobre BASE R8 `068815555a266b784bafc8dd521ca618eabbf30a`: origen, invalidación durable y admisión local del Outbox ante pausa. [Diseño R9](remediation/r9-u12c-outbox-pause-2026-09-10/README.md). Validación remota pendiente; H03/H11 agregados permanecen abiertos. Sin activación.

R9 candidato implementa procedencia de servidor, período durable y admisión por intento; migración aditiva 20260910_0027. La validación remota y el informe final post-CI siguen separados; sin activación ni cierre de H03/H11 agregados.

## 2026-10-02 — staff_outbox separado del outbox de clientes

Los avisos a asesores tienen su propia cola mutable `staff_outbox` y su historia
append-only en `audit_event`. La admisión por conversación, el epoch y las pausas
R9 protegen mensajes destinados al cliente; no aplican a avisos internos que
deben llegar precisamente cuando una conversación se entrega a un asesor.

Se descarta reutilizar `outbox`: exigir una conversación ficticia de cada asesor
mezclaría destinatarios, políticas de pausa y permisos. La cola separada conserva
el patrón probado de claims, stale recovery, backoff y envío posterior al commit,
con idempotencia por destinatario/evento/fuente y fallback de ventana a plantilla.
La administración queda restringida a ADMIN. No se añade infraestructura externa.

## 2026-10-02 — D5: múltiples comprobantes, saldo y excepción de acuse durante pausa

El incidente de la conversación 196 mostró que un primer abono de $100.000 para
una reserva de $400.000 dejaba el handoff abierto, una segunda imagen se capturaba
sin acuse y una tercera podía quedar sin reserva porque la búsqueda solo admitía
PAYMENT_PENDING de la conversación original. D5 vincula por cliente una reserva
futura, priorizando PAYMENT_REVIEW, PAYMENT_PENDING y RESERVED con saldo. Las
asociaciones en PAYMENT_REVIEW y RESERVED no transicionan la reserva; aceptar el
saldo es decisión humana y conserva la franja y Calendar.

La regla R9 original reservaba HANDOFF_NOTICE al caso recién creado y
PAYMENT_REVIEW_RESULT a una decisión humana persistida. Se autoriza explícitamente
una excepción independiente PAYMENT_EVIDENCE_ACK/EVIDENCE_RECEIPT solo para una
imagen vinculada en la misma transacción bajo el único handoff PAYMENT_REVIEW
PENDING de la conversación en WAITING_FOR_HUMAN. No admite textos, otros medios,
otro handoff abierto, TAKEN/HUMAN_ACTIVE, CLOSED ni bot deshabilitado. Cada mensaje
externo genera como máximo un acuse, cuya admisión revalida asociación y handoff.
La toma humana posterior suprime el acuse encolado con motivo explícito. Se
conservan el HANDOFF_NOTICE del primer comprobante y la captura pasiva documental.

Se descarta el silencio hasta la intervención de un asesor porque deja al cliente
sin confirmación de recepción de sus abonos, como ocurrió en el incidente 196.
También se descarta reutilizar HANDOFF_NOTICE del caso previo o inventar una
decisión humana: debilitaría la autoridad R9. La excepción se documenta junto al
código y no otorga al bot autoridad para aceptar pagos, reservar ni cancelar.

La liquidación del último comprobante pendiente resuelve el handoff de pago y
devuelve el control a BOT_ACTIVE solo si no hay otros casos abiertos. Un conflicto
de disponibilidad conserva la pausa mediante RESERVATION_CONFIRMATION. Esta
resolución ocurre tras el commit de liquidación, en una transacción corta con
locks Customer → Conversation → Handoff; también ocurre si la notificación no
puede renderizarse. Una reserva manual sin conversation_id también notifica si la
evidencia pertenece a una conversación válida del mismo cliente. Se descarta
conservar DEFERRED por ese NULL porque contradiría las notificaciones exigidas
para todos los comprobantes vinculados y excluiría los pagos de saldo posteriores.

## 2026-10-02 — D6: lease mutable y pre-revisión en dos transacciones

TX1 bloquea con FOR UPDATE SKIP LOCKED y registra claim_token/claimed_at en
payment_evidence; confirma antes de leer el archivo y llamar a OpenRouter.
El archivo conserva las validaciones de ruta, tamaño, descarga y MIME. TX2
adquiere un bloqueo fresco, comprueba PENDING_REVIEW y el mismo token e inserta
payment_evidence_review, ai_execution y audit_event atómicamente. Si un humano
ya decidió o el lease cambió, solo registra PAYMENT_PREREVIEW_DISCARDED.
Los tres historiales siguen append-only; solo el lease de la evidencia es mutable.

Worker y re-revisión administrativa usan el mismo flujo. Un lease vigente devuelve
409 con «La pre-revisión está en curso»; un lease vencido según
OUTBOX_SENDING_TIMEOUT_SECONDS puede reclamarse. Descarga FAILED_PERMANENT y MIME
no imagen producen SKIPPED sin proveedor. Se descarta mantener el bloqueo abierto
durante HTTP porque impedía aceptar comprobantes mientras respondía la IA.

## 2026-10-02 — B4: cola de recordatorios programados y saldo vencido

Se crea customer_notification separada porque el outbox conversacional de
clientes exige message_id de un mensaje entrante y pasa por admisión de la
conversación. Un recordatorio programado no tiene mensaje origen y debe salir
aunque esa conversación esté cerrada. Siempre usa plantilla Meta aprobada,
idioma es y parámetros saneados, sin ventana de 24 horas ni texto libre.
Se descarta fabricar un mensaje entrante o una conversación para el recordatorio.

La refactorización mínima extrae claim/recovery/settlement en
app/notifications/queue.py y la actualización de statuses en un helper compartido.
Staff mantiene sus APIs y su selección TEXT/TEMPLATE/DEFERRED; sus pruebas
existentes se ejecutan sin cambios. Solo la consulta, el snapshot y la admisión
de cada tabla son específicos. Todos los proveedores se llaman tras el commit.
El programador respeta el orden de bloqueos Customer → Reservation de inbound;
se descarta bloquear primero reservas porque el FK de la cola produciría el
orden inverso al recibir otro comprobante del cliente.

El vencimiento marca y avisa sin cancelar. Una reprogramación humana a un nuevo
plazo futuro limpia la marca anterior, con valores viejos y nuevos en el audit;
de lo contrario el panel mostraría saldo vencido antes del nuevo plazo.
Los tipos de recordatorio conservan UNIQUE(reservation_id, kind): reprogramar
no crea una segunda entrega del mismo tipo para esa reserva.

## 2026-10-02 — B4: callbacks mixtos y deduplicación sin espera

Un webhook puede actualizar el status de un aviso y continuar con un mensaje
del cliente en la misma transacción. El status conserva el bloqueo de la fila
hasta el commit exterior. El programador, que ya tiene Customer, no vuelve a
insertar un tipo customer_notification ni una fuente BALANCE_OVERDUE existente:
una lectura MVCC detecta esa existencia sin esperar la fila del callback.
UNIQUE sigue siendo la defensa final de idempotencia. Se descarta repetir
INSERT ON CONFLICT sobre la fila existente porque invertiría los bloqueos
Outbox → Customer del webhook frente a Customer → Outbox del programador.
Los contratos reproducen ambas colas y verifican que callback y mensaje terminan.

## 2026-10-02 — D5: cierre de casos de pago entre conversaciones

El último comprobante revisado finaliza los casos PAYMENT_REVIEW de todas las
conversaciones del mismo cliente que tienen evidencias de la reserva, conservando
Customer → Conversation (orden de ID) → Handoff. No se limita el cierre a la
conversación del último comprobante: eso dejaba pendiente el caso del primer abono
cuando el cliente enviaba el siguiente desde una conversación nueva.

PaymentEvidence no tiene handoff_id; la asociación probada utiliza sus FKs de
reserva, cliente y conversación. Se descarta añadir un campo y migración para
resolver este ciclo. No se cierran otros motivos, clientes o casos que conservan
algún comprobante PENDING_REVIEW de otra reserva o sin reserva. La conversación
vuelve al bot solo si estaba pausada y no quedan otros handoffs abiertos; las
conversaciones CLOSED no se reabren. Cada caso resuelto genera su propio audit
con la reserva y la decisión humana final.


## 2026-10-05 — Noviazgo, catálogo determinista y recuperación de preguntas

El incidente de la conversación 203 (main `3e01706`) mostró que «pedidas de
noviazgo» no resolvía PROPOSAL y un JSON truncado desviaba la pregunta pendiente.
Emerson decide mapear noviazgo y sus variantes a PROPOSAL. Una sola tabla de alias
alimenta un matcher de frases con límites de palabra, descarte de coincidencias
contenidas y ambigüedad entre tipos. Se conserva igualdad completa como caso
particular y el normalizador de entidades estructuradas sigue exigiendo un valor
canónico completo.

Durante la captura de catálogo manda la resolución determinista; si falla, el
extractor de tipo se evalúa tras una clasificación válida y antes del abandono.
`RESP-CATALOG-002` es una pregunta de tipo de evento. Sin captura, catálogo más un
tipo único se resuelve antes del LLM. El atajo sin la palabra catálogo exige una
frase única PROPOSAL con etiqueta reconocida de dos o más palabras, por
GENERAL_INFORMATION de precio fijo, para que T2/T3 del transcript no consuman
el JSON truncado.

Emerson aclara que la ruta de precio fijo mantiene prioridad PROPOSAL sobre
ROMANTIC_DINNER en frases mixtas existentes. Se comparte el matcher y la tabla de
alias; el resolvedor de catálogo conserva `None` ante varios tipos. Se reutiliza
`CATALOG_EVENT_TYPE_RESOLVED` con actor SYSTEM, event_type, matched_label y
`decision_source=DETERMINISTIC`, más una fuente que distingue captura, solicitud
explícita e información de precio fijo. No se agregan estados ni plantillas.

La revisión C1 de Claude del PR #41 limita `noviazgo`, `propuesta`, `otro`,
`otro tipo de evento`, `grado` y `taller` a respuestas de la captura
`COLLECT_CATALOG_EVENT_TYPE`. El matcher recibe esa condición explícitamente;
fuera de captura ignora esos labels para evitar resolver menciones incidentales.
La normalización de entidades estructuradas conserva su contrato. La prioridad
de precio fijo se limita a PROPOSAL sobre ROMANTIC_DINNER; cualquier otro tipo
coexistente deja esa ruta sin resolver.

La revisión C2 de Claude del PR #41 limita el atajo PROPOSAL autorizado
inicialmente a esas frases explícitas de al menos dos palabras (`pedida de
noviazgo`, `pedir noviazgo`, `anillo de compromiso`). Fuera de captura no basta
una etiqueta de una palabra para evitar el clasificador sin pedir catálogo.
`mandame otro catalogo` también pasa al clasificador: `otro` solo es una respuesta
válida a la pregunta de tipo de evento, sin provocar un handoff determinista.

Ante indisponibilidad IA, fuera de las ramas críticas y ubicación, se repite la
última pregunta solo si hay pending_action vigente y su última versión está
APPROVED y tiene allowed_variables vacío. El fallo técnico no agota la captura.

## 2026-10-06 — Catálogo explícito de precio fijo conserva contexto de reserva

La conversación 205, sobre main `621eeead`, recibió el catálogo de pedidas de
mano por la rama explícita sin crear lead/evento PROPOSAL. El siguiente
«Me gustaría agendar para el 14» llegó a visitas por falta del tipo persistido.

Emerson decide que una solicitud explícita con tipo de precio fijo resuelto use
la misma rama de información de precio fijo: crear/reutilizar lead/evento,
aplicar event_type desde el backend, texto aprobado más DOCUMENT PROACTIVE y
FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO. PROPOSAL y ROMANTIC_DINNER comparten
ese contrato y restauran el mismo pending/estado; el PDF se deduplica por lead y
asset, incluso al repetir el catálogo. La resolución puede venir de una mención,
entidad aceptada del clasificador o tipo ya persistido del lead activo. Una
entidad pendiente de confirmación no se transforma en un tipo firme.

Los tipos no fijos y COLLECT_CATALOG_EVENT_TYPE conservan la ruta de catálogo
explícita. No se crean estados, pending_action, plantillas ni migraciones.
