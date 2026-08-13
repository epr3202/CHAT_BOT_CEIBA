# Estados conversacionales y máquina de estados

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/conversation/states.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Zona horaria oficial:** `America/Bogota`
**Canal inicial:** WhatsApp

**Documentos relacionados:**

* `/docs/product/vision.md`
* `/docs/product/scope.md`
* `/docs/product/business-rules.md`
* `/docs/product/use-cases.md`
* `/docs/product/data-matrix.md`
* `/docs/conversation/intents.md`
* `/docs/conversation/entities.md`

---

# 1. Propósito

Este documento define la máquina de estados del Asistente Conversacional de La Ceiba Club House.

La máquina de estados deberá controlar:

* el momento actual de la conversación;
* la acción pendiente;
* los datos que faltan;
* las acciones permitidas;
* las acciones prohibidas;
* las transiciones válidas;
* la intervención humana;
* la recuperación ante errores;
* la continuidad entre mensajes;
* el cierre y reapertura;
* la relación entre conversación, lead, cita, pago y reserva.

La máquina de estados impedirá que el modelo de inteligencia artificial decida libremente qué operaciones ejecutar.

La IA podrá sugerir:

* intención;
* entidades;
* siguiente acción;
* nivel de confianza.

El orquestador y el backend determinarán si la transición es válida.

---

# 2. Principios de la máquina de estados

## ST-GEN-001 — Estado persistido

El estado de una conversación deberá almacenarse de forma persistente.

No dependerá únicamente de:

* memoria temporal;
* último mensaje;
* prompt;
* resumen de IA;
* sesión en caché.

---

## ST-GEN-002 — Transiciones explícitas

Cada cambio de estado deberá ocurrir mediante una transición definida.

Ejemplo:

```text
BOT_ACTIVE
→ COLLECTING_EVENT_DATA
```

No se permitirán cambios arbitrarios como:

```text
BOT_ACTIVE
→ APPOINTMENT_CONFIRMED
```

sin atravesar las validaciones correspondientes.

---

## ST-GEN-003 — Eventos de transición

Las transiciones deberán ser provocadas por eventos identificables.

Ejemplos:

```text
MESSAGE_RECEIVED
INTENT_CLASSIFIED
QUOTE_MINIMUM_DATA_COMPLETED
APPOINTMENT_CONFIRMED_BY_CUSTOMER
AGENT_TAKEOVER
PAYMENT_REPORTED
```

---

## ST-GEN-004 — Guardas

Una transición podrá tener condiciones obligatorias, denominadas guardas.

Ejemplo:

```text
APPOINTMENT_PENDING_CONFIRMATION
→ APPOINTMENT_CONFIRMED
```

Solo si:

```text
customer_confirmation = true
availability_revalidated = true
calendar_event_created = true
```

---

## ST-GEN-005 — Acciones de entrada y salida

Cada estado podrá definir:

* acciones al entrar;
* acciones durante el estado;
* acciones al salir.

---

## ST-GEN-006 — Estado conversacional separado del estado comercial

La conversación, el lead, la cita, el pago y la reserva tendrán máquinas de estados separadas.

Ejemplo:

```text
conversation_status = BOT_ACTIVE
lead_status = QUOTE_REQUESTED
appointment_status = CONFIRMED
```

Estos estados pueden coexistir.

---

## ST-GEN-007 — Una conversación, un estado principal

Cada conversación tendrá un solo estado conversacional principal activo.

Podrá conservar además:

* intención actual;
* acción pendiente;
* subflujo;
* campos pendientes;
* prioridad;
* asesor asignado.

---

## ST-GEN-008 — Auditoría

Toda transición crítica deberá registrar:

* estado anterior;
* estado nuevo;
* evento;
* actor;
* fecha y hora;
* razón;
* datos relacionados;
* identificador de solicitud.

---

# 3. Estado estructurado de la conversación

La conversación deberá incluir como mínimo:

```json
{
  "conversation_status": "COLLECTING_EVENT_DATA",
  "current_intent": "QUOTE_REQUEST",
  "previous_intent": "GENERAL_INFORMATION",
  "pending_action": "COLLECT_EVENT_DATE",
  "pending_fields": [
    "event_date"
  ],
  "last_question_code": "ASK_EVENT_DATE",
  "bot_enabled": true,
  "assigned_agent_id": null,
  "priority": "NORMAL",
  "failed_understanding_count": 0,
  "last_message_at": "2026-08-05T11:45:00-05:00"
}
```

---

# 4. Catálogo oficial de estados conversacionales

```text
NEW
BOT_ACTIVE
ANSWERING_INFORMATION
COLLECTING_EVENT_DATA
QUOTE_REQUEST_READY
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED
WAITING_FOR_HUMAN
HUMAN_ACTIVE
RETURNED_TO_BOT
RESOLVED
CLOSED
```

---

# 5. NEW

## 5.1 Definición

Estado inicial de una conversación recién creada y todavía no procesada por el orquestador.

## 5.2 Entrada

Se entra a `NEW` cuando:

* llega el primer mensaje de un cliente;
* no existe conversación activa;
* se crea una nueva conversación para un nuevo contexto.

## 5.3 Acciones de entrada

* crear `Conversation`;
* relacionar `Customer`;
* guardar mensaje;
* registrar canal;
* establecer `bot_enabled = true`;
* establecer prioridad `NORMAL`.

## 5.4 Acciones permitidas

```text
CLASSIFY_INTENT
EXTRACT_ENTITIES
LOAD_CUSTOMER_CONTEXT
LOAD_ACTIVE_LEADS
```

## 5.5 Acciones prohibidas

```text
CREATE_APPOINTMENT
CONFIRM_PAYMENT
CONFIRM_RESERVATION
CLOSE_CONVERSATION
```

## 5.6 Transiciones permitidas

```text
NEW → BOT_ACTIVE
NEW → WAITING_FOR_HUMAN
NEW → CLOSED
```

## 5.7 Guardas

### `NEW → BOT_ACTIVE`

* webhook válido;
* mensaje almacenado;
* cliente identificado;
* bot habilitado.

### `NEW → WAITING_FOR_HUMAN`

Cuando el primer mensaje contiene:

* emergencia;
* queja;
* solicitud explícita de asesor;
* pago;
* cancelación de evento.

### `NEW → CLOSED`

Solo por:

* evento técnico inválido;
* conversación creada por error;
* acción administrativa autorizada.

---

# 6. BOT_ACTIVE

## 6.1 Definición

Estado general en el que el bot puede interpretar mensajes y dirigir la conversación.

## 6.2 Uso

Este estado se utiliza cuando:

* no existe un subflujo operativo activo;
* el bot espera una nueva intención;
* se retomó una conversación;
* se completó una respuesta y queda abierto el diálogo.

## 6.3 Acciones permitidas

```text
CLASSIFY_INTENT
EXTRACT_ENTITIES
ANSWER_GREETING
START_INFORMATION_FLOW
START_QUOTE_FLOW
START_APPOINTMENT_FLOW
CREATE_HANDOFF
MARK_RESOLVED
```

## 6.4 Acciones prohibidas

```text
CONFIRM_PAYMENT
CONFIRM_RESERVATION
APPLY_DISCOUNT
APPROVE_REFUND
```

## 6.5 Transiciones permitidas

```text
BOT_ACTIVE → ANSWERING_INFORMATION
BOT_ACTIVE → COLLECTING_EVENT_DATA
BOT_ACTIVE → WAITING_FOR_APPOINTMENT_DATE
BOT_ACTIVE → WAITING_FOR_APPOINTMENT_SELECTION
BOT_ACTIVE → APPOINTMENT_PENDING_CONFIRMATION
BOT_ACTIVE → WAITING_FOR_HUMAN
BOT_ACTIVE → RESOLVED
BOT_ACTIVE → CLOSED
```

## 6.6 Eventos

```text
GENERAL_INFORMATION_DETECTED
QUOTE_REQUEST_DETECTED
EVENT_INFORMATION_DETECTED
SCHEDULE_VISIT_DETECTED
HUMAN_REQUEST_DETECTED
COMPLAINT_DETECTED
PAYMENT_DETECTED
FAREWELL_DETECTED
```

---

# 7. ANSWERING_INFORMATION

## 7.1 Definición

Estado temporal en el que el sistema responde una pregunta frecuente o consulta informativa.

## 7.2 Ejemplos

* ubicación;
* capacidad;
* parqueadero;
* piscina;
* mascotas;
* horarios;
* proveedores;
* servicios;
* alojamiento;
* formas de pago.

## 7.3 Acciones de entrada

* identificar categoría;
* recuperar respuesta aprobada;
* verificar vigencia;
* conservar acción pendiente anterior.

## 7.4 Acciones permitidas

```text
GET_APPROVED_KNOWLEDGE
SEND_APPROVED_RESPONSE
REGISTER_OPTIONAL_ENTITY
RESUME_PREVIOUS_FLOW
```

## 7.5 Acciones prohibidas

```text
INVENT_INFORMATION
CONFIRM_PROVIDER
CONFIRM_CUSTOM_PRICE
CONFIRM_RESERVATION
```

## 7.6 Transiciones permitidas

```text
ANSWERING_INFORMATION → BOT_ACTIVE
ANSWERING_INFORMATION → COLLECTING_EVENT_DATA
ANSWERING_INFORMATION → WAITING_FOR_APPOINTMENT_DATE
ANSWERING_INFORMATION → WAITING_FOR_HUMAN
ANSWERING_INFORMATION → RESOLVED
```

## 7.7 Transición de retorno

Si existía una acción pendiente:

```text
pending_action != null
```

el sistema deberá regresar al estado correspondiente.

Ejemplo:

```text
COLLECTING_EVENT_DATA
→ ANSWERING_INFORMATION
→ COLLECTING_EVENT_DATA
```

## 7.8 Error de conocimiento

Si no existe respuesta aprobada:

```text
ANSWERING_INFORMATION → WAITING_FOR_HUMAN
```

cuando la información sea comercialmente relevante.

---

# 8. COLLECTING_EVENT_DATA

## 8.1 Definición

Estado en el que el bot recopila información para crear o completar un lead, evento o solicitud de cotización.

## 8.2 Datos principales

```text
full_name
event_type
event_date
event_month
guest_count
guest_count_range
estimated_budget
preferred_space
requested_services
special_requests
```

## 8.3 Acciones de entrada

* cargar cliente;
* cargar lead;
* cargar evento;
* identificar campos faltantes;
* seleccionar la siguiente pregunta.

## 8.4 Acciones permitidas

```text
ASK_MISSING_FIELD
EXTRACT_EVENT_ENTITIES
UPDATE_LEAD
UPDATE_EVENT
REGISTER_SERVICE_REQUEST
REGISTER_CORRECTION
ANSWER_TEMPORARY_INFORMATION
CREATE_QUOTE_REQUEST_DRAFT
```

## 8.5 Acciones prohibidas

```text
GENERATE_CUSTOM_PRICE
CONFIRM_QUOTE
APPLY_DISCOUNT
CONFIRM_SERVICE_AVAILABILITY
```

## 8.6 Campos mínimos para finalizar

```text
full_name
phone_number
event_type
date_resolved (fecha, mes, o tipo FLEXIBLE/UNKNOWN declarado)
guest_count OR guest_count_range
```

El silencio del cliente sobre la fecha no cuenta como `UNKNOWN`; si no se pronunció, la fecha sigue pendiente.

## 8.7 Transiciones permitidas

```text
COLLECTING_EVENT_DATA → COLLECTING_EVENT_DATA
COLLECTING_EVENT_DATA → ANSWERING_INFORMATION
COLLECTING_EVENT_DATA → QUOTE_REQUEST_READY
COLLECTING_EVENT_DATA → WAITING_FOR_APPOINTMENT_DATE
COLLECTING_EVENT_DATA → WAITING_FOR_HUMAN
COLLECTING_EVENT_DATA → RESOLVED
```

## 8.8 Auto-transición

El estado puede mantenerse después de cada dato recibido:

```text
COLLECTING_EVENT_DATA
→ COLLECTING_EVENT_DATA
```

hasta completar los mínimos.

## 8.9 Condición de salida hacia `QUOTE_REQUEST_READY`

```text
minimum_quote_data_complete = true
summary_generated = true
customer_confirmation_pending = true
```

## 8.10 Eventos especiales

### Presupuesto no informado

El flujo continúa.

### Más de 60 invitados

```text
capacity_review_required = true
```

Puede pasar a:

```text
WAITING_FOR_HUMAN
```

### Corrección de datos

El estado se mantiene, pero se crea auditoría.

---

# 9. QUOTE_REQUEST_READY

## 9.1 Definición

Estado en el que los datos mínimos de cotización están completos y el sistema espera confirmación final o ya creó la solicitud.

## 9.2 Subestados lógicos recomendados

```text
SUMMARY_PENDING
CUSTOMER_CONFIRMATION_PENDING
REQUEST_CREATED
```

Pueden representarse mediante `pending_action`.

## 9.3 Acciones de entrada

* validar datos mínimos;
* generar resumen;
* mostrar resumen al cliente;
* solicitar confirmación.

## 9.4 Acciones permitidas

```text
SEND_QUOTE_SUMMARY
REQUEST_CONFIRMATION
REGISTER_CORRECTION
CREATE_QUOTE_REQUEST
CREATE_HANDOFF
```

## 9.5 Acciones prohibidas

```text
CALCULATE_QUOTE
SEND_PRICE
APPROVE_QUOTE
```

## 9.6 Transiciones permitidas

```text
QUOTE_REQUEST_READY → COLLECTING_EVENT_DATA
QUOTE_REQUEST_READY → WAITING_FOR_HUMAN
QUOTE_REQUEST_READY → BOT_ACTIVE
QUOTE_REQUEST_READY → RESOLVED
```

## 9.7 Guarda para crear solicitud

```text
customer_confirmation = true
minimum_data_complete = true
quote_request_not_already_created = true
```

## 9.8 Resultado después de crear solicitud

* `QuoteRequest.status = READY`;
* `Lead.status = QUOTE_REQUESTED`;
* se crea handoff por `QUOTE_PREPARATION`;
* conversación pasa a `WAITING_FOR_HUMAN` o `BOT_ACTIVE`, según estrategia operativa.

## 9.9 Estrategia recomendada

Después de crear la solicitud:

```text
QUOTE_REQUEST_READY → WAITING_FOR_HUMAN
```

si el asesor continuará por el mismo chat.

Puede mantenerse el bot disponible para FAQ mientras la solicitud está pendiente, siempre que no responda sobre el precio.

---

# 10. WAITING_FOR_APPOINTMENT_DATE

## 10.1 Definición

Estado en el que el sistema espera que el cliente indique una fecha para visitar La Ceiba.

## 10.2 Acciones de entrada

* informar reglas de visita;
* solicitar fecha;
* establecer `pending_action = SELECT_VISIT_DATE`.

## 10.3 Acciones permitidas

```text
EXTRACT_VISIT_DATE
RESOLVE_RELATIVE_DATE
REQUEST_DATE_CONFIRMATION
VALIDATE_VISIT_DATE
ANSWER_VISIT_POLICY
```

## 10.4 Validaciones

* martes a sábado;
* no festivo;
* mínimo tres días;
* fecha futura;
* no bloqueada.

## 10.5 Transiciones permitidas

```text
WAITING_FOR_APPOINTMENT_DATE → WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_DATE → WAITING_FOR_APPOINTMENT_SELECTION
WAITING_FOR_APPOINTMENT_DATE → ANSWERING_INFORMATION
WAITING_FOR_APPOINTMENT_DATE → WAITING_FOR_HUMAN
WAITING_FOR_APPOINTMENT_DATE → BOT_ACTIVE
```

## 10.6 Fecha inválida

El estado se mantiene y el bot solicita otra fecha.

## 10.7 Fecha relativa

El estado se mantiene hasta que el cliente confirme la fecha absoluta.

---

# 11. WAITING_FOR_APPOINTMENT_SELECTION

## 11.1 Definición

Estado en el que el sistema ya validó una fecha y espera que el cliente seleccione un horario disponible.

## 11.2 Acciones de entrada

* consultar calendario;
* aplicar reglas;
* obtener horarios;
* presentar opciones;
* establecer `pending_action = SELECT_VISIT_TIME`.

## 11.3 Horarios permitidos

```text
08:00
09:00
10:00
11:00
```

## 11.4 Acciones permitidas

```text
CHECK_AVAILABILITY
OFFER_TIME_OPTIONS
INTERPRET_OPTION_SELECTION
REGISTER_SELECTED_TIME
ASK_ATTENDEE_COUNT
ASK_VISIT_REASON
```

## 11.5 Acciones prohibidas

```text
CONFIRM_APPOINTMENT_WITHOUT_CUSTOMER
CREATE_APPOINTMENT_WITHOUT_REVALIDATION
```

## 11.6 Transiciones permitidas

```text
WAITING_FOR_APPOINTMENT_SELECTION → WAITING_FOR_APPOINTMENT_SELECTION
WAITING_FOR_APPOINTMENT_SELECTION → APPOINTMENT_PENDING_CONFIRMATION
WAITING_FOR_APPOINTMENT_SELECTION → WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION → ANSWERING_INFORMATION
WAITING_FOR_APPOINTMENT_SELECTION → WAITING_FOR_HUMAN
```

## 11.7 Sin horarios disponibles

El sistema deberá:

* ofrecer otra fecha;
* regresar a `WAITING_FOR_APPOINTMENT_DATE`.

---

# 12. APPOINTMENT_PENDING_CONFIRMATION

## 12.1 Definición

Estado en el que todos los datos de la visita están disponibles y el sistema espera la confirmación expresa del cliente.

## 12.2 Datos obligatorios

```text
full_name
phone_number
preferred_visit_date
preferred_visit_time
visit_attendee_count
visit_reason
```

## 12.3 Acciones de entrada

* generar resumen;
* mostrar fecha;
* mostrar hora;
* mostrar asistentes;
* mostrar motivo;
* solicitar confirmación.

## 12.4 Acciones permitidas

```text
REQUEST_APPOINTMENT_CONFIRMATION
REGISTER_APPOINTMENT_CORRECTION
REVALIDATE_AVAILABILITY
CREATE_APPOINTMENT
```

## 12.5 Acciones prohibidas

```text
CREATE_APPOINTMENT_WITHOUT_CONFIRMATION
ASSUME_CONFIRMATION_FROM_SILENCE
```

## 12.6 Transiciones permitidas

```text
APPOINTMENT_PENDING_CONFIRMATION → APPOINTMENT_CONFIRMED
APPOINTMENT_PENDING_CONFIRMATION → WAITING_FOR_APPOINTMENT_DATE
APPOINTMENT_PENDING_CONFIRMATION → WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION → BOT_ACTIVE
APPOINTMENT_PENDING_CONFIRMATION → WAITING_FOR_HUMAN
```

## 12.7 Guarda de confirmación

```text
customer_confirmation = true
date_valid = true
time_valid = true
attendee_count <= 3
availability_revalidated = true
calendar_event_created = true
```

## 12.8 Conflicto de última hora

Si el horario ya no está disponible:

```text
APPOINTMENT_PENDING_CONFIRMATION
→ WAITING_FOR_APPOINTMENT_SELECTION
```

---

# 13. APPOINTMENT_CONFIRMED

## 13.1 Definición

Estado conversacional alcanzado inmediatamente después de crear una visita correctamente.

## 13.2 Condiciones obligatorias

```text
appointment_status = CONFIRMED
external_calendar_id != null
reminder_scheduled = true
```

## 13.3 Acciones de entrada

* enviar confirmación;
* compartir dirección;
* compartir mapa;
* informar duración;
* informar puntualidad;
* registrar auditoría.

## 13.4 Acciones permitidas

```text
SEND_APPOINTMENT_CONFIRMATION
ANSWER_APPOINTMENT_INFORMATION
START_RESCHEDULE_FLOW
START_CANCEL_VISIT_FLOW
MARK_RESOLVED
```

## 13.5 Transiciones permitidas

```text
APPOINTMENT_CONFIRMED → BOT_ACTIVE
APPOINTMENT_CONFIRMED → WAITING_FOR_APPOINTMENT_DATE
APPOINTMENT_CONFIRMED → WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_CONFIRMED → APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED → WAITING_FOR_HUMAN
APPOINTMENT_CONFIRMED → RESOLVED
```

## 13.6 Duración del estado

Este estado puede ser transitorio.

Después de enviar la confirmación:

```text
APPOINTMENT_CONFIRMED → BOT_ACTIVE
```

o:

```text
APPOINTMENT_CONFIRMED → RESOLVED
```

---

# 14. WAITING_FOR_HUMAN

## 14.1 Definición

Estado en el que existe una solicitud de intervención humana, pero ningún asesor ha tomado todavía la conversación.

## 14.2 Motivos

```text
CUSTOMER_REQUEST
QUOTE_PREPARATION
PRICE_NEGOTIATION
DISCOUNT_REQUEST
PAYMENT_REVIEW
RESERVATION_CONFIRMATION
CANCELLATION
COMPLAINT
LOW_CONFIDENCE
UNSUPPORTED_REQUEST
CAPACITY_REVIEW
SPECIAL_EVENT
SUPPLIER_CONFIRMATION
URGENT_EVENT
SYSTEM_ERROR
REPEATED_NO_SHOW
MANUAL_TAKEOVER
OTHER
```

## 14.3 Acciones de entrada

* crear `Handoff`;
* generar resumen;
* asignar prioridad;
* enviar a bandeja;
* notificar equipo;
* informar al cliente.

## 14.4 Comportamiento del bot

Mientras ningún asesor haya tomado la conversación, se recomienda permitir únicamente:

* confirmación de que la solicitud está registrada;
* FAQ no sensibles;
* recepción de mensajes;
* recepción de archivos;
* actualización de datos sin ejecutar acciones críticas.

## 14.5 Acciones prohibidas

```text
NEGOTIATE
CONFIRM_PAYMENT
CONFIRM_RESERVATION
APPROVE_CANCELLATION
SEND_CUSTOM_PRICE
```

## 14.6 Transiciones permitidas

```text
WAITING_FOR_HUMAN → HUMAN_ACTIVE
WAITING_FOR_HUMAN → BOT_ACTIVE
WAITING_FOR_HUMAN → RESOLVED
WAITING_FOR_HUMAN → CLOSED
```

## 14.7 Guarda `WAITING_FOR_HUMAN → HUMAN_ACTIVE`

```text
agent_assigned = true
agent_has_permission = true
bot_pause_successful = true
```

## 14.7.1 Toma directa desde otros estados

Un asesor autorizado puede tomar manualmente una conversación que aún no esté en
`WAITING_FOR_HUMAN`. Esta operación administrativa debe pasar por las mismas
invariantes de handoff humano y se ejecuta como composición atómica de transiciones
existentes, dentro de una sola transacción:

```text
<estado elegible>
→ WAITING_FOR_HUMAN
→ HUMAN_ACTIVE
```

Estados elegibles:

```text
BOT_ACTIVE
ANSWERING_INFORMATION
COLLECTING_EVENT_DATA
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED
RESOLVED
```

`RESOLVED` implica reapertura auditada antes de entrar a atención humana.

Estados no elegibles:

```text
HUMAN_ACTIVE
CLOSED
WAITING_FOR_HUMAN
```

`HUMAN_ACTIVE` devuelve conflicto porque ya existe un asesor activo.
`CLOSED` requiere reapertura administrativa explícita fuera de este flujo.
`WAITING_FOR_HUMAN` debe tomarse con el handoff pendiente existente para no crear un
segundo handoff.

Efectos obligatorios:

```text
handoff.reason = MANUAL_TAKEOVER
handoff.status = TAKEN
handoff.assigned_agent_id = usuario autenticado
handoff.assigned_to = agent.name
conversation_status = HUMAN_ACTIVE
bot_enabled = false
pending_action = WAIT_FOR_HUMAN
audit_event.action = CONVERSATION_MANUAL_TAKEOVER
```

El handoff nace y se toma en el mismo acto con motivo `MANUAL_TAKEOVER`. La identidad
del asesor o administrador se deriva de su sesión; toda toma conserva
`assigned_agent_id` real.

Esta toma manual no autoriza al sistema a ejecutar acciones críticas. Precios, pagos,
reservas, disponibilidad, citas, devoluciones y descuentos siguen requiriendo servicios
de dominio y autorización humana según sus reglas específicas.

La toma directa no envía ningún mensaje automático al cliente. El primer mensaje tras
la toma lo escribe el asesor.

## 14.8 Cancelación del handoff

Podrá regresar a `BOT_ACTIVE` cuando:

* el cliente ya no requiere asesor;
* un manager cancela el escalamiento;
* la situación fue resuelta automáticamente sin riesgo.

Debe quedar auditado.

---

# 15. HUMAN_ACTIVE

## 15.1 Definición

Estado en el que un asesor humano tiene control exclusivo de la conversación.

## 15.2 Invariante

```text
conversation_status = HUMAN_ACTIVE
→ bot_enabled = false
```

Este estado es persistente. Reiniciar procesos de API, worker, frontend o túnel público
no cambia la asignación humana ni reactiva el bot. La conversación solo sale de
`HUMAN_ACTIVE` mediante una transición explícita registrada por backend.

## 15.3 Acciones de entrada

* asignar asesor;
* guardar hora de toma;
* pausar bot;
* bloquear toma por otros asesores;
* mostrar resumen;
* permitir respuesta humana.
* mostrar hilo de mensajes;
* actualizar el hilo operativo sin recarga manual cuando sea posible.

## 15.4 Acciones permitidas

```text
SEND_AGENT_MESSAGE
UPDATE_CUSTOMER
UPDATE_LEAD
UPDATE_EVENT
CREATE_QUOTE
VALIDATE_PAYMENT
CONFIRM_RESERVATION
REGISTER_RESOLUTION
RETURN_TO_BOT
RESOLVE_CONVERSATION
```

Sujetas a permisos.

## 15.5 Acciones prohibidas para el bot

```text
SEND_AUTOMATIC_REPLY
ASK_AUTOMATIC_QUESTION
EXECUTE_PENDING_BOT_ACTION
```

## 15.6 Transiciones permitidas

```text
HUMAN_ACTIVE → RETURNED_TO_BOT
HUMAN_ACTIVE → RESOLVED
HUMAN_ACTIVE → CLOSED
HUMAN_ACTIVE → WAITING_FOR_HUMAN
```

## 15.7 `HUMAN_ACTIVE → WAITING_FOR_HUMAN`

Puede ocurrir si:

* el asesor libera la conversación;
* debe reasignarse;
* se eleva a otro responsable.

## 15.8 Reasignación

La reasignación deberá ser explícita y auditada.

No puede haber dos asesores activos.

## 15.9 Mensajes durante atención humana

Cuando el cliente envía mensajes durante `HUMAN_ACTIVE`:

```text
mensaje inbound
→ guardar Message
→ actualizar vista operativa
→ no generar respuesta automática
```

La vista del asesor debe leer el historial persistido y puede incluir filas de outbox
no materializadas todavía como `Message OUTBOUND`, indicando su estado operativo:

```text
PENDING
SENDING
FAILED
```

Cuando el worker confirma envío exitoso, el mensaje saliente queda persistido como
`Message OUTBOUND`. Si falla, la causa técnica se conserva en `outbox.last_error` y
la auditoría registra el fallo al agotar intentos.

---

# 16. RETURNED_TO_BOT

## 16.1 Definición

Estado transitorio que indica que un asesor devolvió la conversación a la automatización.

## 16.2 Acciones de entrada

* registrar resolución;
* actualizar resumen;
* actualizar datos;
* eliminar asignación activa;
* establecer `bot_enabled = true`;
* establecer fecha de retorno.

## 16.3 Acciones permitidas

```text
LOAD_UPDATED_CONTEXT
VALIDATE_PENDING_ACTION
RESUME_BOT
ASK_NEXT_PENDING_QUESTION
```

## 16.4 Transiciones permitidas

```text
RETURNED_TO_BOT → BOT_ACTIVE
RETURNED_TO_BOT → COLLECTING_EVENT_DATA
RETURNED_TO_BOT → WAITING_FOR_APPOINTMENT_DATE
RETURNED_TO_BOT → RESOLVED
RETURNED_TO_BOT → WAITING_FOR_HUMAN
```

## 16.5 Guarda

Antes de reactivar:

```text
agent_resolution_saved = true
summary_updated = true
critical_human_action_pending = false
```

## 16.6 Duración

Debe ser un estado corto y transitorio.

---

# 17. RESOLVED

## 17.1 Definición

Estado en el que la interacción actual fue atendida, pero la conversación puede retomarse posteriormente.

## 17.2 Casos

* pregunta respondida;
* visita confirmada;
* solicitud creada;
* cliente se despide;
* asesor resolvió el caso;
* no existe acción inmediata pendiente.

## 17.3 Acciones de entrada

* actualizar resumen;
* establecer `resolved_at`;
* conservar lead;
* conservar acción futura cuando aplique;
* registrar métricas.

## 17.4 Acciones permitidas

```text
REOPEN_CONVERSATION
CREATE_NEW_LEAD
MARK_CLOSED
```

## 17.5 Acciones prohibidas

No se ejecutarán acciones pendientes sin un nuevo evento.

## 17.6 Transiciones permitidas

```text
RESOLVED → BOT_ACTIVE
RESOLVED → HUMAN_ACTIVE
RESOLVED → CLOSED
```

## 17.7 Nuevo mensaje

Cuando llega un nuevo mensaje:

* se puede reabrir la misma conversación;
* o crear una nueva, según política de sesión.

El lead y el historial se conservan.

---

# 18. CLOSED

## 18.1 Definición

Estado final administrativo de una conversación que ya no debe recibir procesamiento normal.

## 18.2 Motivos

* cierre manual;
* conversación archivada;
* duplicado;
* abuso;
* error de creación;
* política de retención;
* cliente restringido.

## 18.3 Acciones permitidas

```text
READ_HISTORY
AUDIT
ADMIN_REOPEN
ARCHIVE
ANONYMIZE_WHEN_ALLOWED
```

## 18.4 Acciones prohibidas

```text
AUTOMATIC_REPLY
CREATE_APPOINTMENT
CREATE_QUOTE_REQUEST
```

sin reapertura autorizada.

## 18.5 Transiciones permitidas

```text
CLOSED → BOT_ACTIVE
CLOSED → HUMAN_ACTIVE
```

Solo mediante reapertura explícita.

---

# 19. Eventos oficiales de transición

```text
CONVERSATION_CREATED
MESSAGE_RECEIVED
INTENT_CLASSIFIED
GENERAL_INFORMATION_DETECTED
EVENT_INFORMATION_DETECTED
QUOTE_REQUEST_DETECTED
QUOTE_MINIMUM_DATA_COMPLETED
QUOTE_SUMMARY_CONFIRMED
QUOTE_REQUEST_CREATED
VISIT_REQUEST_DETECTED
VISIT_DATE_RECEIVED
VISIT_DATE_VALIDATED
VISIT_TIME_SELECTED
VISIT_DATA_COMPLETED
APPOINTMENT_CONFIRMED_BY_CUSTOMER
APPOINTMENT_CREATED
APPOINTMENT_CONFLICT_DETECTED
RESCHEDULE_REQUESTED
CANCEL_VISIT_REQUESTED
HUMAN_REQUESTED
HANDOFF_CREATED
AGENT_ASSIGNED
AGENT_RELEASED
BOT_RETURN_REQUESTED
ISSUE_RESOLVED
FAREWELL_DETECTED
INACTIVITY_TIMEOUT
ADMIN_CLOSE
SYSTEM_ERROR
AI_FAILURE
CALENDAR_FAILURE
PAYMENT_REPORTED
COMPLAINT_DETECTED
EMERGENCY_DETECTED
```

---

# 20. Acciones pendientes oficiales

```text
NONE
CLASSIFY_MESSAGE
ANSWER_INFORMATION
COLLECT_EVENT_TYPE
COLLECT_GUEST_COUNT
COLLECT_EVENT_DATE
COLLECT_CUSTOMER_NAME
COLLECT_BUDGET
COLLECT_SERVICES
CONFIRM_QUOTE_REQUEST
SELECT_VISIT_DATE
CONFIRM_VISIT_DATE
SELECT_VISIT_TIME
COLLECT_VISIT_ATTENDEES
COLLECT_VISIT_REASON
CONFIRM_APPOINTMENT
CONFIRM_RESCHEDULE
CONFIRM_VISIT_CANCELLATION
CONFIRM_EVENT_CANCELLATION
WAIT_FOR_HUMAN
WAIT_FOR_PAYMENT_REVIEW
WAIT_FOR_RESERVATION_CONFIRMATION
```

---

# 21. Tabla general de transiciones conversacionales

| Estado actual                       | Evento             | Estado siguiente                    | Guarda principal        |
| ----------------------------------- | ------------------ | ----------------------------------- | ----------------------- |
| `NEW`                               | Mensaje válido     | `BOT_ACTIVE`                        | Mensaje almacenado      |
| `NEW`                               | Emergencia         | `WAITING_FOR_HUMAN`                 | Handoff creado          |
| `BOT_ACTIVE`                        | FAQ                | `ANSWERING_INFORMATION`             | Categoría identificada  |
| `BOT_ACTIVE`                        | Cotización         | `COLLECTING_EVENT_DATA`             | Lead disponible         |
| `BOT_ACTIVE`                        | Visita             | `WAITING_FOR_APPOINTMENT_DATE`      | Agenda habilitada       |
| `BOT_ACTIVE`                        | Asesor             | `WAITING_FOR_HUMAN`                 | Handoff creado          |
| `ANSWERING_INFORMATION`             | Respuesta enviada  | `BOT_ACTIVE`                        | Sin flujo pendiente     |
| `ANSWERING_INFORMATION`             | Retomar cotización | `COLLECTING_EVENT_DATA`             | Acción pendiente        |
| `COLLECTING_EVENT_DATA`             | Datos incompletos  | `COLLECTING_EVENT_DATA`             | Falta información       |
| `COLLECTING_EVENT_DATA`             | Mínimos completos  | `QUOTE_REQUEST_READY`               | Validación correcta     |
| `QUOTE_REQUEST_READY`               | Cliente corrige    | `COLLECTING_EVENT_DATA`             | Corrección registrada   |
| `QUOTE_REQUEST_READY`               | Cliente confirma   | `WAITING_FOR_HUMAN`                 | Solicitud creada        |
| `WAITING_FOR_APPOINTMENT_DATE`      | Fecha válida       | `WAITING_FOR_APPOINTMENT_SELECTION` | Hay disponibilidad      |
| `WAITING_FOR_APPOINTMENT_SELECTION` | Hora seleccionada  | `APPOINTMENT_PENDING_CONFIRMATION`  | Datos completos         |
| `APPOINTMENT_PENDING_CONFIRMATION`  | Confirmación       | `APPOINTMENT_CONFIRMED`             | Cita creada             |
| `APPOINTMENT_PENDING_CONFIRMATION`  | Conflicto          | `WAITING_FOR_APPOINTMENT_SELECTION` | Horario ocupado         |
| `APPOINTMENT_CONFIRMED`             | Mensaje enviado    | `BOT_ACTIVE`                        | Confirmación almacenada |
| `WAITING_FOR_HUMAN`                 | Asesor toma        | `HUMAN_ACTIVE`                      | Bot pausado             |
| `HUMAN_ACTIVE`                      | Devuelve al bot    | `RETURNED_TO_BOT`                   | Resolución guardada     |
| `RETURNED_TO_BOT`                   | Contexto cargado   | `BOT_ACTIVE`                        | Sin acción crítica      |
| `BOT_ACTIVE`                        | Despedida          | `RESOLVED`                          | Sin pendiente crítico   |
| `RESOLVED`                          | Nuevo mensaje      | `BOT_ACTIVE`                        | Reapertura válida       |
| `RESOLVED`                          | Archivo            | `CLOSED`                            | Acción autorizada       |

---

# 22. Máquina de estados del lead

La máquina conversacional se relacionará con una máquina separada para leads.

## 22.1 Estados

```text
NEW
QUALIFYING
QUALIFIED
QUOTE_REQUESTED
QUOTE_IN_PROGRESS
QUOTE_SENT
VISIT_SCHEDULED
FOLLOW_UP
WON
LOST
ARCHIVED
```

---

## 22.2 NEW

Lead creado con información comercial mínima.

Transiciones:

```text
NEW → QUALIFYING
NEW → LOST
NEW → ARCHIVED
```

---

## 22.3 QUALIFYING

Se están recopilando:

* evento;
* fecha;
* invitados;
* presupuesto;
* servicios.

Transiciones:

```text
QUALIFYING → QUALIFIED
QUALIFYING → QUOTE_REQUESTED
QUALIFYING → VISIT_SCHEDULED
QUALIFYING → LOST
```

---

## 22.4 QUALIFIED

Existe información suficiente para seguimiento comercial.

Transiciones:

```text
QUALIFIED → QUOTE_REQUESTED
QUALIFIED → VISIT_SCHEDULED
QUALIFIED → FOLLOW_UP
QUALIFIED → LOST
```

---

## 22.5 QUOTE_REQUESTED

Existe una solicitud lista.

Transiciones:

```text
QUOTE_REQUESTED → QUOTE_IN_PROGRESS
QUOTE_REQUESTED → LOST
```

---

## 22.6 QUOTE_IN_PROGRESS

Un asesor prepara la propuesta.

Transiciones:

```text
QUOTE_IN_PROGRESS → QUOTE_SENT
QUOTE_IN_PROGRESS → FOLLOW_UP
QUOTE_IN_PROGRESS → LOST
```

---

## 22.7 QUOTE_SENT

La propuesta fue enviada.

Transiciones:

```text
QUOTE_SENT → FOLLOW_UP
QUOTE_SENT → VISIT_SCHEDULED
QUOTE_SENT → WON
QUOTE_SENT → LOST
```

---

## 22.8 VISIT_SCHEDULED

Existe visita confirmada.

Este estado puede coexistir con una cotización.

Transiciones:

```text
VISIT_SCHEDULED → QUOTE_REQUESTED
VISIT_SCHEDULED → QUOTE_SENT
VISIT_SCHEDULED → FOLLOW_UP
VISIT_SCHEDULED → WON
VISIT_SCHEDULED → LOST
```

---

## 22.9 FOLLOW_UP

Existe una acción comercial futura.

Transiciones:

```text
FOLLOW_UP → QUOTE_IN_PROGRESS
FOLLOW_UP → QUOTE_SENT
FOLLOW_UP → VISIT_SCHEDULED
FOLLOW_UP → WON
FOLLOW_UP → LOST
```

---

## 22.10 WON

El lead se considera ganado cuando existe:

* reserva confirmada;
* decisión comercial aprobada;
* pago validado conforme a política.

No debe marcarse únicamente porque el cliente diga que está interesado.

---

## 22.11 LOST

Debe registrar motivo.

Ejemplos:

```text
BUDGET
DATE_UNAVAILABLE
NO_RESPONSE
CLIENT_CANCELLED
CAPACITY
COMPETITOR
OTHER
```

---

# 23. Máquina de estados de solicitudes de cotización

## Estados

```text
DRAFT
READY
ASSIGNED
IN_PROGRESS
COMPLETED
CANCELLED
EXPIRED
```

## Transiciones

```text
DRAFT → READY
DRAFT → CANCELLED
READY → ASSIGNED
READY → CANCELLED
READY → EXPIRED
ASSIGNED → IN_PROGRESS
ASSIGNED → CANCELLED
IN_PROGRESS → COMPLETED
IN_PROGRESS → CANCELLED
```

## Guardas

### `DRAFT → READY`

```text
minimum_data_complete = true
customer_confirmation = true
```

### `READY → ASSIGNED`

```text
agent_available = true
request_not_assigned = true
```

### `IN_PROGRESS → COMPLETED`

```text
quote_created = true
quote_sent_or_registered = true
```

---

# 24. Máquina de estados de cotización

## Estados

```text
DRAFT
PRELIMINARY
REVIEW_REQUIRED
APPROVED
SENT
ACCEPTED
REJECTED
EXPIRED
SUPERSEDED
```

## Transiciones principales

```text
DRAFT → PRELIMINARY
DRAFT → REVIEW_REQUIRED
PRELIMINARY → APPROVED
PRELIMINARY → REVIEW_REQUIRED
REVIEW_REQUIRED → APPROVED
APPROVED → SENT
SENT → ACCEPTED
SENT → REJECTED
SENT → EXPIRED
SENT → SUPERSEDED
ACCEPTED → SUPERSEDED
```

## Invariantes

* una cotización `SENT` no se edita;
* una modificación crea una nueva versión;
* `SUPERSEDED` conserva historial;
* `ACCEPTED` no significa fecha reservada.

---

# 25. Máquina de estados de visitas

## Estados

```text
PENDING_CONFIRMATION
CONFIRMED
RESCHEDULED
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

## Transiciones

```text
PENDING_CONFIRMATION → CONFIRMED
PENDING_CONFIRMATION → CANCELLED
CONFIRMED → RESCHEDULED
CONFIRMED → CANCELLED
CONFIRMED → LATE_CANCEL
CONFIRMED → COMPLETED
CONFIRMED → NO_SHOW
RESCHEDULED → RESCHEDULED
RESCHEDULED → CANCELLED
RESCHEDULED → LATE_CANCEL
RESCHEDULED → COMPLETED
RESCHEDULED → NO_SHOW
```

## Estados finales

```text
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

Una visita finalizada no deberá volver a `CONFIRMED` sin crear una nueva cita o acción administrativa especial.

---

# 26. Máquina de estados de pagos

## Estados

```text
PAYMENT_PENDING
PAYMENT_REVIEW
PAYMENT_CONFIRMED
PAYMENT_REJECTED
PAYMENT_CANCELLED
```

## Transiciones

```text
PAYMENT_PENDING → PAYMENT_REVIEW
PAYMENT_PENDING → PAYMENT_CANCELLED
PAYMENT_REVIEW → PAYMENT_CONFIRMED
PAYMENT_REVIEW → PAYMENT_REJECTED
PAYMENT_REVIEW → PAYMENT_CANCELLED
PAYMENT_REJECTED → PAYMENT_REVIEW
```

## Autoridad

### Bot

Puede solicitar:

```text
PAYMENT_PENDING → PAYMENT_REVIEW
```

cuando recibe información o comprobante.

### Asesor

Puede ejecutar:

```text
PAYMENT_REVIEW → PAYMENT_CONFIRMED
PAYMENT_REVIEW → PAYMENT_REJECTED
```

## Invariante

La IA nunca podrá establecer `PAYMENT_CONFIRMED`.

---

# 27. Máquina de estados de reserva

## Estados

```text
INQUIRY
QUOTED
PAYMENT_PENDING
PAYMENT_REVIEW
RESERVED
CANCEL_REQUESTED
CANCELLED
COMPLETED
```

## Transiciones

```text
INQUIRY → QUOTED
QUOTED → PAYMENT_PENDING
PAYMENT_PENDING → PAYMENT_REVIEW
PAYMENT_REVIEW → RESERVED
RESERVED → CANCEL_REQUESTED
RESERVED → COMPLETED
CANCEL_REQUESTED → CANCELLED
CANCEL_REQUESTED → RESERVED
```

## Guarda crítica `PAYMENT_REVIEW → RESERVED`

```text
payment_status = PAYMENT_CONFIRMED
deposit_requirement_met = true
event_date_available = true
authorized_agent_confirmation = true
```

## Invariante

```text
reservation_status = RESERVED
→ payment_status = PAYMENT_CONFIRMED
```

---

# 28. Máquina de estados del handoff

## Estados recomendados

```text
PENDING
ASSIGNED
ACCEPTED
IN_PROGRESS
RESOLVED
CANCELLED
```

## Transiciones

```text
PENDING → ASSIGNED
PENDING → CANCELLED
ASSIGNED → ACCEPTED
ASSIGNED → PENDING
ACCEPTED → IN_PROGRESS
IN_PROGRESS → RESOLVED
IN_PROGRESS → PENDING
```

## Relación con conversación

| Handoff       | Conversación                   |
| ------------- | ------------------------------ |
| `PENDING`     | `WAITING_FOR_HUMAN`            |
| `ASSIGNED`    | `WAITING_FOR_HUMAN`            |
| `ACCEPTED`    | `HUMAN_ACTIVE`                 |
| `IN_PROGRESS` | `HUMAN_ACTIVE`                 |
| `RESOLVED`    | `RETURNED_TO_BOT` o `RESOLVED` |

---

# 29. Estados de error técnico

Se recomienda no utilizar errores como estados principales permanentes de conversación.

En su lugar, registrar:

```text
last_error_code
recovery_status
retry_count
```

## Estados de recuperación sugeridos

```text
NONE
RETRY_PENDING
RECONCILIATION_REQUIRED
HUMAN_REVIEW_REQUIRED
RECOVERED
FAILED_PERMANENTLY
```

---

# 30. Fallo de inteligencia artificial

## Evento

```text
AI_FAILURE
```

## Comportamiento por estado

### `ANSWERING_INFORMATION`

* usar respuesta determinista;
* regresar al flujo.

### `COLLECTING_EVENT_DATA`

* solicitar aclaración;
* conservar mensaje;
* no perder contexto.

### Flujo crítico

* crear handoff;
* pasar a `WAITING_FOR_HUMAN`.

## Prohibición

No cambiar un estado crítico usando una salida inválida.

---

# 31. Fallo de calendario

## Evento

```text
CALENDAR_FAILURE
```

## Durante consulta

```text
WAITING_FOR_APPOINTMENT_DATE
o
WAITING_FOR_APPOINTMENT_SELECTION
→ WAITING_FOR_HUMAN
```

si no puede recuperarse.

## Durante creación

La conversación no pasa a `APPOINTMENT_CONFIRMED`.

Debe permanecer en:

```text
APPOINTMENT_PENDING_CONFIRMATION
```

o pasar a:

```text
WAITING_FOR_HUMAN
```

## Durante reprogramación

La cita original debe conservarse hasta confirmar la nueva.

## Durante cancelación

No marcar la cita como cancelada definitivamente si el proveedor externo no confirmó.

---

# 32. Fallo de envío de mensaje

Si el mensaje de respuesta falla:

* el estado de negocio no debe revertirse automáticamente;
* el mensaje se marca con error;
* se programa reintento;
* se evita enviar dos veces;
* se alerta si era crítico.

Ejemplo:

La cita puede estar creada aunque falle el mensaje de confirmación.

El sistema deberá reconciliar y reenviar sin crear otra cita.

---

# 33. Mensajes duplicados

El mensaje duplicado no deberá provocar transición.

```text
external_message_id ya procesado
→ conservar estado actual
```

No se repetirá:

* respuesta;
* cita;
* solicitud;
* pago;
* reserva;
* handoff.

---

# 34. Tiempo de inactividad

## 34.1 Estados que pueden permanecer abiertos

```text
BOT_ACTIVE
COLLECTING_EVENT_DATA
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
QUOTE_REQUEST_READY
WAITING_FOR_HUMAN
```

## 34.2 Recomendación

Después de un periodo configurable:

* generar resumen;
* conservar datos;
* marcar `RESOLVED`;
* no eliminar el lead.

## 34.3 Estados que no deben cerrarse automáticamente

Cuando exista:

* pago en revisión;
* cancelación;
* queja;
* emergencia;
* asesor activo;
* cita en proceso de creación;
* reserva pendiente de confirmación.

---

# 35. Reapertura

Cuando llega un nuevo mensaje a una conversación `RESOLVED`:

```text
RESOLVED → BOT_ACTIVE
```

si:

* se trata del mismo cliente;
* no existe una razón para una nueva conversación;
* el canal es el mismo.

Cuando existen varios leads activos, el bot deberá preguntar cuál desea continuar.

---

# 36. Reglas de interrupción

Una intención prioritaria puede interrumpir cualquier estado.

## Prioridad

```text
1. EMERGENCY
2. COMPLAINT
3. PAYMENT_MESSAGE
4. EVENT_CANCELLATION
5. HUMAN_REQUEST
```

Ejemplo:

```text
COLLECTING_EVENT_DATA
+ PAYMENT_MESSAGE
→ WAITING_FOR_HUMAN
```

El estado anterior deberá conservarse como contexto recuperable.

---

# 37. Reglas para cambio temporal de tema

Cuando el cliente pregunta algo informativo dentro de un flujo:

```text
estado_actual = COLLECTING_EVENT_DATA
pending_action = COLLECT_EVENT_DATE
```

El sistema puede pasar temporalmente a:

```text
ANSWERING_INFORMATION
```

Después:

```text
ANSWERING_INFORMATION
→ COLLECTING_EVENT_DATA
```

El `pending_action` original se conserva.

---

# 38. Reglas de confirmación contextual

Un mensaje como:

```text
“Sí”
```

solo podrá ejecutar una transición cuando exista:

```text
pending_action
last_question_code
```

Ejemplo válido:

```text
pending_action = CONFIRM_APPOINTMENT
```

Entonces:

```text
“Sí”
→ intentar crear cita
```

Ejemplo no válido:

```text
pending_action = NONE
```

Entonces el bot deberá pedir aclaración.

---

# 39. Bloqueos e invariantes críticos

## INV-ST-001 — Bot pausado

```text
conversation_status = HUMAN_ACTIVE
→ bot_enabled = false
```

---

## INV-ST-002 — Reserva válida

```text
reservation_status = RESERVED
→ payment_status = PAYMENT_CONFIRMED
```

---

## INV-ST-003 — Visita confirmada

```text
appointment_status = CONFIRMED
→ external_calendar_id != null
```

---

## INV-ST-004 — Solicitud lista

```text
quote_request_status = READY
→ minimum_data_complete = true
```

---

## INV-ST-005 — Cotización enviada

```text
quote_status = SENT
→ version_number != null
```

---

## INV-ST-006 — Un asesor activo

```text
conversation_id
→ máximo un assigned_agent activo
```

---

## INV-ST-007 — Mensaje único

```text
external_message_id
→ único
```

---

## INV-ST-008 — Estado cerrado

```text
conversation_status = CLOSED
→ bot_enabled = false
```

salvo reapertura explícita.

---

## INV-ST-009 — Fechas relativas

No se crea cita con fecha relativa sin confirmar su fecha absoluta.

---

## INV-ST-010 — Servicio solicitado

```text
service_status = REQUESTED
```

no permite comunicar:

```text
INCLUDED
```

---

# 40. Matriz de permisos por estado conversacional

| Estado                              |    Bot responde | Asesor responde |      Acciones críticas |
| ----------------------------------- | --------------: | --------------: | ---------------------: |
| `NEW`                               |      No todavía |              No |                     No |
| `BOT_ACTIVE`                        |              Sí |     Sí, si toma |           Solo backend |
| `ANSWERING_INFORMATION`             |              Sí |              Sí |                     No |
| `COLLECTING_EVENT_DATA`             |              Sí |              Sí |                     No |
| `QUOTE_REQUEST_READY`               |              Sí |              Sí |        Crear solicitud |
| `WAITING_FOR_APPOINTMENT_DATE`      |              Sí |              Sí |       Consultar agenda |
| `WAITING_FOR_APPOINTMENT_SELECTION` |              Sí |              Sí |       Consultar agenda |
| `APPOINTMENT_PENDING_CONFIRMATION`  |              Sí |              Sí | Crear cita con guardas |
| `APPOINTMENT_CONFIRMED`             |              Sí |              Sí |         Cita ya creada |
| `WAITING_FOR_HUMAN`                 |        Limitado |              Sí |         Según permisos |
| `HUMAN_ACTIVE`                      |              No |   Sí, exclusivo |          Sí, según rol |
| `RETURNED_TO_BOT`                   |     Transitorio |              No |                     No |
| `RESOLVED`                          | Solo al reabrir |              Sí |          No automática |
| `CLOSED`                            |              No |      Solo admin |                     No |

---

# 41. Acciones de entrada por estado

| Estado                              | Acción principal de entrada    |
| ----------------------------------- | ------------------------------ |
| `NEW`                               | Crear y cargar contexto        |
| `BOT_ACTIVE`                        | Esperar o clasificar intención |
| `ANSWERING_INFORMATION`             | Recuperar respuesta aprobada   |
| `COLLECTING_EVENT_DATA`             | Calcular campos faltantes      |
| `QUOTE_REQUEST_READY`               | Generar resumen                |
| `WAITING_FOR_APPOINTMENT_DATE`      | Solicitar fecha                |
| `WAITING_FOR_APPOINTMENT_SELECTION` | Mostrar horarios               |
| `APPOINTMENT_PENDING_CONFIRMATION`  | Mostrar resumen                |
| `APPOINTMENT_CONFIRMED`             | Enviar confirmación            |
| `WAITING_FOR_HUMAN`                 | Crear y notificar handoff      |
| `HUMAN_ACTIVE`                      | Pausar bot                     |
| `RETURNED_TO_BOT`                   | Recargar contexto              |
| `RESOLVED`                          | Actualizar resumen y métricas  |
| `CLOSED`                            | Bloquear procesamiento         |

---

# 42. Acciones de salida por estado

| Estado                              | Acción de salida                   |
| ----------------------------------- | ---------------------------------- |
| `NEW`                               | Registrar primera clasificación    |
| `ANSWERING_INFORMATION`             | Conservar respuesta enviada        |
| `COLLECTING_EVENT_DATA`             | Persistir datos                    |
| `QUOTE_REQUEST_READY`               | Crear solicitud o volver a captura |
| `WAITING_FOR_APPOINTMENT_DATE`      | Guardar fecha validada             |
| `WAITING_FOR_APPOINTMENT_SELECTION` | Guardar horario                    |
| `APPOINTMENT_PENDING_CONFIRMATION`  | Crear cita o registrar rechazo     |
| `WAITING_FOR_HUMAN`                 | Asignar asesor                     |
| `HUMAN_ACTIVE`                      | Guardar resolución                 |
| `RETURNED_TO_BOT`                   | Habilitar automatización           |
| `RESOLVED`                          | Guardar fecha de resolución        |
| `CLOSED`                            | Mantener archivo                   |

---

# 43. Pseudocódigo del orquestador

```text
function processMessage(message):
    conversation = loadConversation(message.customer)

    if isDuplicate(message.external_id):
        return successWithoutProcessing()

    persist(message)

    if conversation.status == CLOSED:
        handleClosedConversation(conversation, message)
        return

    if conversation.status == HUMAN_ACTIVE:
        routeToAssignedAgent(message)
        return

    classification = classifyIntent(message, conversation.context)

    if classification.isCritical:
        createHandoff(classification)
        transition(conversation, WAITING_FOR_HUMAN)
        sendSafeResponse()
        return

    action = resolveAction(
        state=conversation.status,
        intent=classification.intent,
        entities=classification.entities,
        pendingAction=conversation.pending_action
    )

    if not isActionAllowed(conversation.status, action):
        requestClarificationOrEscalate()
        return

    validation = validateAction(action)

    if not validation.valid:
        handleValidationFailure(validation)
        return

    result = executeAction(action)

    transition(conversation, result.nextState)

    persistAudit()
    sendResponse(result.response)
```

---

# 44. Reglas de implementación

## 44.1 Transacciones

Las transiciones críticas deberán ejecutarse dentro de una transacción o mecanismo equivalente.

Casos:

* creación de cita;
* reprogramación;
* cancelación;
* toma de conversación;
* confirmación de pago;
* confirmación de reserva;
* creación de solicitud.

## 44.2 Optimistic locking

Se recomienda utilizar control de versión en:

* `Conversation`;
* `Appointment`;
* `Payment`;
* `Reservation`;
* `Handoff`.

Ejemplo:

```text
version
```

para evitar actualizaciones simultáneas.

## 44.3 Idempotency keys

Cada operación crítica deberá aceptar una clave de idempotencia.

Ejemplos:

```text
CREATE_APPOINTMENT:{conversation_id}:{confirmation_message_id}
CONFIRM_PAYMENT:{payment_id}:{review_action_id}
```

## 44.4 Registro de transición

Cada transición deberá registrar:

```json
{
  "entity": "Conversation",
  "entity_id": "uuid",
  "from_state": "WAITING_FOR_APPOINTMENT_SELECTION",
  "to_state": "APPOINTMENT_PENDING_CONFIRMATION",
  "event": "VISIT_TIME_SELECTED",
  "actor": "CUSTOMER",
  "timestamp": "2026-08-05T11:45:00-05:00"
}
```

---

# 45. Casos de prueba obligatorios

## Estado inicial

* conversación nueva pasa a `BOT_ACTIVE`;
* mensaje duplicado no produce transición.

## Información

* FAQ regresa a estado anterior;
* FAQ sin respuesta aprobada escala.

## Cotización

* datos incompletos mantienen `COLLECTING_EVENT_DATA`;
* datos completos pasan a `QUOTE_REQUEST_READY`;
* corrección devuelve a captura;
* solicitud confirmada genera handoff.

## Visitas

* fecha inválida conserva `WAITING_FOR_APPOINTMENT_DATE`;
* fecha válida pasa a selección;
* hora seleccionada pasa a confirmación;
* cita no se crea sin confirmación;
* conflicto vuelve a selección;
* cita creada pasa a `APPOINTMENT_CONFIRMED`.

## Handoff

* solicitud crea `WAITING_FOR_HUMAN`;
* asesor toma y pasa a `HUMAN_ACTIVE`;
* bot queda deshabilitado;
* devolución pasa por `RETURNED_TO_BOT`.

## Pagos

* pago reportado no cambia a confirmado;
* pago crea handoff urgente;
* reserva no se confirma sin pago validado.

## Errores

* fallo de IA no ejecuta acción crítica;
* fallo de calendario no confirma cita;
* fallo de envío no duplica operación.

## Reapertura

* conversación resuelta puede reabrirse;
* conversación cerrada requiere autorización.

---

# 46. Métricas de estados

El sistema deberá medir:

* conversaciones por estado;
* tiempo promedio por estado;
* transiciones fallidas;
* transiciones rechazadas;
* conversaciones estancadas;
* tiempo en `WAITING_FOR_HUMAN`;
* tiempo en `HUMAN_ACTIVE`;
* citas abandonadas antes de confirmar;
* solicitudes abandonadas;
* reaperturas;
* errores de concurrencia;
* intentos de transición inválida;
* fallos de guardas.

---

# 47. Alertas recomendadas

## Conversaciones estancadas

* `WAITING_FOR_HUMAN` por encima del SLA;
* `APPOINTMENT_PENDING_CONFIRMATION` por tiempo excesivo;
* `QUOTE_REQUEST_READY` sin solicitud creada;
* `RETURNED_TO_BOT` sin transición;
* `HUMAN_ACTIVE` sin actividad prolongada.

## Inconsistencias críticas

* `HUMAN_ACTIVE` con `bot_enabled = true`;
* `RESERVED` sin pago confirmado;
* `CONFIRMED` sin evento de calendario;
* dos asesores activos;
* cita duplicada;
* conversación cerrada enviando mensajes automáticos.

---

# 48. Criterios de aceptación

La máquina de estados se considerará correctamente implementada cuando:

1. Solo existan estados permitidos.
2. Toda transición se produzca mediante evento.
3. Las guardas se validen en backend.
4. El bot no responda en `HUMAN_ACTIVE`.
5. Una cita no se confirme sin calendario.
6. Una reserva no exista sin pago confirmado.
7. Una solicitud lista tenga datos mínimos.
8. Los estados de conversación y lead sean independientes.
9. Los mensajes duplicados no cambien estados.
10. Las fechas relativas se confirmen.
11. Los errores no generen confirmaciones falsas.
12. Las transiciones críticas sean idempotentes.
13. Exista auditoría completa.
14. Las interrupciones prioritarias funcionen.
15. Los flujos temporales puedan retomarse.
16. Las conversaciones puedan reabrirse.
17. Las conversaciones cerradas no procesen mensajes automáticamente.
18. Los fallos de integración puedan reconciliarse.
19. Existan métricas por estado.
20. Existan pruebas automatizadas de todas las transiciones críticas.

---

# 49. Definición de terminado

La implementación estará terminada cuando:

* exista la enumeración oficial;
* exista el motor de transición;
* existan guardas;
* existan eventos;
* existan acciones de entrada y salida;
* exista persistencia;
* exista control de concurrencia;
* exista idempotencia;
* exista auditoría;
* existan pruebas unitarias;
* existan pruebas de integración;
* existan pruebas conversacionales;
* existan alertas;
* exista documentación de recuperación;
* todos los invariantes críticos estén protegidos.

---

# 50. Aprobación

Este documento queda listo como fuente oficial para:

* máquina de estados;
* orquestador conversacional;
* servicios de dominio;
* contratos internos;
* persistencia;
* validaciones;
* pruebas;
* auditoría;
* observabilidad;
* manejo de errores.

Su aprobación implica que:

* los estados principales están definidos;
* las transiciones están delimitadas;
* las operaciones críticas tienen guardas;
* la intervención humana está controlada;
* el bot no puede responder simultáneamente con un asesor;
* las citas, pagos y reservas tienen estados independientes;
* el MVP puede implementarse de manera determinista y auditable.
