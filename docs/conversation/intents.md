# Catálogo de intenciones conversacionales

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/conversation/intents.md`
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

---

# 1. Propósito

Este documento define el catálogo oficial de intenciones que utilizará el Asistente Conversacional de La Ceiba Club House.

La clasificación de intenciones permitirá determinar:

* qué necesita el cliente;
* qué información debe recuperarse;
* qué datos deben extraerse;
* qué estado conversacional corresponde;
* qué acción puede solicitarse al backend;
* cuándo debe pedirse una aclaración;
* cuándo debe transferirse la conversación;
* qué respuesta aprobada debe utilizarse;
* qué operaciones están prohibidas para la inteligencia artificial.

Este catálogo será utilizado para:

* entrenamiento y evaluación de prompts;
* contratos estructurados con OpenRouter;
* diseño del orquestador;
* máquina de estados;
* pruebas conversacionales;
* métricas de clasificación;
* reglas de fallback;
* escalamiento humano;
* diseño de APIs internas.

---

# 2. Principios de clasificación

## INT-GEN-001 — La intención no ejecuta la acción

La intención representa lo que el cliente parece querer.

Ejemplo:

```text
intent = SCHEDULE_VISIT
```

Esto no significa que la visita pueda crearse inmediatamente.

Antes de ejecutar se deberán validar:

* datos obligatorios;
* reglas de agenda;
* permisos;
* disponibilidad;
* confirmación del cliente;
* estado de la conversación.

---

## INT-GEN-002 — La IA propone; el backend valida

La inteligencia artificial podrá proponer:

* intención;
* subintención;
* entidades;
* confianza;
* acción solicitada;
* necesidad de escalamiento.

El backend deberá validar:

* que la intención exista;
* que la acción esté permitida;
* que el estado permita la acción;
* que los campos sean válidos;
* que el cliente tenga autorización;
* que no exista conflicto.

---

## INT-GEN-003 — Una intención principal

Cada mensaje deberá tener una intención principal.

Ejemplo:

> Quiero cotizar una boda para 30 personas y también ir mañana.

Resultado recomendado:

```json
{
  "primary_intent": "QUOTE_REQUEST",
  "secondary_intents": [
    "SCHEDULE_VISIT"
  ]
}
```

---

## INT-GEN-004 — Intenciones secundarias

El sistema podrá registrar intenciones secundarias cuando el mensaje contenga varias solicitudes.

La intención principal deberá seleccionarse según:

1. acción más urgente;
2. operación más crítica;
3. solicitud explícita;
4. contexto conversacional;
5. acción pendiente.

---

## INT-GEN-005 — Contexto obligatorio

Mensajes breves como:

* “sí”;
* “no”;
* “esa”;
* “la primera”;
* “el sábado”;
* “está bien”;
* “cámbiala”;

no deberán clasificarse sin consultar:

* última pregunta;
* opciones mostradas;
* acción pendiente;
* estado conversacional;
* datos ya conocidos.

---

## INT-GEN-006 — Persistencia de intención

La intención actual no deberá eliminar automáticamente la acción pendiente.

Ejemplo:

1. El cliente está solicitando una cotización.
2. Pregunta por parqueadero.
3. El bot responde.
4. El sistema retoma la captura de la cotización.

---

## INT-GEN-007 — Intenciones críticas

Las siguientes intenciones tendrán prioridad sobre flujos comerciales ordinarios:

```text
EMERGENCY
COMPLAINT
PAYMENT_MESSAGE
EVENT_CANCELLATION
HUMAN_REQUEST
```

---

# 3. Estructura de salida esperada

La clasificación deberá devolver un objeto estructurado semejante a:

```json
{
  "primary_intent": "QUOTE_REQUEST",
  "secondary_intents": [],
  "sub_intent": "CUSTOM_EVENT_QUOTE",
  "confidence": 0.94,
  "entities": {
    "event_type": "WEDDING",
    "guest_count": 45,
    "event_date": "2026-12-12"
  },
  "requested_action": "COLLECT_MISSING_QUOTE_DATA",
  "missing_fields": [
    "full_name"
  ],
  "needs_confirmation": false,
  "needs_human": false,
  "priority": "NORMAL",
  "reasoning_code": "EXPLICIT_QUOTE_REQUEST"
}
```

La respuesta estructurada no deberá enviarse al cliente.

---

# 4. Catálogo principal de intenciones

El MVP utilizará las siguientes intenciones principales:

```text
GREETING
GENERAL_INFORMATION
EVENT_INFORMATION
QUOTE_REQUEST
MODIFY_EVENT_DATA
SCHEDULE_VISIT
RESCHEDULE_VISIT
CANCEL_VISIT
PAYMENT_MESSAGE
RESERVATION_INFORMATION
EVENT_CANCELLATION
HUMAN_REQUEST
COMPLAINT
EMERGENCY
FAREWELL
UNKNOWN
```

---

# 5. GREETING

## 5.1 Definición

El cliente inicia o retoma la conversación sin expresar todavía una necesidad específica.

## 5.2 Ejemplos positivos

* “Hola”.
* “Buenos días”.
* “Buenas tardes”.
* “Buenas”.
* “Hola, ¿cómo están?”
* “Quisiera información”.
* “Hola de nuevo”.
* “Buenas noches”.

## 5.3 Ejemplos negativos

* “Hola, quiero cotizar una boda”.

  * Intención principal: `QUOTE_REQUEST`.
* “Buenos días, quiero cancelar mi cita”.

  * Intención principal: `CANCEL_VISIT`.
* “Hola, ya pagué”.

  * Intención principal: `PAYMENT_MESSAGE`.

## 5.4 Entidades esperadas

Normalmente ninguna.

Posibles entidades:

* nombre;
* tratamiento;
* idioma.

## 5.5 Acciones permitidas

```text
CREATE_OR_RESUME_CONVERSATION
SEND_GREETING
ASK_INITIAL_NEED
```

## 5.6 Respuesta base

> ¡Hola! Somos el equipo de La Ceiba Club House. Nos encantará ayudarte. ¿Qué tipo de celebración o experiencia estás planeando?

## 5.7 Estado sugerido

```text
BOT_ACTIVE
```

## 5.8 Escalamiento

No.

## 5.9 Confianza mínima

```text
0.70
```

Si el mensaje contiene además una solicitud clara, deberá seleccionarse la intención específica y no `GREETING`.

---

# 6. GENERAL_INFORMATION

## 6.1 Definición

El cliente solicita información general autorizada sobre La Ceiba.

## 6.2 Subintenciones

```text
LOCATION
MAP_LINK
PARKING
GENERAL_CAPACITY
SPACES
EVENT_HOURS
CAFE_HOURS
POOL
PETS
EXTERNAL_FOOD
EXTERNAL_BEVERAGES
EXTERNAL_ALCOHOL
CORKAGE
EXTERNAL_SUPPLIERS
ACCOMMODATION
SERVICES
PAYMENT_METHODS
BUSINESS_HOURS
SUPPORTED_EVENT_TYPES
GENERAL_RESERVATION_PROCESS
```

---

## 6.3 LOCATION

### Ejemplos positivos

* “¿Dónde están ubicados?”
* “¿Cuál es la dirección?”
* “¿En qué parte de Bucaramanga quedan?”
* “Pásame la ubicación”.
* “¿Cómo llego?”

### Entidades esperadas

Ninguna.

### Acción permitida

```text
GET_APPROVED_KNOWLEDGE
SEND_LOCATION
```

### Respuesta autorizada

> Estamos en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander.

---

## 6.4 MAP_LINK

### Ejemplos positivos

* “Pásame el Maps”.
* “¿Tienen enlace de ubicación?”
* “Mándame la ubicación por Google Maps”.

### Acción permitida

```text
SEND_MAP_LINK
```

### Valor autorizado

```text
https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw
```

---

## 6.5 PARKING

### Ejemplos positivos

* “¿Tienen parqueadero?”
* “¿Dónde dejo el carro?”
* “¿Hay dónde parquear?”
* “¿El parqueadero está incluido?”

### Entidades posibles

* número de vehículos;
* tipo de vehículo.

### Respuesta autorizada

> Sí, contamos con parqueadero para nuestros clientes e invitados. La disponibilidad depende de la cantidad de asistentes y del montaje del evento.

### Prohibiciones

No inventar:

* capacidad;
* vigilancia;
* cobertura;
* reserva de cupos.

---

## 6.6 GENERAL_CAPACITY

### Ejemplos positivos

* “¿Cuántas personas caben?”
* “¿Cuál es el aforo?”
* “¿Puedo hacer un evento para 50?”
* “¿Reciben 80 personas?”

### Entidades esperadas

* `guest_count`.

### Acciones

```text
ANSWER_CAPACITY
FLAG_CAPACITY_REVIEW
```

### Regla

Más de 60 personas:

```text
needs_human = true
handoff_reason = CAPACITY_REVIEW
```

---

## 6.7 SPACES

### Ejemplos positivos

* “¿Qué espacios tienen?”
* “¿Tienen terraza?”
* “¿Tienen salones?”
* “¿Hay quiosco?”
* “¿Qué capacidad tiene la terraza?”

### Entidades esperadas

* `preferred_space`;
* `guest_count`.

### Valores permitidos

```text
TERRAZA_LA_CEIBA
SALON_CEIBA_1
SALON_CEIBA_2
SALONES_COMBINADOS
QUIOSCO_PISCINA
OTHER
```

---

## 6.8 EVENT_HOURS

### Ejemplos positivos

* “¿Hasta qué hora puede durar?”
* “¿Puedo hacer fiesta hasta tarde?”
* “¿Cuál es el horario de los eventos?”

### Acción

```text
ANSWER_STANDARD_EVENT_HOURS
```

### Regla

Horario habitual:

```text
22:00
```

Solicitudes de extensión:

```text
needs_human = true
handoff_reason = SPECIAL_EVENT
```

---

## 6.9 CAFE_HOURS

### Ejemplos positivos

* “¿La cafetería abre?”
* “¿Puedo ir a desayunar?”
* “¿A qué hora venden café?”

### Respuesta base

> Nuestra cafetería funciona inicialmente de martes a sábado, entre las 8:00 a. m. y las 12:00 m.

---

## 6.10 POOL

### Ejemplos positivos

* “¿Tienen piscina?”
* “¿Está incluida?”
* “¿La podemos usar?”
* “¿Los niños pueden entrar a la piscina?”

### Entidades posibles

* uso esperado;
* menores;
* fecha;
* evento.

### Regla

La piscina está incluida, su uso está sujeto a condiciones de seguridad.

---

## 6.11 PETS

### Ejemplos positivos

* “¿Aceptan mascotas?”
* “¿Puedo llevar a mi perro?”
* “¿Son pet friendly?”

### Entidades posibles

* cantidad de mascotas;
* tipo de mascota.

### Acción

```text
REGISTER_PET_ATTENDANCE
ANSWER_PET_POLICY
```

---

## 6.12 EXTERNAL_FOOD

### Ejemplos positivos

* “¿Puedo llevar comida?”
* “Ya tengo catering”.
* “¿Puedo llevar la torta?”
* “¿Aceptan comida externa?”

### Entidades posibles

* tipo de alimento;
* proveedor externo.

### Regla

Está permitido, sujeto a coordinación.

---

## 6.13 EXTERNAL_BEVERAGES y EXTERNAL_ALCOHOL

### Ejemplos positivos

* “¿Puedo llevar bebidas?”
* “Yo llevo el whisky”.
* “¿Puedo llevar licor?”
* “¿Puedo llevar cerveza?”

### Entidades posibles

* tipo de bebida;
* alcohol esperado.

### Regla

Permitido y sin descorche.

---

## 6.14 CORKAGE

### Ejemplos positivos

* “¿Cobran descorche?”
* “¿Cuánto vale ingresar licor?”

### Respuesta

> No manejamos cobro de descorche. El ingreso de bebidas y licor debe coordinarse previamente con nuestro equipo.

---

## 6.15 EXTERNAL_SUPPLIERS

### Ejemplos positivos

* “¿Puedo llevar fotógrafo?”
* “Ya tengo decorador”.
* “¿Puede entrar mi DJ?”
* “¿Cobran por proveedores externos?”

### Entidades posibles

* tipo de proveedor;
* servicio.

### Regla

Permitido sin cobro general de ingreso, sujeto a coordinación.

---

## 6.16 ACCOMMODATION

### Ejemplos positivos

* “¿Tienen habitaciones?”
* “¿Puedo quedarme esa noche?”
* “¿Tienen suite para novios?”
* “¿Incluye alojamiento?”

### Entidades posibles

* fecha;
* número de huéspedes;
* alojamiento requerido.

### Acción

```text
REGISTER_ACCOMMODATION_INTEREST
ANSWER_CONDITIONAL_AVAILABILITY
```

### Regla

No confirmar disponibilidad automática.

---

## 6.17 SERVICES

### Ejemplos positivos

* “¿Qué incluye?”
* “¿Qué servicios ofrecen?”
* “¿Tienen decoración?”
* “¿Tienen DJ?”
* “¿Tienen fotógrafo?”

### Entidades esperadas

* lista de servicios.

### Acciones

```text
ANSWER_SERVICE_OVERVIEW
REGISTER_REQUESTED_SERVICES
FLAG_SUPPLIER_CONFIRMATION
```

---

## 6.18 PAYMENT_METHODS

### Ejemplos positivos

* “¿Cómo puedo pagar?”
* “¿Reciben tarjeta?”
* “¿Tienen Nequi?”
* “¿Puedo pagar en efectivo?”

### Valores autorizados

```text
BANK_TRANSFER
CASH
CARD
NEQUI
DAVIPLATA
PAYMENT_LINK
```

### Prohibición

No compartir números de cuenta inventados.

---

## 6.19 SUPPORTED_EVENT_TYPES

### Ejemplos positivos

* “¿Qué eventos realizan?”
* “¿Hacen matrimonios?”
* “¿Atienden cumpleaños?”
* “¿Puedo hacer un evento empresarial?”

### Acción

```text
ANSWER_SUPPORTED_EVENTS
```

---

## 6.20 Acciones permitidas para GENERAL_INFORMATION

```text
GET_APPROVED_KNOWLEDGE
SEND_APPROVED_ANSWER
REGISTER_OPTIONAL_EVENT_DATA
RESUME_PENDING_FLOW
CREATE_HANDOFF_IF_CONDITIONAL
```

## 6.21 Acciones prohibidas

```text
CALCULATE_PRICE
CONFIRM_SERVICE_AVAILABILITY
CONFIRM_RESERVATION
CONFIRM_PAYMENT
```

## 6.22 Confianza mínima

```text
0.75
```

## 6.23 Escalamiento

Cuando:

* no existe respuesta aprobada;
* se solicita excepción;
* capacidad supera 60;
* se pide extensión de horario;
* se requiere disponibilidad de proveedor;
* el cliente solicita confirmación contractual.

---

# 7. EVENT_INFORMATION

## 7.1 Definición

El cliente expresa o amplía información sobre el evento, pero no solicita necesariamente una cotización o una visita.

## 7.2 Ejemplos positivos

* “Será una boda”.
* “Somos 40 personas”.
* “La fecha sería en diciembre”.
* “Queremos algo muy natural”.
* “Van 20 niños”.
* “Ya tenemos fotógrafo”.
* “Quiero cena y decoración”.
* “La fiesta será de noche”.

## 7.3 Ejemplos negativos

* “Quiero cotizar una boda”.

  * `QUOTE_REQUEST`.
* “Quiero ir a conocer”.

  * `SCHEDULE_VISIT`.
* “Ya no serán 40 sino 55”.

  * `MODIFY_EVENT_DATA`.

## 7.4 Entidades esperadas

```text
full_name
event_type
event_date
event_month
date_flexibility
guest_count
guest_count_min
guest_count_max
adult_guest_count
child_guest_count
infant_guest_count
estimated_budget
preferred_space
start_time
end_time
requested_services
special_requests
accessibility_requirements
dietary_requirements
pet_attendance
pool_use_expected
```

## 7.5 Acciones permitidas

```text
CREATE_OR_UPDATE_LEAD
CREATE_OR_UPDATE_EVENT
REGISTER_SERVICE_REQUESTS
UPDATE_PENDING_FIELDS
ASK_NEXT_MISSING_FIELD
```

## 7.6 Estado sugerido

```text
COLLECTING_EVENT_DATA
```

## 7.7 Confianza mínima

```text
0.70
```

## 7.8 Escalamiento

Cuando:

* evento especial no soportado;
* más de 60 personas;
* servicio complejo;
* solicitud contractual;
* dato crítico contradictorio.

---

# 8. QUOTE_REQUEST

## 8.1 Definición

El cliente solicita un precio, propuesta, cotización o información comercial personalizada.

## 8.2 Subintenciones

```text
GENERAL_PRICE_QUERY
PRICE_PER_PERSON_QUERY
CUSTOM_EVENT_QUOTE
QUOTE_STATUS_QUERY
QUOTE_CHANGE_REQUEST
```

---

## 8.3 GENERAL_PRICE_QUERY

### Ejemplos positivos

* “¿Cuánto cuesta?”
* “¿Qué precio tiene un evento?”
* “¿Cuánto vale alquilar?”
* “Mándame precios”.

### Acción

```text
COLLECT_MINIMUM_QUOTE_DATA
```

### Regla

No se genera precio automáticamente.

---

## 8.4 PRICE_PER_PERSON_QUERY

### Ejemplos positivos

* “¿Cuánto vale por persona?”
* “¿Qué precio manejan por invitado?”
* “¿Tienen tarifa por persona?”

### Acción

```text
ANSWER_CONDITIONAL_PRICE_POLICY
COLLECT_GUEST_COUNT
COLLECT_EVENT_TYPE
```

---

## 8.5 CUSTOM_EVENT_QUOTE

### Ejemplos positivos

* “Quiero cotizar una boda”.
* “Necesito una propuesta para 40 personas”.
* “Hazme una cotización para un cumpleaños”.
* “Quiero saber cuánto me saldría todo”.

### Entidades esperadas

* nombre;
* evento;
* fecha;
* invitados;
* presupuesto;
* servicios.

### Datos mínimos

```text
full_name
phone_number
event_type
date_resolved (fecha, mes, o tipo FLEXIBLE/UNKNOWN declarado)
total_guest_count OR guest_count_range
```

El silencio del cliente sobre la fecha no cuenta como `UNKNOWN`.

---

## 8.6 QUOTE_STATUS_QUERY

### Ejemplos positivos

* “¿Ya está mi cotización?”
* “¿Cuándo me envían la propuesta?”
* “Sigo esperando la cotización”.
* “¿Cómo va la propuesta?”

### Acción

```text
GET_QUOTE_REQUEST_STATUS
ANSWER_STATUS
CREATE_HANDOFF_IF_OVERDUE
```

### Escalamiento

Si está vencida o el cliente está molesto.

---

## 8.7 QUOTE_CHANGE_REQUEST

### Ejemplos positivos

* “Quiero quitar el DJ de la cotización”.
* “Agrega decoración”.
* “Cámbiala para 50 personas”.
* “Necesito otra versión”.

### Acción

```text
REGISTER_QUOTE_CHANGE_REQUEST
CREATE_NEW_QUOTE_VERSION_TASK
CREATE_HANDOFF
```

### Regla

La IA no modifica el valor directamente.

---

## 8.8 Acciones permitidas

```text
CREATE_OR_UPDATE_LEAD
COLLECT_MINIMUM_QUOTE_DATA
CREATE_QUOTE_REQUEST_DRAFT
CONFIRM_QUOTE_SUMMARY
CREATE_QUOTE_REQUEST
GET_QUOTE_STATUS
CREATE_HANDOFF
```

## 8.9 Acciones prohibidas

```text
CALCULATE_CUSTOM_PRICE
APPLY_DISCOUNT
APPROVE_QUOTE
NEGOTIATE
```

## 8.10 Estado sugerido

```text
COLLECTING_EVENT_DATA
QUOTE_REQUEST_READY
```

## 8.11 Confianza mínima

```text
0.78
```

## 8.12 Escalamiento

Obligatorio cuando:

* solicitud está lista;
* cliente pide descuento;
* cliente solicita negociación;
* cotización está vencida;
* requiere cambios después de enviada;
* evento supera capacidad;
* servicio depende de proveedor.

---

# 9. MODIFY_EVENT_DATA

## 9.1 Definición

El cliente corrige, agrega o elimina información previamente registrada.

## 9.2 Ejemplos positivos

* “No son 30, son 55”.
* “Cambiamos la fecha”.
* “Ya no quiero DJ”.
* “Finalmente será matrimonio civil”.
* “Seremos 20 adultos y 10 niños”.
* “No voy a llevar fotógrafo”.
* “El presupuesto subió a 8 millones”.

## 9.3 Entidades esperadas

* campo afectado;
* valor anterior;
* valor nuevo;
* motivo opcional.

## 9.4 Acciones permitidas

```text
VALIDATE_NEW_VALUE
UPDATE_EVENT_DATA
UPDATE_LEAD_DATA
REGISTER_CORRECTION
CREATE_AUDIT_EVENT
FLAG_QUOTE_REVERSION
FLAG_CAPACITY_REVIEW
```

## 9.5 Acciones restringidas

No actualizar automáticamente:

* fecha de evento reservado;
* precio de cotización enviada;
* reserva;
* pago;
* condiciones contractuales.

## 9.6 Confirmación

Requerida cuando:

* dato es crítico;
* la corrección es ambigua;
* afecta cita;
* afecta cotización;
* afecta reserva.

## 9.7 Confianza mínima

```text
0.80
```

## 9.8 Escalamiento

Cuando:

* evento ya está reservado;
* cambia fecha de reserva;
* aumenta a más de 60;
* requiere nueva cotización;
* afecta pago o condiciones.

---

# 10. SCHEDULE_VISIT

## 10.1 Definición

El cliente quiere conocer La Ceiba mediante una visita.

## 10.2 Ejemplos positivos

* “Quiero conocer el lugar”.
* “¿Puedo ir?”
* “Quiero agendar una visita”.
* “¿Tienen cita para el sábado?”
* “Quiero ver el espacio”.

## 10.3 Ejemplos negativos

* “¿Cuál es el horario de visitas?”

  * Puede ser `GENERAL_INFORMATION`.
* “Quiero cambiar mi visita”.

  * `RESCHEDULE_VISIT`.
* “Cancela mi cita”.

  * `CANCEL_VISIT`.

## 10.4 Entidades esperadas

```text
preferred_visit_date
preferred_visit_time
attendee_count
visit_reason
full_name
```

## 10.5 Acciones permitidas

```text
COLLECT_VISIT_DATA
VALIDATE_VISIT_DATE
CHECK_AVAILABILITY
OFFER_TIME_OPTIONS
REQUEST_CONFIRMATION
CREATE_APPOINTMENT
SCHEDULE_REMINDER
```

## 10.6 Validaciones

* martes a sábado;
* no festivo;
* mínimo tres días;
* horarios 8, 9, 10 u 11;
* máximo tres asistentes;
* máximo cuatro visitas diarias;
* disponibilidad real.

## 10.7 Confirmación obligatoria

Antes de crear.

## 10.8 Estado sugerido

```text
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED
```

## 10.9 Confianza mínima

```text
0.80
```

## 10.10 Escalamiento

Cuando:

* más de tres asistentes y solicita excepción;
* calendario falla;
* tercera inasistencia previa;
* requiere horario especial;
* solicita festivo;
* necesita visita urgente.

---

# 11. RESCHEDULE_VISIT

## 11.1 Definición

El cliente desea cambiar la fecha u hora de una visita existente.

## 11.2 Ejemplos positivos

* “Quiero cambiar mi cita”.
* “No puedo ir ese día”.
* “¿Podemos moverla?”
* “Pásala para el sábado”.
* “Necesito otra hora”.

## 11.3 Entidades esperadas

```text
appointment_reference
new_date
new_time
change_reason
```

## 11.4 Acciones permitidas

```text
FIND_ACTIVE_APPOINTMENT
CHECK_NEW_AVAILABILITY
REQUEST_RESCHEDULE_CONFIRMATION
RESCHEDULE_APPOINTMENT
RESCHEDULE_REMINDER
CREATE_APPOINTMENT_CHANGE
```

## 11.5 Confirmación obligatoria

Sí.

## 11.6 Confianza mínima

```text
0.82
```

## 11.7 Escalamiento

Cuando:

* no se identifica la cita;
* varias citas activas;
* calendario falla;
* solicita horario no permitido;
* reprogramaciones repetidas requieren revisión.

---

# 12. CANCEL_VISIT

## 12.1 Definición

El cliente desea cancelar una visita comercial.

## 12.2 Ejemplos positivos

* “Cancela mi visita”.
* “No voy a poder ir”.
* “Quiero cancelar la cita”.
* “Ya no necesito la visita”.

## 12.3 Ejemplos negativos

* “Quiero cancelar mi evento”.

  * `EVENT_CANCELLATION`.

## 12.4 Entidades esperadas

```text
appointment_reference
cancellation_reason
```

## 12.5 Acciones permitidas

```text
FIND_ACTIVE_APPOINTMENT
REQUEST_CANCELLATION_CONFIRMATION
CANCEL_APPOINTMENT
CANCEL_REMINDER
MARK_LATE_CANCEL
```

## 12.6 Confirmación obligatoria

Sí.

## 12.7 Confianza mínima

```text
0.85
```

## 12.8 Escalamiento

Solo cuando:

* no se identifica la cita;
* calendario falla;
* existe inconsistencia.

---

# 13. PAYMENT_MESSAGE

## 13.1 Definición

El cliente informa, consulta o envía información relacionada con un pago.

## 13.2 Subintenciones

```text
PAYMENT_METHOD_QUERY
PAYMENT_REPORTED
PAYMENT_PROOF_SENT
PAYMENT_STATUS_QUERY
PAYMENT_PROBLEM
```

---

## 13.3 PAYMENT_REPORTED

### Ejemplos positivos

* “Ya pagué”.
* “Hice la transferencia”.
* “Ya envié el dinero”.
* “Pagué el 50 %”.

### Acciones

```text
CREATE_OR_UPDATE_PAYMENT
MARK_PAYMENT_REVIEW
CREATE_URGENT_HANDOFF
```

---

## 13.4 PAYMENT_PROOF_SENT

### Ejemplos

* imagen de comprobante;
* documento bancario;
* captura de transferencia.

### Acción

```text
STORE_ATTACHMENT
CLASSIFY_AS_PAYMENT_PROOF
MARK_PAYMENT_REVIEW
CREATE_URGENT_HANDOFF
```

---

## 13.5 PAYMENT_STATUS_QUERY

### Ejemplos positivos

* “¿Ya confirmaron mi pago?”
* “¿Recibieron la transferencia?”
* “¿Ya quedó validado?”
* “¿Ya está reservado?”

### Acción

```text
GET_PAYMENT_STATUS
ANSWER_PAYMENT_REVIEW_STATUS
```

### Restricción

No inferir confirmación.

---

## 13.6 PAYMENT_PROBLEM

### Ejemplos positivos

* “El enlace no funciona”.
* “Me cobraron dos veces”.
* “Pagué y no aparece”.
* “El pago fue rechazado”.

### Prioridad

```text
URGENT
```

### Acción

```text
CREATE_URGENT_HANDOFF
PAUSE_AUTOMATION_IF_REQUIRED
```

---

## 13.7 Acciones prohibidas

```text
CONFIRM_PAYMENT
CONFIRM_RESERVATION
DECLARE_FUNDS_RECEIVED
```

La confirmación la realiza un asesor.

## 13.8 Confianza mínima

```text
0.85
```

## 13.9 Escalamiento

Siempre que se reporte o envíe un pago.

---

# 14. RESERVATION_INFORMATION

## 14.1 Definición

El cliente pregunta sobre la separación o reserva de la fecha.

## 14.2 Subintenciones

```text
DEPOSIT_PERCENTAGE_QUERY
DATE_HOLD_QUERY
RESERVATION_STATUS_QUERY
RESERVATION_PROCESS_QUERY
```

## 14.3 Ejemplos positivos

* “¿Con cuánto separo?”
* “¿Me guardan la fecha?”
* “¿Ya quedó reservada?”
* “¿Cómo reservo?”
* “¿La cotización bloquea la fecha?”

## 14.4 Entidades esperadas

* fecha;
* cotización;
* pago;
* evento.

## 14.5 Acciones permitidas

```text
ANSWER_DEPOSIT_POLICY
GET_RESERVATION_STATUS
ANSWER_RESERVATION_PROCESS
```

## 14.6 Regla

Separación:

```text
50 %
```

No hay bloqueo antes del pago validado.

## 14.7 Acciones prohibidas

```text
CREATE_RESERVATION_FROM_CHAT
CONFIRM_DATE_HOLD
CONFIRM_RESERVATION_WITHOUT_PAYMENT
```

## 14.8 Confianza mínima

```text
0.80
```

## 14.9 Escalamiento

Cuando:

* el cliente informa pago;
* solicita excepción;
* afirma inconsistencia;
* fecha aparece ocupada;
* se requiere confirmación.

---

# 15. EVENT_CANCELLATION

## 15.1 Definición

El cliente desea cancelar un evento o reserva, no una visita.

## 15.2 Ejemplos positivos

* “Quiero cancelar mi evento”.
* “No podremos realizar la boda”.
* “Necesito cancelar la reserva”.
* “Quiero que me devuelvan el dinero”.
* “Ya no vamos a hacer la celebración”.

## 15.3 Entidades esperadas

```text
event_reference
reservation_reference
event_date
cancellation_reason
refund_request
```

## 15.4 Acciones permitidas

```text
FIND_RESERVATION
CALCULATE_TIME_BEFORE_EVENT
MARK_CANCEL_REQUESTED
CREATE_HANDOFF
ANSWER_CANCELLATION_POLICY
```

## 15.5 Regla

Un mes o más:

* revisión humana.

Menos de un mes:

* no devolución;
* escalamiento obligatorio.

## 15.6 Acciones prohibidas

```text
APPROVE_REFUND
REJECT_EXCEPTION_FINALLY
CANCEL_RESERVATION_WITHOUT_HUMAN
TRANSFER_BALANCE
```

## 15.7 Prioridad

```text
URGENT
```

## 15.8 Confianza mínima

```text
0.88
```

## 15.9 Escalamiento

Siempre.

---

# 16. HUMAN_REQUEST

## 16.1 Definición

El cliente solicita explícitamente atención por una persona.

## 16.2 Ejemplos positivos

* “Quiero hablar con alguien”.
* “Pásame un asesor”.
* “Necesito atención humana”.
* “No quiero seguir con el bot”.
* “Comunícame con ventas”.
* “Quiero hablar con Leandro”.

## 16.3 Entidades posibles

* asesor solicitado;
* motivo;
* urgencia.

## 16.4 Acciones permitidas

```text
CREATE_HANDOFF
GENERATE_SUMMARY
SET_WAITING_FOR_HUMAN
NOTIFY_TEAM
```

## 16.5 Respuesta en horario

> Claro. Voy a compartir tu conversación con nuestro equipo para que un asesor continúe contigo.

## 16.6 Respuesta fuera de horario

> Tu solicitud quedó registrada. Un asesor continuará contigo dentro de nuestro horario de atención, de martes a sábado entre las 8:00 a. m. y las 4:00 p. m.

## 16.7 Confianza mínima

```text
0.75
```

## 16.8 Escalamiento

Siempre.

---

# 17. COMPLAINT

## 17.1 Definición

El cliente expresa molestia, inconformidad, incumplimiento o reclamación.

## 17.2 Ejemplos positivos

* “Estoy muy inconforme”.
* “Nadie me responde”.
* “Esto no fue lo acordado”.
* “Necesito una solución”.
* “Quiero poner una queja”.
* “Me parece una falta de respeto”.
* “El servicio fue pésimo”.

## 17.3 Entidades esperadas

```text
complaint_topic
event_reference
appointment_reference
payment_reference
requested_resolution
```

## 17.4 Acciones permitidas

```text
ACKNOWLEDGE_COMPLAINT
CREATE_URGENT_HANDOFF
GENERATE_SUMMARY
NOTIFY_MANAGER
PAUSE_BOT_ON_TAKEOVER
```

## 17.5 Respuesta base

> Lamentamos que estés pasando por esta situación. Queremos revisar tu caso con la atención que merece. Voy a trasladar la conversación a nuestro equipo responsable.

## 17.6 Acciones prohibidas

```text
ARGUE
DENY_FACTS
BLAME_CUSTOMER
PROMISE_COMPENSATION
PROMISE_REFUND
```

## 17.7 Prioridad

```text
URGENT
```

Puede elevarse a `CRITICAL`.

## 17.8 Confianza mínima

```text
0.72
```

Se prefiere sensibilidad alta para evitar no detectar quejas.

## 17.9 Escalamiento

Siempre.

---

# 18. EMERGENCY

## 18.1 Definición

El mensaje describe una situación inmediata que puede afectar seguridad, salud, acceso, operación crítica o reserva.

## 18.2 Subintenciones

```text
MEDICAL_EMERGENCY
SECURITY_INCIDENT
FOOD_SAFETY_INCIDENT
CLIENT_ON_SITE_UNATTENDED
ACCESS_PROBLEM
DOUBLE_BOOKING
CRITICAL_PAYMENT_ERROR
CRITICAL_RESERVATION_ERROR
EVENT_WITHIN_72_HOURS
```

## 18.3 Ejemplos positivos

* “Una persona se desmayó”.
* “Estoy en la puerta y nadie me atiende”.
* “Hay un problema de seguridad”.
* “Dos personas tenemos la misma fecha”.
* “Mi evento es mañana y nadie me responde”.
* “Confirmaron un pago que no era mío”.
* “La comida causó una reacción”.

## 18.4 Acciones permitidas

```text
CREATE_CRITICAL_HANDOFF
NOTIFY_MANAGER
NOTIFY_ON_SITE_TEAM
SEND_SAFE_EMERGENCY_RESPONSE
PAUSE_NORMAL_AUTOMATION
CREATE_ALERT
```

## 18.5 Respuesta para emergencia física

> Contacta inmediatamente al personal presente en La Ceiba y a los servicios de emergencia. Voy a alertar al equipo responsable ahora mismo.

## 18.6 Prioridad

```text
CRITICAL
```

Excepto evento dentro de 72 horas, que puede ser `URGENT`.

## 18.7 Confianza mínima

```text
0.60
```

Se utilizará umbral bajo para priorizar seguridad.

## 18.8 Escalamiento

Siempre e inmediato.

---

# 19. FAREWELL

## 19.1 Definición

El cliente indica que desea terminar o pausar la conversación.

## 19.2 Ejemplos positivos

* “Gracias”.
* “Era solo eso”.
* “Luego continúo”.
* “Hasta luego”.
* “Muchas gracias por la información”.
* “Después les escribo”.

## 19.3 Ejemplos negativos

* “Gracias, pero quiero cotizar”.

  * `QUOTE_REQUEST`.
* “Gracias, ya pagué”.

  * `PAYMENT_MESSAGE`.

## 19.4 Acciones permitidas

```text
SEND_FAREWELL
MARK_RESOLVED_IF_NO_PENDING_CRITICAL_ACTION
PRESERVE_PENDING_DATA
```

## 19.5 Respuesta base

> Con mucho gusto. Cuando quieras continuar o planear una celebración, estaremos encantados de ayudarte.

## 19.6 Estado sugerido

```text
RESOLVED
```

## 19.7 Confianza mínima

```text
0.75
```

---

# 20. UNKNOWN

## 20.1 Definición

No se puede determinar con suficiente confianza qué quiere el cliente.

## 20.2 Ejemplos

* texto ilegible;
* respuesta sin contexto;
* mensaje incompleto;
* contenido no relacionado;
* mezcla incoherente de temas.

## 20.3 Acciones permitidas

Primer fallo:

```text
ASK_CLARIFICATION_MENU
```

Segundo fallo:

```text
ASK_REPHRASE_OR_OFFER_HUMAN
```

Tercer fallo:

```text
CREATE_HANDOFF_LOW_CONFIDENCE
```

## 20.4 Respuestas

### Primer fallo

> Quiero asegurarme de entenderte bien. ¿Buscas información, solicitar una cotización, agendar una visita o hablar con un asesor?

### Segundo fallo

> Aún no logro identificar exactamente lo que necesitas. Puedes contármelo nuevamente con tus palabras o pedir que te comuniquemos con un asesor.

### Tercer fallo

> Voy a compartir tu conversación con nuestro equipo para que puedan ayudarte personalmente.

## 20.5 Estado

Puede permanecer en:

```text
BOT_ACTIVE
```

o pasar a:

```text
WAITING_FOR_HUMAN
```

## 20.6 Confianza

Por debajo del umbral general.

---

# 21. Intenciones contextuales de confirmación

Estas intenciones no deberán funcionar sin contexto.

```text
CONFIRM
DENY
SELECT_OPTION
CORRECT
CONTINUE
PAUSE
```

---

## 21.1 CONFIRM

### Ejemplos

* “Sí”.
* “Confirmo”.
* “Está correcto”.
* “Agéndala”.
* “Hazlo”.
* “De acuerdo”.

### Acción

Depende de `pending_action`.

Ejemplo:

```text
pending_action = CONFIRM_APPOINTMENT
```

Entonces `CONFIRM` permite solicitar al backend la creación.

---

## 21.2 DENY

### Ejemplos

* “No”.
* “No está bien”.
* “No quiero”.
* “Mejor no”.

### Acción

Cancelar o corregir la acción pendiente, sin asumir cancelación de una operación crítica.

---

## 21.3 SELECT_OPTION

### Ejemplos

* “La primera”.
* “La de las 9”.
* “El sábado”.
* “Esa opción”.

### Requisito

Debe existir una lista reciente de opciones.

---

## 21.4 CORRECT

### Ejemplos

* “No, son 50”.
* “La fecha correcta es el 19”.
* “Quise decir cumpleaños”.

Se mapea normalmente a `MODIFY_EVENT_DATA`.

---

# 22. Prioridad de clasificación

Cuando un mensaje coincida con varias intenciones, se utilizará este orden general:

```text
1. EMERGENCY
2. COMPLAINT
3. PAYMENT_MESSAGE
4. EVENT_CANCELLATION
5. HUMAN_REQUEST
6. CANCEL_VISIT
7. RESCHEDULE_VISIT
8. SCHEDULE_VISIT
9. MODIFY_EVENT_DATA
10. QUOTE_REQUEST
11. RESERVATION_INFORMATION
12. EVENT_INFORMATION
13. GENERAL_INFORMATION
14. FAREWELL
15. GREETING
16. UNKNOWN
```

La prioridad podrá ajustarse según el contexto.

---

# 23. Matriz de entidades por intención

| Intención                 | Entidades principales                            |
| ------------------------- | ------------------------------------------------ |
| `GREETING`                | nombre, idioma                                   |
| `GENERAL_INFORMATION`     | categoría, espacio, invitados, servicio          |
| `EVENT_INFORMATION`       | evento, fecha, invitados, presupuesto, servicios |
| `QUOTE_REQUEST`           | nombre, evento, fecha, invitados, presupuesto    |
| `MODIFY_EVENT_DATA`       | campo, valor nuevo, valor anterior               |
| `SCHEDULE_VISIT`          | fecha, hora, asistentes, motivo                  |
| `RESCHEDULE_VISIT`        | cita, fecha nueva, hora nueva                    |
| `CANCEL_VISIT`            | cita, motivo                                     |
| `PAYMENT_MESSAGE`         | método, monto, referencia, comprobante           |
| `RESERVATION_INFORMATION` | evento, fecha, cotización, estado                |
| `EVENT_CANCELLATION`      | reserva, fecha, motivo, devolución               |
| `HUMAN_REQUEST`           | asesor, motivo                                   |
| `COMPLAINT`               | tema, referencia, solución solicitada            |
| `EMERGENCY`               | tipo, ubicación, evento, gravedad                |
| `FAREWELL`                | ninguno                                          |
| `UNKNOWN`                 | ninguno confirmado                               |

---

# 24. Matriz de acciones permitidas

| Intención                 | Puede consultar |          Puede modificar |        Requiere confirmación |   Requiere humano |
| ------------------------- | --------------: | -----------------------: | ---------------------------: | ----------------: |
| `GREETING`                |              No |             Conversación |                           No |                No |
| `GENERAL_INFORMATION`     |              Sí |         Datos opcionales |                           No |       Condicional |
| `EVENT_INFORMATION`       |              Sí |              Lead/evento |                  Condicional |       Condicional |
| `QUOTE_REQUEST`           |              Sí |           Solicitud/lead | Sí, antes de crear solicitud |   Sí al completar |
| `MODIFY_EVENT_DATA`       |              Sí |              Evento/lead |                   Según dato |       Condicional |
| `SCHEDULE_VISIT`          |          Agenda |                     Cita |                           Sí |       Condicional |
| `RESCHEDULE_VISIT`        |          Agenda |                     Cita |                           Sí |       Condicional |
| `CANCEL_VISIT`            |            Cita |                     Cita |                           Sí |        Solo error |
| `PAYMENT_MESSAGE`         |            Pago |       Estado de revisión |            No para registrar |                Sí |
| `RESERVATION_INFORMATION` |         Reserva |               No crítica |                           No |       Condicional |
| `EVENT_CANCELLATION`      |         Reserva | Solicitud de cancelación |                           Sí |                Sí |
| `HUMAN_REQUEST`           |              No |                  Handoff |                           No |                Sí |
| `COMPLAINT`               |        Contexto |                  Handoff |                           No |                Sí |
| `EMERGENCY`               |        Contexto |           Alerta/handoff |                           No |                Sí |
| `FAREWELL`                |              No |             Conversación |                           No |                No |
| `UNKNOWN`                 |              No |       Contador de fallos |                           No | Después de fallos |

---

# 25. Umbrales de confianza

## 25.1 Clasificación segura

```text
confidence >= 0.85
```

El sistema puede continuar con la acción permitida, siempre sometida a validación.

## 25.2 Clasificación probable

```text
0.70 <= confidence < 0.85
```

El sistema podrá:

* continuar en acciones no críticas;
* solicitar confirmación;
* evitar ejecutar acciones irreversibles.

## 25.3 Clasificación incierta

```text
0.50 <= confidence < 0.70
```

El sistema deberá:

* pedir aclaración;
* presentar opciones;
* no ejecutar acciones críticas.

### Rescate acotado de `event_type` en posición dirigida

Antes de aplicar la aclaración de la banda incierta, el backend podrá promover
determinísticamente la clasificación a `EVENT_INFORMATION` solo cuando se cumplan todas
estas guardas:

* la intención original es exactamente `EVENT_INFORMATION`;
* `0.50 <= confidence < 0.70`, según los umbrales configurados;
* `last_question_code` pertenece a `EVENT_TYPE_QUESTION_CODES`;
* existe una entidad `event_type` con `quality_status` igual a `PROVIDED` o `CORRECTED`;
* la entidad no requiere confirmación;
* la confianza de la entidad es mayor o igual a `AI_CONFIDENCE_SAFE`;
* el valor de la entidad normaliza a un tipo de evento válido.

La clasificación promovida contiene únicamente la entidad rescatada y usa
`reasoning_code = UNCERTAIN_ENTITY_RESCUE`. `INFERRED`, `PENDING_CONFIRMATION`, una
intención sensible, una posición no dirigida o una entidad no normalizable conservan sin
cambios el régimen general de confianza. La decisión del backend se audita por separado;
la fila `ai_execution` conserva el veredicto literal del modelo.

## 25.4 Confianza insuficiente

```text
confidence < 0.50
```

Resultado:

```text
intent = UNKNOWN
```

## 25.5 Excepción de seguridad

Para `EMERGENCY` y `COMPLAINT`, podrán utilizarse umbrales inferiores para evitar omitir situaciones relevantes.

---

# 26. Reglas de confirmación

Se deberá solicitar confirmación antes de:

```text
CREATE_APPOINTMENT
RESCHEDULE_APPOINTMENT
CANCEL_APPOINTMENT
CREATE_READY_QUOTE_REQUEST
APPLY_CRITICAL_EVENT_DATA_CHANGE
REQUEST_EVENT_CANCELLATION
```

La confirmación deberá incluir los datos relevantes.

Ejemplo:

> Confirmemos tu visita: sábado 8 de agosto a las 9:00 a. m., para dos personas. ¿Deseas que la agendemos?

---

# 27. Reglas de escalamiento por intención

## Escalamiento obligatorio

```text
PAYMENT_MESSAGE
EVENT_CANCELLATION
HUMAN_REQUEST
COMPLAINT
EMERGENCY
```

## Escalamiento al completar flujo

```text
QUOTE_REQUEST
```

## Escalamiento condicional

```text
GENERAL_INFORMATION
EVENT_INFORMATION
MODIFY_EVENT_DATA
SCHEDULE_VISIT
RESCHEDULE_VISIT
CANCEL_VISIT
RESERVATION_INFORMATION
```

---

# 28. Motivos de handoff relacionados

| Intención                 | Motivo de handoff                     |
| ------------------------- | ------------------------------------- |
| `QUOTE_REQUEST`           | `QUOTE_PREPARATION`                   |
| `MODIFY_EVENT_DATA`       | `QUOTE_PREPARATION` o `SPECIAL_EVENT` |
| `SCHEDULE_VISIT`          | `SYSTEM_ERROR` o `SPECIAL_EVENT`      |
| `RESCHEDULE_VISIT`        | `SYSTEM_ERROR`                        |
| `CANCEL_VISIT`            | `SYSTEM_ERROR`                        |
| `PAYMENT_MESSAGE`         | `PAYMENT_REVIEW`                      |
| `RESERVATION_INFORMATION` | `RESERVATION_CONFIRMATION`            |
| `EVENT_CANCELLATION`      | `CANCELLATION`                        |
| `HUMAN_REQUEST`           | `CUSTOMER_REQUEST`                    |
| `COMPLAINT`               | `COMPLAINT`                           |
| `EMERGENCY`               | `URGENT_EVENT`                        |
| `UNKNOWN`                 | `LOW_CONFIDENCE`                      |

---

# 29. Intenciones y estados conversacionales

| Intención                 | Estado inicial posible | Estado resultante                   |
| ------------------------- | ---------------------- | ----------------------------------- |
| `GREETING`                | `NEW`                  | `BOT_ACTIVE`                        |
| `GENERAL_INFORMATION`     | `BOT_ACTIVE`           | `ANSWERING_INFORMATION`             |
| `EVENT_INFORMATION`       | `BOT_ACTIVE`           | `COLLECTING_EVENT_DATA`             |
| `QUOTE_REQUEST`           | `BOT_ACTIVE`           | `COLLECTING_EVENT_DATA`             |
| `MODIFY_EVENT_DATA`       | Cualquiera comercial   | Se conserva o actualiza             |
| `SCHEDULE_VISIT`          | `BOT_ACTIVE`           | `WAITING_FOR_APPOINTMENT_DATE`      |
| `RESCHEDULE_VISIT`        | `BOT_ACTIVE`           | `WAITING_FOR_APPOINTMENT_SELECTION` |
| `CANCEL_VISIT`            | `BOT_ACTIVE`           | `APPOINTMENT_PENDING_CONFIRMATION`  |
| `PAYMENT_MESSAGE`         | Cualquiera             | `WAITING_FOR_HUMAN`                 |
| `RESERVATION_INFORMATION` | Cualquiera             | `ANSWERING_INFORMATION`             |
| `EVENT_CANCELLATION`      | Cualquiera             | `WAITING_FOR_HUMAN`                 |
| `HUMAN_REQUEST`           | Cualquiera             | `WAITING_FOR_HUMAN`                 |
| `COMPLAINT`               | Cualquiera             | `WAITING_FOR_HUMAN`                 |
| `EMERGENCY`               | Cualquiera             | `WAITING_FOR_HUMAN`                 |
| `FAREWELL`                | Sin pendientes         | `RESOLVED`                          |
| `UNKNOWN`                 | Cualquiera             | Se conserva o escala                |

---

# 30. Casos de múltiples intenciones

## Caso A — Cotización y visita

Mensaje:

> Quiero cotizar una boda para 30 personas y también ir mañana.

Resultado:

```json
{
  "primary_intent": "QUOTE_REQUEST",
  "secondary_intents": [
    "SCHEDULE_VISIT"
  ],
  "entities": {
    "event_type": "WEDDING",
    "guest_count": 30,
    "relative_visit_date": "TOMORROW"
  }
}
```

El bot deberá:

1. registrar evento e invitados;
2. informar que la visita requiere tres días;
3. solicitar una fecha válida;
4. conservar pendiente la cotización.

---

## Caso B — Pago y queja

Mensaje:

> Ya pagué y nadie me confirma.

Resultado:

```json
{
  "primary_intent": "COMPLAINT",
  "secondary_intents": [
    "PAYMENT_MESSAGE"
  ],
  "priority": "URGENT",
  "needs_human": true
}
```

---

## Caso C — Ubicación y precio

Mensaje:

> ¿Dónde están y cuánto cuesta una boda?

Resultado:

```json
{
  "primary_intent": "QUOTE_REQUEST",
  "secondary_intents": [
    "GENERAL_INFORMATION"
  ],
  "sub_intent": "CUSTOM_EVENT_QUOTE"
}
```

El bot responde ubicación e inicia captura comercial.

---

# 31. Ejemplos de clasificación negativa

## Ejemplo 1

Mensaje:

> “¿La piscina está incluida?”

No clasificar como:

```text
EVENT_INFORMATION
```

Clasificar como:

```text
GENERAL_INFORMATION / POOL
```

---

## Ejemplo 2

Mensaje:

> “Ya no quiero piscina”.

Si existe evento activo:

```text
MODIFY_EVENT_DATA
```

---

## Ejemplo 3

Mensaje:

> “Quiero hablar del precio”.

Si el contexto indica negociación:

```text
HUMAN_REQUEST
```

o:

```text
QUOTE_REQUEST / QUOTE_CHANGE_REQUEST
```

No clasificar automáticamente como simple FAQ.

---

## Ejemplo 4

Mensaje:

> “No puedo ir”.

Si existe visita activa:

```text
CANCEL_VISIT
```

Si existe evento reservado y se refiere al evento:

```text
EVENT_CANCELLATION
```

Debe utilizarse contexto.

---

# 32. Reglas para mensajes multimedia

## Imagen sin texto

Clasificación inicial:

```text
UNKNOWN
```

El contexto podrá permitir:

* `PAYMENT_MESSAGE`, si existe pago pendiente;
* `EVENT_INFORMATION`, si se pidió referencia;
* `QUOTE_REQUEST`, si forma parte de una solicitud.

## Comprobante

```text
PAYMENT_MESSAGE / PAYMENT_PROOF_SENT
```

## Imagen de decoración

```text
EVENT_INFORMATION
```

Entidad:

```text
inspiration_reference = true
```

## Audio

Si no hay transcripción:

* no clasificar contenido;
* solicitar texto o escalar.

---

# 33. Reglas para fecha y tiempo

Las intenciones relacionadas con fechas deberán extraer:

```text
raw_date_expression
resolved_date
timezone
needs_confirmation
```

Ejemplo:

> “El próximo sábado”.

Salida:

```json
{
  "raw_date_expression": "el próximo sábado",
  "resolved_date": "2026-08-08",
  "timezone": "America/Bogota",
  "needs_confirmation": true
}
```

El bot deberá preguntar:

> ¿Te refieres al sábado 8 de agosto de 2026?

---

# 34. Métricas de intenciones

El sistema deberá medir:

* cantidad por intención;
* confianza promedio;
* tasa de corrección;
* tasa de fallback;
* tasa de handoff;
* mensajes con múltiples intenciones;
* errores por intención;
* precisión por categoría;
* entidades faltantes;
* clasificación humana corregida;
* intenciones desconocidas frecuentes.

---

# 35. Dataset mínimo de evaluación

El conjunto de pruebas deberá incluir por intención:

* 20 ejemplos directos;
* 10 ejemplos informales;
* 10 ejemplos con errores ortográficos;
* 10 ejemplos ambiguos;
* 5 ejemplos negativos;
* 5 ejemplos con múltiples intenciones.

Para intenciones críticas:

```text
PAYMENT_MESSAGE
EVENT_CANCELLATION
COMPLAINT
EMERGENCY
```

se recomienda mínimo 50 ejemplos por intención.

---

# 36. Criterios de aceptación

El catálogo se considerará correctamente implementado cuando:

1. Solo se devuelvan intenciones permitidas.
2. Las salidas cumplan el esquema.
3. Las intenciones críticas tengan prioridad.
4. Los mensajes breves utilicen contexto.
5. Las acciones prohibidas no sean ejecutadas.
6. Las fechas relativas requieran confirmación.
7. Las solicitudes múltiples conserven intenciones secundarias.
8. Los datos extraídos tengan estado de calidad.
9. El bot solicite aclaración con baja confianza.
10. El tercer fallo produzca handoff.
11. Los pagos siempre escalen.
12. Las cancelaciones de eventos siempre escalen.
13. Las quejas tengan prioridad urgente.
14. Las emergencias generen alerta crítica.
15. La IA no invente categorías.
16. Las FAQ puedan resolverse sin IA.
17. Los cambios de datos sean diferenciados de datos nuevos.
18. El bot no confunda cancelación de visita con cancelación de evento.
19. La clasificación sea auditable.
20. Las correcciones humanas puedan alimentar pruebas futuras.

---

# 37. Contrato de clasificación recomendado

```json
{
  "primary_intent": "string",
  "secondary_intents": [
    "string"
  ],
  "sub_intent": "string|null",
  "confidence": 0.0,
  "entities": {},
  "requested_action": "string|null",
  "missing_fields": [
    "string"
  ],
  "needs_confirmation": false,
  "needs_human": false,
  "handoff_reason": "string|null",
  "priority": "NORMAL",
  "context_reference": {
    "pending_action": "string|null",
    "last_question_code": "string|null"
  },
  "reasoning_code": "string"
}
```

## Restricciones

* `primary_intent` debe pertenecer al catálogo.
* `confidence` debe estar entre 0 y 1.
* `priority` debe pertenecer al catálogo.
* `requested_action` debe estar autorizada para la intención.
* `handoff_reason` es obligatorio si `needs_human = true`.
* No debe incluir explicación libre del razonamiento interno.
* Las entidades deben cumplir sus esquemas.

---

# 38. Versionado del catálogo

Toda modificación deberá registrar:

* intención agregada, modificada o desactivada;
* motivo;
* ejemplos;
* acciones afectadas;
* estados afectados;
* pruebas actualizadas;
* versión;
* responsable;
* fecha de vigencia.

Las intenciones eliminadas deberán conservarse como:

```text
INACTIVE
```

para mantener trazabilidad histórica.

---

# 39. Definición de terminado

La implementación del catálogo estará terminada cuando:

* exista el esquema JSON;
* existan validadores;
* existan prompts versionados;
* exista dataset de evaluación;
* existan pruebas por intención;
* existan pruebas de múltiples intenciones;
* existan pruebas de contexto;
* existan umbrales configurables;
* existan métricas;
* exista fallback;
* exista handoff por baja confianza;
* las intenciones críticas sean detectadas;
* el backend valide todas las acciones;
* las correcciones humanas queden registradas.

---

# 40. Aprobación

Este documento queda listo como fuente oficial para:

* diseño de prompts;
* clasificación;
* extracción de entidades;
* máquina de estados;
* orquestador;
* contratos con OpenRouter;
* pruebas conversacionales;
* métricas de calidad;
* reglas de escalamiento.

Su aprobación implica que:

* el catálogo principal está delimitado;
* las subintenciones están definidas;
* las acciones permitidas y prohibidas están separadas;
* los umbrales están establecidos;
* las intenciones críticas tienen prioridad;
* el MVP puede implementar clasificación controlada;
* la futura cotización automática podrá añadirse sin cambiar la taxonomía principal.
