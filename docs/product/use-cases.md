# Casos de uso del producto

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/product/use-cases.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Zona horaria oficial:** `America/Bogota`

**Documentos relacionados:**

* `/docs/product/vision.md`
* `/docs/product/scope.md`
* `/docs/product/business-rules.md`

---

# 1. Propósito

Este documento describe los casos de uso funcionales del MVP del Asistente Conversacional de La Ceiba Club House.

Cada caso define:

* objetivo;
* actores;
* disparador;
* precondiciones;
* datos de entrada;
* flujo principal;
* flujos alternativos;
* excepciones;
* datos modificados;
* reglas de negocio;
* resultado esperado;
* criterios de aceptación.

Los casos de uso deberán servir como base para:

* requerimientos funcionales;
* diseño de arquitectura;
* diseño del modelo de datos;
* creación de servicios;
* implementación del orquestador;
* construcción del panel administrativo;
* pruebas unitarias;
* pruebas de integración;
* pruebas conversacionales;
* pruebas end-to-end.

---

# 2. Convenciones

## 2.1 Identificación

Cada caso de uso tendrá el formato:

```text
UC-XXX
```

Ejemplo:

```text
UC-001 — Iniciar conversación
```

## 2.2 Actores

### Cliente

Persona que se comunica con La Ceiba por WhatsApp.

### Bot

Componente conversacional que interpreta mensajes, solicita datos y redacta respuestas.

### Orquestador conversacional

Componente que controla:

* estado;
* intención;
* acción pendiente;
* servicios permitidos;
* validaciones.

### Backend

Conjunto de servicios de dominio que ejecuta las operaciones.

### Asesor

Persona que atiende conversaciones comerciales, prepara cotizaciones y valida pagos.

### Business Manager

Persona que atiende visitas.

### Manager Leandro

Responsable general de escalaciones, excepciones y casos especiales.

### Administrador

Usuario autorizado para modificar configuraciones y contenidos.

### Proveedor de WhatsApp

Servicio externo que recibe y envía mensajes.

### Proveedor de calendario

Servicio externo utilizado para consultar y registrar visitas.

### OpenRouter

Proveedor utilizado para acceder a modelos de lenguaje.

---

# 3. Estados principales

## 3.1 Estados de conversación

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

## 3.2 Estados del lead

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

## 3.3 Estados de visita

```text
PENDING_CONFIRMATION
CONFIRMED
RESCHEDULED
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

## 3.4 Estados de pago

```text
PAYMENT_PENDING
PAYMENT_REVIEW
PAYMENT_CONFIRMED
PAYMENT_REJECTED
PAYMENT_CANCELLED
```

## 3.5 Estados de reserva

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

---

# 4. Catálogo de casos de uso

| ID     | Caso de uso                        | Actor principal  |
| ------ | ---------------------------------- | ---------------- |
| UC-001 | Iniciar o recuperar conversación   | Cliente          |
| UC-002 | Responder pregunta frecuente       | Cliente          |
| UC-003 | Registrar cliente potencial        | Bot              |
| UC-004 | Crear o actualizar lead            | Bot              |
| UC-005 | Identificar tipo de evento         | Bot              |
| UC-006 | Recopilar datos del evento         | Bot              |
| UC-007 | Corregir datos del evento          | Cliente          |
| UC-008 | Gestionar cambio temporal de tema  | Cliente          |
| UC-009 | Crear solicitud de cotización      | Cliente          |
| UC-010 | Asignar solicitud de cotización    | Asesor           |
| UC-011 | Registrar cotización humana        | Asesor           |
| UC-012 | Crear nueva versión de cotización  | Asesor           |
| UC-013 | Consultar disponibilidad de visita | Cliente          |
| UC-014 | Agendar visita                     | Cliente          |
| UC-015 | Reprogramar visita                 | Cliente          |
| UC-016 | Cancelar visita                    | Cliente          |
| UC-017 | Enviar recordatorio de visita      | Sistema          |
| UC-018 | Registrar inasistencia             | Business Manager |
| UC-019 | Solicitar atención humana          | Cliente          |
| UC-020 | Tomar conversación escalada        | Asesor           |
| UC-021 | Devolver conversación al bot       | Asesor           |
| UC-022 | Gestionar queja                    | Cliente          |
| UC-023 | Registrar información de pago      | Cliente          |
| UC-024 | Confirmar pago                     | Asesor           |
| UC-025 | Confirmar reserva de fecha         | Asesor           |
| UC-026 | Solicitar cancelación de evento    | Cliente          |
| UC-027 | Gestionar caso urgente             | Cliente          |
| UC-028 | Gestionar mensaje duplicado        | Sistema          |
| UC-029 | Gestionar fallo de IA              | Sistema          |
| UC-030 | Gestionar fallo de calendario      | Sistema          |
| UC-031 | Actualizar base de conocimiento    | Administrador    |
| UC-032 | Cerrar conversación                | Bot o asesor     |

---

# 5. UC-001 — Iniciar o recuperar conversación

## Objetivo

Crear una conversación nueva o recuperar una conversación activa cuando un cliente envía un mensaje por WhatsApp.

## Actor principal

Cliente.

## Actores secundarios

* Proveedor de WhatsApp.
* Orquestador conversacional.
* Backend.

## Disparador

El proveedor de WhatsApp envía un webhook con un mensaje entrante.

## Precondiciones

* El webhook es válido.
* El identificador externo del mensaje no ha sido procesado.
* El canal se encuentra activo.

## Datos de entrada

* número de teléfono;
* identificador externo del mensaje;
* fecha y hora;
* tipo de mensaje;
* contenido;
* cuenta receptora;
* metadatos del proveedor.

## Flujo principal

1. El proveedor envía el evento.
2. El sistema valida la firma y estructura.
3. El sistema verifica que el mensaje no esté duplicado.
4. El sistema normaliza el número telefónico.
5. El sistema busca un cliente existente.
6. Si no existe, crea un cliente provisional.
7. El sistema busca una conversación activa.
8. Si existe, la recupera.
9. Si no existe, crea una conversación.
10. Guarda el mensaje entrante.
11. Establece o conserva el estado correspondiente.
12. Envía el mensaje al orquestador.
13. El orquestador interpreta la intención.
14. El sistema continúa con el caso de uso correspondiente.

## Flujo alternativo A — Cliente con conversación resuelta

1. El sistema encuentra una conversación en estado `RESOLVED`.
2. Evalúa el tiempo transcurrido.
3. Puede reabrirla o crear una nueva conversación.
4. Conserva los leads existentes.

## Flujo alternativo B — Cliente con varios leads

1. El sistema identifica varios leads activos.
2. No asume cuál desea continuar.
3. Solicita aclaración cuando sea necesario.

## Excepciones

### Mensaje duplicado

Se ejecuta UC-028.

### Webhook inválido

* rechazar el evento;
* registrar intento;
* no crear conversación;
* no enviar respuesta.

### Error de persistencia

* registrar error;
* evitar respuesta no trazable;
* enviar a reintento seguro.

## Datos modificados

* `Customer`;
* `Conversation`;
* `Message`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CUS-001.
* BR-CUS-002.
* BR-CON-008.
* BR-SEC-006.
* BR-SEC-007.
* BR-AUD-003.

## Resultado esperado

Existe una conversación activa y el mensaje quedó almacenado una sola vez.

## Criterios de aceptación

* No se duplica el cliente por el mismo número.
* No se duplica el mensaje.
* Se recupera el contexto cuando existe.
* Se conserva el canal de origen.
* El mensaje queda disponible para auditoría.

---

# 6. UC-002 — Responder pregunta frecuente

## Objetivo

Responder una consulta informativa utilizando contenido aprobado.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Orquestador.
* Base de conocimiento.

## Disparador

El cliente realiza una pregunta sobre La Ceiba.

## Ejemplos

* ubicación;
* capacidad;
* parqueadero;
* piscina;
* mascotas;
* proveedores;
* alimentos;
* licor;
* alojamiento;
* horarios;
* visitas;
* reservas.

## Precondiciones

* Conversación activa.
* Existe una respuesta aprobada o una política de fallback.
* La pregunta no requiere decisión humana.

## Flujo principal

1. El orquestador identifica la intención `GENERAL_INFORMATION`.
2. Detecta la categoría.
3. Consulta la base de conocimiento.
4. Recupera la respuesta en estado `APPROVED`.
5. Adapta el tono sin modificar el significado.
6. Envía la respuesta.
7. Registra la respuesta enviada.
8. Pregunta de forma opcional si existe interés en un evento.
9. Si no hay continuidad, marca la conversación como resuelta.

## Flujo alternativo A — Pregunta durante otro flujo

1. El sistema responde la pregunta.
2. Conserva `pending_action`.
3. Retoma el flujo anterior.

## Flujo alternativo B — Varias preguntas

1. El sistema identifica varias categorías.
2. Responde las que tengan información aprobada.
3. Evita generar un bloque excesivo.
4. Puede dividir la respuesta en varios mensajes.

## Excepciones

### No existe respuesta aprobada

* no improvisar;
* indicar que el equipo debe confirmar;
* escalar si es relevante.

### OpenRouter no disponible

La respuesta podrá enviarse de manera determinista desde la base de conocimiento.

## Datos modificados

* `Message`;
* `Conversation.current_intent`;
* `Conversation.last_message_at`;
* métricas de conocimiento.

## Reglas relacionadas

* BR-KB-001 a BR-KB-016.
* BR-CON-003.
* BR-AI-007.

## Resultado esperado

El cliente recibe información correcta, breve y autorizada.

## Criterios de aceptación

* La respuesta coincide con la versión aprobada.
* No se inventan datos.
* Se conserva el flujo anterior.
* La FAQ funciona aunque la IA falle.

---

# 7. UC-003 — Registrar cliente potencial

## Objetivo

Completar la información básica de un cliente que demuestra interés comercial.

## Actor principal

Bot.

## Actor secundario

Cliente.

## Disparador

El cliente manifiesta interés en:

* cotizar;
* visitar;
* reservar;
* conocer un servicio;
* planear un evento.

## Precondiciones

* Existe conversación activa.
* Existe cliente provisional o confirmado.

## Flujo principal

1. El sistema identifica intención comercial.
2. Verifica qué datos ya existen.
3. Solicita el nombre si todavía no está confirmado.
4. Registra el nombre.
5. Conserva el teléfono del canal.
6. Registra idioma y canal.
7. Actualiza la fecha de último contacto.
8. Crea o relaciona el lead correspondiente.

## Flujo alternativo — Cliente no proporciona nombre

1. El bot continúa con información básica.
2. Mantiene el nombre pendiente.
3. Lo solicita antes de una operación que lo requiera.

## Excepciones

### Nombre ambiguo

El bot puede confirmar:

> ¿Con quién tenemos el gusto?

### Posible cliente duplicado

El sistema marca el perfil para revisión, sin fusionar automáticamente.

## Datos modificados

* `Customer.full_name`;
* `Customer.updated_at`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CUS-003.
* BR-CUS-004.
* BR-CUS-008.
* BR-LEAD-001.

## Resultado esperado

El cliente queda identificado para continuar el proceso comercial.

## Criterios de aceptación

* El nombre no se vuelve a preguntar si está confirmado.
* El cliente puede continuar sin correo.
* Se conserva la relación entre cliente y lead.

---

# 8. UC-004 — Crear o actualizar lead

## Objetivo

Registrar una oportunidad comercial asociada a un evento específico.

## Actor principal

Bot.

## Actores secundarios

* Cliente.
* Asesor.

## Disparador

El cliente expresa intención comercial relacionada con un evento.

## Precondiciones

* Cliente identificado.
* Conversación activa.
* Se ha detectado una intención comercial.

## Flujo principal

1. El sistema busca un lead compatible.
2. Si existe, lo recupera.
3. Si no existe, crea uno nuevo.
4. Registra el canal.
5. Registra el tipo de evento cuando se conozca.
6. Registra fecha, invitados y presupuesto cuando se conozcan.
7. Establece estado `NEW` o `QUALIFYING`.
8. Registra siguiente acción.
9. Relaciona el lead con la conversación.

## Flujo alternativo A — Cliente tiene otro evento

1. El sistema detecta que se trata de un evento diferente.
2. Crea un nuevo lead.
3. No modifica el anterior.

## Flujo alternativo B — Cliente quiere retomar

1. Identifica el lead.
2. Recupera datos y campos faltantes.
3. Continúa desde el último punto.

## Excepciones

### No se puede identificar el evento

El lead puede permanecer en `NEW` con información mínima.

## Datos modificados

* `Lead`;
* `Conversation.lead_id`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CUS-007.
* BR-LEAD-001.
* BR-LEAD-002.
* BR-LEAD-003.

## Resultado esperado

Existe un lead separado para cada oportunidad comercial.

## Criterios de aceptación

* Un cliente puede tener varios leads.
* No se sobrescribe un evento anterior.
* Se conserva el estado comercial.

---

# 9. UC-005 — Identificar tipo de evento

## Objetivo

Clasificar el tipo de celebración o experiencia.

## Actor principal

Bot.

## Disparador

El cliente describe el evento.

## Precondiciones

* Conversación activa.
* Mensaje procesable.

## Flujo principal

1. La IA analiza el mensaje.
2. Devuelve una intención y tipo estructurado.
3. El backend valida que el tipo pertenezca al catálogo.
4. Registra el valor como `PROVIDED` o `INFERRED`.
5. Si es necesario, solicita confirmación.
6. Actualiza el evento y el lead.

## Tipos admitidos

```text
WEDDING
CIVIL_WEDDING
PROPOSAL
BIRTHDAY
GRADUATION
ANNIVERSARY
ROMANTIC_DINNER
CORPORATE_EVENT
FAMILY_EVENT
BAPTISM
FIRST_COMMUNION
BABY_SHOWER
WORKSHOP
POOL_DAY
PRIVATE_DINNER
OTHER
```

## Flujo alternativo — Evento especial

1. Se registra `OTHER`.
2. Se guarda la descripción.
3. Se puede escalar para revisión.

## Excepciones

### Baja confianza

El bot pregunta:

> ¿Se trata de una celebración social, familiar, romántica o empresarial?

## Datos modificados

* `Event.event_type`;
* `Event.event_type_other`;
* `Lead`;
* `AIExecution`;
* `AuditEvent`.

## Reglas relacionadas

* BR-EVT-001.
* BR-EVT-002.
* BR-AI-003.
* BR-AI-004.

## Resultado esperado

El tipo de evento queda registrado o pendiente de confirmación.

## Criterios de aceptación

* No se inventa una categoría fuera del catálogo.
* Los eventos especiales conservan una descripción.
* La baja confianza no genera una acción crítica.

---

# 10. UC-006 — Recopilar datos del evento

## Objetivo

Obtener progresivamente la información necesaria para cotizar o atender el evento.

## Actor principal

Bot.

## Actor secundario

Cliente.

## Disparador

El cliente solicita una cotización o manifiesta interés comercial.

## Precondiciones

* Cliente identificado.
* Lead activo.
* Evento creado.

## Datos principales

* tipo de evento;
* fecha;
* cantidad de invitados;
* presupuesto;
* horario;
* espacio;
* gastronomía;
* bebidas;
* decoración;
* servicios;
* observaciones.

## Flujo principal

1. El sistema revisa los datos ya existentes.
2. Identifica campos obligatorios faltantes.
3. Prioriza tipo de evento e invitados.
4. Solicita la fecha.
5. Solicita el nombre si falta.
6. Solicita presupuesto de forma preferible.
7. Solicita servicios deseados.
8. Registra cada respuesta.
9. Actualiza el estado de calidad de cada dato.
10. Evita repetir preguntas.
11. Cuando están completos los mínimos, propone confirmar la solicitud.

## Orden recomendado

1. Tipo de evento.
2. Invitados.
3. Fecha.
4. Nombre.
5. Presupuesto.
6. Servicios.
7. Observaciones.

Este orden no será rígido.

## Flujo alternativo A — Datos múltiples

Si el cliente entrega varios datos, todos se registran.

## Flujo alternativo B — Presupuesto no informado

El flujo continúa sin bloquearse.

## Flujo alternativo C — Invitados como rango

Se registra mínimo, máximo y estado estimado.

## Flujo alternativo D — Fecha aproximada

Se guarda mes o periodo, sin inventar día.

## Excepciones

### Fecha ambigua

Debe confirmarse en formato absoluto.

### Más de 60 invitados

Se activa revisión de capacidad.

### Servicios no disponibles automáticamente

Se marcan `PENDING_CONFIRMATION`.

## Datos modificados

* `Event`;
* `Lead`;
* `ServiceRequest`;
* `Conversation.pending_fields`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CON-001.
* BR-CON-002.
* BR-LEAD-004 a BR-LEAD-009.
* BR-EVT-003 a BR-EVT-016.
* BR-QREQ-002.
* BR-QREQ-003.

## Resultado esperado

El evento contiene información suficiente para continuar comercialmente.

## Criterios de aceptación

* No se repiten datos confirmados.
* Se aceptan fechas aproximadas.
* Se aceptan rangos de invitados.
* El presupuesto no es obligatorio.
* Los servicios solicitados no se marcan como incluidos.

---

# 11. UC-007 — Corregir datos del evento

## Objetivo

Actualizar información cuando el cliente modifica o corrige un dato.

## Actor principal

Cliente.

## Disparador

El cliente expresa una corrección.

## Ejemplos

* “No son 30, son 55”.
* “Cambiamos para el 19 de diciembre”.
* “Ya no quiero DJ”.
* “Será matrimonio civil”.

## Precondiciones

* Existe un lead o evento activo.
* El dato anterior está registrado.

## Flujo principal

1. El sistema identifica el campo corregido.
2. Recupera el valor anterior.
3. Valida el nuevo valor.
4. Actualiza el registro.
5. Marca la calidad como `CORRECTED`.
6. Crea auditoría.
7. Informa brevemente al cliente.
8. Evalúa impacto sobre:

   * cotización;
   * capacidad;
   * visita;
   * reserva;
   * servicios.
9. Si afecta una cotización enviada, solicita nueva versión.
10. Si afecta una operación crítica, escala.

## Excepciones

### Corrección ambigua

Se solicita confirmación.

### Cambio de fecha con reserva confirmada

Debe escalarse; no se actualiza automáticamente.

### Cambio de invitados superior a 60

Se activa revisión de capacidad.

## Datos modificados

* entidad correspondiente;
* estado de calidad;
* `AuditEvent`;
* posible estado de cotización.

## Reglas relacionadas

* BR-CUS-006.
* BR-QUOTE-003.
* BR-AUD-001.

## Resultado esperado

El nuevo dato queda vigente y el anterior queda trazable.

## Criterios de aceptación

* No se pierde el valor anterior.
* La corrección impacta los módulos dependientes.
* No se modifica una reserva crítica sin autorización.

---

# 12. UC-008 — Gestionar cambio temporal de tema

## Objetivo

Responder una nueva pregunta sin perder el flujo anterior.

## Actor principal

Cliente.

## Ejemplo

> Quiero cotizar una boda. Antes de seguir, ¿tienen parqueadero?

## Precondiciones

* Existe una acción pendiente.
* La nueva pregunta puede responderse.

## Flujo principal

1. El sistema identifica la nueva intención.
2. Guarda la acción anterior en `pending_action`.
3. Responde la nueva pregunta.
4. Recupera el flujo anterior.
5. Formula la siguiente pregunta pendiente.

## Excepciones

### El nuevo tema requiere asesor

El flujo anterior queda suspendido hasta resolver el handoff.

### El cliente cambia definitivamente de objetivo

Se actualiza la intención principal.

## Datos modificados

* `Conversation.current_intent`;
* `Conversation.previous_intent`;
* `Conversation.pending_action`.

## Reglas relacionadas

* BR-CON-003.
* BR-CON-005.

## Resultado esperado

La conversación continúa de manera natural sin pérdida de contexto.

## Criterios de aceptación

* Se responde la pregunta inmediata.
* Se retoma el flujo correcto.
* No se vuelven a pedir datos confirmados.

---

# 13. UC-009 — Crear solicitud de cotización

## Objetivo

Crear una solicitud estructurada para que un asesor prepare una propuesta.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Backend.
* Asesor.

## Disparador

El cliente solicita cotización y los datos mínimos están completos.

## Precondiciones

Debe existir:

* nombre;
* teléfono;
* tipo de evento;
* fecha, mes o periodo;
* invitados o rango.

## Flujo principal

1. El sistema valida datos mínimos.
2. Genera un resumen.
3. El bot presenta el resumen al cliente.
4. Solicita confirmación.
5. El cliente confirma.
6. El sistema crea `QuoteRequest`.
7. Estado inicial: `READY`.
8. Calcula `due_at`.
9. Cambia el lead a `QUOTE_REQUESTED`.
10. Envía la solicitud a la bandeja comercial.
11. Informa al cliente el plazo de hasta tres días hábiles.
12. Registra auditoría.

## Flujo alternativo A — Cliente corrige

1. Se actualiza el dato.
2. Se vuelve a presentar resumen si la corrección es relevante.

## Flujo alternativo B — Falta un dato mínimo

La solicitud queda en `DRAFT`.

## Excepciones

### Error al crear solicitud

* conservar los datos;
* registrar error;
* escalar si es necesario;
* no informar que quedó creada.

## Datos modificados

* `QuoteRequest`;
* `Lead.status`;
* `Conversation.status`;
* `AuditEvent`.

## Reglas relacionadas

* BR-QREQ-001 a BR-QREQ-011.
* BR-SLA-001.

## Resultado esperado

Existe una solicitud lista y asignable.

## Criterios de aceptación

* Los mínimos se validan.
* Se requiere confirmación.
* Se calcula plazo.
* No se genera un precio automático.

---

# 14. UC-010 — Asignar solicitud de cotización

## Objetivo

Permitir que un asesor tome responsabilidad sobre una solicitud.

## Actor principal

Asesor.

## Precondiciones

* Solicitud en `READY`.
* Asesor autenticado.
* Asesor con permiso.

## Flujo principal

1. El asesor abre la bandeja.
2. Visualiza solicitudes pendientes.
3. Selecciona una solicitud.
4. Pulsa “Tomar solicitud”.
5. El sistema valida que no esté asignada.
6. Registra `assigned_agent_id`.
7. Cambia estado a `ASSIGNED`.
8. Registra hora.
9. Actualiza el lead.
10. Genera auditoría.

## Flujo alternativo — Solicitud ya tomada

El sistema informa que otro asesor la asignó.

## Excepciones

### Asesor sin permisos

Se rechaza la acción.

## Datos modificados

* `QuoteRequest`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-LEAD-010.
* BR-HAND-003.
* BR-HAND-004.
* BR-HAND-005.

## Resultado esperado

Una sola persona queda responsable de la solicitud.

## Criterios de aceptación

* No existen dos responsables activos.
* La asignación queda auditada.
* La solicitud desaparece de la cola no asignada.

---

# 15. UC-011 — Registrar cotización humana

## Objetivo

Guardar una propuesta preparada por un asesor.

## Actor principal

Asesor.

## Precondiciones

* Solicitud asignada.
* Datos del evento disponibles.
* Asesor autorizado.

## Flujo principal

1. El asesor abre la solicitud.
2. Registra conceptos.
3. Registra subtotal.
4. Registra impuestos, si aplica.
5. Registra descuento autorizado, si aplica.
6. Registra total.
7. Define vigencia.
8. Adjunta documento.
9. Guarda como `DRAFT`.
10. Puede marcarla `APPROVED`.
11. Envía al cliente.
12. Cambia estado a `SENT`.
13. Actualiza lead a `QUOTE_SENT`.
14. Registra fecha de envío.

## Excepciones

### Descuento no autorizado

La acción se bloquea o requiere aprobación.

### Documento faltante

Puede guardarse borrador, pero no marcarse enviado si el proceso exige archivo.

## Datos modificados

* `Quote`;
* `QuoteItem`;
* `QuoteRequest`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-QUOTE-001 a BR-QUOTE-006.
* BR-CFG-004.

## Resultado esperado

La cotización queda almacenada, versionada y trazable.

## Criterios de aceptación

* Tiene versión.
* Tiene responsable.
* Una cotización enviada no se modifica.
* Se registra vigencia.

---

# 16. UC-012 — Crear nueva versión de cotización

## Objetivo

Crear una nueva propuesta cuando cambian datos o condiciones.

## Actor principal

Asesor.

## Disparador

Cambio en:

* fecha;
* invitados;
* servicios;
* menú;
* precio;
* descuento;
* duración;
* condiciones.

## Precondiciones

* Existe cotización previa.
* La cotización previa fue enviada o aprobada.

## Flujo principal

1. El sistema copia la estructura de la versión anterior.
2. Incrementa `version_number`.
3. Marca la anterior como `SUPERSEDED` cuando corresponda.
4. Aplica cambios.
5. Conserva los valores históricos.
6. Registra responsable.
7. Envía nueva versión.
8. Actualiza estado del lead.

## Excepciones

### Cotización anterior en borrador

Puede editarse mientras no haya sido enviada, según permisos.

## Datos modificados

* `Quote`;
* `QuoteItem`;
* `AuditEvent`.

## Reglas relacionadas

* BR-QUOTE-001.
* BR-QUOTE-002.
* BR-QUOTE-003.
* BR-AUD-004.

## Resultado esperado

Las versiones anteriores permanecen disponibles.

## Criterios de aceptación

* No se sobrescribe la cotización enviada.
* El número de versión aumenta.
* Se puede identificar cuál está vigente.

---

# 17. UC-013 — Consultar disponibilidad de visita

## Objetivo

Consultar horarios válidos para conocer La Ceiba.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Servicio de agenda.
* Proveedor de calendario.

## Disparador

El cliente solicita una visita.

## Precondiciones

* Conversación activa.
* Servicio de agenda disponible.

## Flujo principal

1. El bot informa reglas generales.
2. Solicita fecha.
3. El cliente entrega fecha.
4. El backend convierte y valida la fecha.
5. Verifica:

   * martes a sábado;
   * no festivo;
   * mínimo tres días;
   * no bloqueo;
   * máximo diario;
   * horarios libres.
6. Recupera horarios válidos.
7. Presenta opciones.
8. Cambia estado a `WAITING_FOR_APPOINTMENT_SELECTION`.

## Flujo alternativo A — Fecha relativa

Se convierte y se confirma en formato absoluto.

## Flujo alternativo B — Día inválido

Se informa la regla y se solicitan alternativas.

## Flujo alternativo C — Día completo

Se ofrecen otras fechas.

## Excepciones

### Calendario no disponible

Se ejecuta UC-030.

## Datos modificados

* `Conversation`;
* posible `AppointmentDraft`;
* métricas de agenda.

## Reglas relacionadas

* BR-APT-001 a BR-APT-015.
* BR-GEN-004.

## Resultado esperado

El cliente recibe únicamente horarios realmente válidos.

## Criterios de aceptación

* No se ofrecen festivos.
* No se ofrecen horarios ocupados.
* No se ofrecen citas con menos de tres días.
* Se usa `America/Bogota`.

---

# 18. UC-014 — Agendar visita

## Objetivo

Crear una visita confirmada.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Backend.
* Calendario.
* Business Manager.

## Precondiciones

* Fecha válida.
* Horario seleccionado.
* Nombre disponible.
* Teléfono disponible.
* Máximo tres asistentes.
* Motivo disponible.
* Cliente confirmó.

## Flujo principal

1. El sistema recopila datos faltantes.
2. Presenta resumen:

   * fecha;
   * hora;
   * asistentes;
   * motivo.
3. Solicita confirmación.
4. El cliente confirma.
5. El backend consulta disponibilidad nuevamente.
6. Crea la cita local.
7. Crea el evento de calendario.
8. Guarda identificador externo.
9. Cambia estado a `CONFIRMED`.
10. Programa recordatorio.
11. Actualiza lead a `VISIT_SCHEDULED`.
12. Informa al cliente.
13. Registra auditoría.

## Flujo alternativo — Horario ocupado al confirmar

1. No crea la cita.
2. Informa el conflicto.
3. Ofrece nuevas opciones.

## Excepciones

### Error del calendario

Se ejecuta UC-030.

### Más de tres asistentes

Se solicita ajuste o revisión humana.

## Datos modificados

* `Appointment`;
* `Lead`;
* `Conversation`;
* `Notification`;
* `AuditEvent`.

## Reglas relacionadas

* BR-APT-010 a BR-APT-020.
* BR-NOT-001 a BR-NOT-005.
* INV-002.

## Resultado esperado

Existe una sola visita confirmada y sincronizada.

## Criterios de aceptación

* Se valida disponibilidad dos veces.
* Se guarda identificador externo.
* El recordatorio queda programado.
* No se crea una cita doble.

---

# 19. UC-015 — Reprogramar visita

## Objetivo

Cambiar la fecha y hora de una visita existente.

## Actor principal

Cliente.

## Precondiciones

* Existe visita activa.
* El cliente está identificado.

## Flujo principal

1. El sistema identifica la visita.
2. Muestra fecha y hora actuales.
3. Solicita nueva fecha.
4. Consulta disponibilidad.
5. Presenta opciones.
6. El cliente selecciona.
7. El sistema muestra resumen.
8. El cliente confirma.
9. Valida disponibilidad nuevamente.
10. Actualiza calendario.
11. Actualiza cita local.
12. Registra historial de cambio.
13. Incrementa contador.
14. Reprograma recordatorio.
15. Confirma al cliente.

## Flujo alternativo — Varias visitas

Se solicita identificar cuál desea cambiar.

## Excepciones

### Nuevo horario ocupado

No se modifica la cita actual y se ofrecen alternativas.

### Fallo al actualizar calendario

Se conserva la cita original y se escala.

## Datos modificados

* `Appointment`;
* `AppointmentChange`;
* `Notification`;
* `AuditEvent`.

## Reglas relacionadas

* BR-APT-021 a BR-APT-025.
* BR-NOT-005.

## Resultado esperado

La visita queda actualizada sin perder el historial.

## Criterios de aceptación

* Se conserva fecha anterior.
* No existe periodo sin cita válida por un fallo parcial.
* El recordatorio anterior se cancela.

---

# 20. UC-016 — Cancelar visita

## Objetivo

Cancelar una visita después de confirmación expresa.

## Actor principal

Cliente.

## Precondiciones

* Existe visita activa.
* Cliente identificado.

## Flujo principal

1. El sistema identifica la visita.
2. Informa fecha y hora.
3. Solicita confirmación.
4. El cliente confirma.
5. Calcula si es cancelación ordinaria o tardía.
6. Cancela en calendario.
7. Actualiza estado local.
8. Cancela recordatorio.
9. Registra motivo si se informa.
10. Confirma al cliente.
11. Registra auditoría.

## Flujo alternativo — Cliente no confirma

La visita permanece activa.

## Excepciones

### Error al cancelar en calendario

* no marcar como cancelada localmente de forma definitiva;
* registrar estado de reconciliación;
* escalar.

## Datos modificados

* `Appointment`;
* `Notification`;
* `AuditEvent`.

## Reglas relacionadas

* BR-APT-026 a BR-APT-029.

## Resultado esperado

La cita queda cancelada de forma consistente.

## Criterios de aceptación

* No se cancela sin confirmación.
* Se identifica cancelación tardía.
* No se envía recordatorio posterior.

---

# 21. UC-017 — Enviar recordatorio de visita

## Objetivo

Recordar al cliente su visita un día antes.

## Actor principal

Sistema.

## Precondiciones

* Cita en `CONFIRMED` o `RESCHEDULED`.
* Falta un día.
* Recordatorio no enviado.
* Cita no cancelada.

## Flujo principal

1. El sistema identifica recordatorios pendientes.
2. Verifica estado de cita.
3. Construye mensaje.
4. Envía por WhatsApp.
5. Registra resultado.
6. Marca `reminder_sent_at`.

## Contenido

* nombre;
* fecha;
* hora;
* dirección;
* mapa;
* asistentes;
* puntualidad;
* opciones de cambio.

## Excepciones

### Error de envío

* registrar error;
* reintentar según política;
* evitar duplicados.

## Datos modificados

* `Notification`;
* `Message`;
* `Appointment`.

## Reglas relacionadas

* BR-NOT-001 a BR-NOT-005.

## Resultado esperado

El cliente recibe un único recordatorio oportuno.

## Criterios de aceptación

* No se envía a citas canceladas.
* No se duplica.
* Se actualiza tras reprogramación.

---

# 22. UC-018 — Registrar inasistencia

## Objetivo

Registrar que el cliente no asistió.

## Actor principal

Business Manager.

## Precondiciones

* Hora de la visita ya pasó.
* Cita estaba confirmada.
* Usuario autorizado.

## Flujo principal

1. El Business Manager abre la cita.
2. Selecciona “No asistió”.
3. El sistema valida estado.
4. Cambia a `NO_SHOW`.
5. Incrementa `no_show_count`.
6. Envía mensaje cordial.
7. Aplica reglas según cantidad.
8. Registra auditoría.

## Tratamiento por contador

### Primera

Permitir nueva agenda.

### Segunda

Notificar internamente.

### Tercera

Escalar nueva solicitud de visita.

## Excepciones

### Visita marcada completada

No se permite marcarla como inasistencia sin corrección autorizada.

## Datos modificados

* `Appointment`;
* `Customer.no_show_count`;
* `Notification`;
* `AuditEvent`.

## Reglas relacionadas

* BR-APT-030 a BR-APT-034.

## Resultado esperado

La inasistencia queda trazable sin bloquear automáticamente al cliente.

## Criterios de aceptación

* El contador aumenta.
* El cliente no recibe lenguaje sancionatorio.
* La tercera reincidencia produce revisión humana.

---

# 23. UC-019 — Solicitar atención humana

## Objetivo

Transferir una conversación cuando el cliente solicita una persona o el flujo lo requiere.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Asesor.

## Disparador

* solicitud directa;
* baja confianza;
* negociación;
* descuento;
* pago;
* cancelación;
* excepción;
* servicio especial.

## Precondiciones

* Conversación activa.

## Flujo principal

1. El sistema detecta el motivo.
2. Determina prioridad.
3. Genera resumen.
4. Crea `Handoff`.
5. Cambia conversación a `WAITING_FOR_HUMAN`.
6. Envía a bandeja.
7. Informa al cliente.
8. Mantiene el bot según política hasta que el asesor tome la conversación.
9. Registra auditoría.

## Flujo alternativo — Fuera de horario

Informa el horario humano.

## Excepciones

### Fallo al generar resumen

El handoff se crea con datos estructurados y últimos mensajes.

## Datos modificados

* `Handoff`;
* `Conversation`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-HAND-001 a BR-HAND-011.

## Resultado esperado

La conversación queda disponible para un asesor con contexto suficiente.

## Criterios de aceptación

* El motivo queda registrado.
* La prioridad queda registrada.
* El cliente recibe confirmación.
* El caso entra en bandeja.

---

# 24. UC-020 — Tomar conversación escalada

## Objetivo

Permitir que un asesor asuma la atención.

## Actor principal

Asesor.

## Precondiciones

* Handoff pendiente.
* Asesor autenticado.
* Conversación no asignada.

## Flujo principal

1. El asesor abre la bandeja.
2. Selecciona una conversación.
3. Revisa el resumen.
4. Pulsa “Tomar conversación”.
5. El sistema valida exclusividad.
6. Asigna al asesor.
7. Cambia estado a `HUMAN_ACTIVE`.
8. Establece `bot_enabled = false`.
9. Registra hora.
10. Permite responder.

## Excepciones

### Otro asesor la tomó

Se bloquea la acción.

### Error al pausar bot

No se permite enviar respuesta hasta resolver consistencia.

## Datos modificados

* `Conversation`;
* `Handoff`;
* `AuditEvent`.

## Reglas relacionadas

* BR-HAND-004 a BR-HAND-007.
* INV-003.

## Resultado esperado

Solo el asesor asignado responde.

## Criterios de aceptación

* El bot queda pausado.
* No existen dos asesores activos.
* La asignación queda auditada.

---

# 25. UC-021 — Devolver conversación al bot

## Objetivo

Reactivar la automatización después de atención humana.

## Actor principal

Asesor.

## Precondiciones

* Conversación en `HUMAN_ACTIVE`.
* Asesor asignado.

## Flujo principal

1. El asesor registra nota o resolución.
2. Actualiza datos comerciales necesarios.
3. Selecciona “Devolver al bot”.
4. El sistema genera o actualiza resumen.
5. Cambia estado a `RETURNED_TO_BOT`.
6. Establece `bot_enabled = true`.
7. Libera asignación activa según política.
8. Registra auditoría.
9. El siguiente mensaje vuelve al orquestador.

## Excepciones

### Existe acción humana pendiente

El sistema puede impedir retorno o solicitar confirmación.

## Datos modificados

* `Conversation`;
* `Handoff`;
* `AuditEvent`.

## Reglas relacionadas

* BR-HAND-008.

## Resultado esperado

El bot retoma con contexto actualizado.

## Criterios de aceptación

* No se pierde la resolución humana.
* El bot no vuelve a preguntar datos resueltos.
* El retorno queda auditado.

---

# 26. UC-022 — Gestionar queja

## Objetivo

Detectar, contener y escalar una inconformidad.

## Actor principal

Cliente.

## Disparador

El cliente expresa:

* molestia;
* incumplimiento;
* inconformidad;
* reclamación;
* solicitud de solución.

## Precondiciones

* Conversación activa.

## Flujo principal

1. El sistema detecta intención `COMPLAINT`.
2. Asigna prioridad mínima `URGENT`.
3. Envía respuesta empática.
4. Genera resumen.
5. Crea handoff.
6. Notifica al equipo.
7. Pausa el bot cuando el asesor toma.
8. Registra auditoría.

## Excepciones

### Queja crítica

Puede elevarse a `CRITICAL`.

### Solicitud de compensación

No se concede; se escala.

## Datos modificados

* `Handoff`;
* `Conversation`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-HAND-012 a BR-HAND-015.
* BR-URG-001.

## Resultado esperado

La queja queda priorizada y atendida por una persona.

## Criterios de aceptación

* El bot no discute.
* No promete devolución.
* La prioridad es adecuada.
* Se notifica al responsable.

---

# 27. UC-023 — Registrar información de pago

## Objetivo

Registrar que el cliente informa o envía un pago.

## Actor principal

Cliente.

## Actores secundarios

* Bot.
* Asesor.

## Disparador

* “Ya pagué”.
* Envío de comprobante.
* Envío de referencia.

## Precondiciones

* Existe lead, cotización o reserva relacionada, cuando sea posible.

## Flujo principal

1. El sistema detecta intención de pago.
2. Guarda el mensaje o archivo.
3. Crea o actualiza `Payment`.
4. Cambia a `PAYMENT_REVIEW`.
5. Define `review_due_at`.
6. Crea handoff urgente.
7. Informa al cliente que está en validación.
8. No confirma reserva.
9. Registra auditoría.

## Flujo alternativo — No se identifica la reserva

El asesor deberá relacionar el pago manualmente.

## Excepciones

### Cliente envía datos sensibles

El bot advierte que no comparta claves, PIN o CVV.

### Archivo inválido

Se registra y se solicita una alternativa si es necesario.

## Datos modificados

* `Payment`;
* `Attachment`;
* `Handoff`;
* `Reservation`;
* `AuditEvent`.

## Reglas relacionadas

* BR-PAY-001 a BR-PAY-009.
* BR-URG-003.

## Resultado esperado

El pago queda pendiente de revisión humana.

## Criterios de aceptación

* El bot no confirma pago.
* Se registra plazo de un día.
* Se notifica a un asesor.
* El comprobante queda protegido.

---

# 28. UC-024 — Confirmar pago

## Objetivo

Permitir que un asesor valide un pago.

## Actor principal

Asesor.

## Precondiciones

* Pago en `PAYMENT_REVIEW`.
* Asesor autorizado.
* Evidencia disponible.

## Flujo principal

1. El asesor revisa información.
2. Compara valor esperado y reportado.
3. Verifica recepción.
4. Selecciona confirmar o rechazar.
5. Si confirma:

   * cambia a `PAYMENT_CONFIRMED`;
   * registra responsable;
   * registra fecha.
6. Si rechaza:

   * cambia a `PAYMENT_REJECTED`;
   * registra motivo.
7. Notifica al cliente.
8. Registra auditoría.

## Excepciones

### Pago parcial

Se registra según política y no se confirma reserva si no cumple la condición.

### Pago no identificable

Permanece en revisión o se rechaza.

## Datos modificados

* `Payment`;
* `Reservation`;
* `AuditEvent`;
* `Message`.

## Reglas relacionadas

* BR-PAY-004 a BR-PAY-008.
* INV-006.

## Resultado esperado

El estado del pago refleja una validación humana.

## Criterios de aceptación

* Solo un asesor autorizado confirma.
* Se registra responsable.
* El cliente recibe resultado.
* No se reserva automáticamente antes de cumplir reglas.

---

# 29. UC-025 — Confirmar reserva de fecha

## Objetivo

Marcar una fecha como oficialmente reservada.

## Actor principal

Asesor.

## Precondiciones

* Cotización aceptada.
* Pago confirmado.
* Valor de separación válido.
* Condiciones aceptadas.
* Asesor autorizado.

## Flujo principal

1. El sistema valida `PAYMENT_CONFIRMED`.
2. Valida el 50 % del valor acordado o excepción aprobada.
3. Verifica que la fecha siga disponible.
4. Crea o actualiza la reserva.
5. Cambia estado a `RESERVED`.
6. Registra:

   * cotización;
   * pago;
   * porcentaje;
   * asesor;
   * fecha;
   * términos.
7. Informa al cliente.
8. Registra auditoría.

## Excepciones

### La fecha ya no está disponible

Se bloquea la reserva y se escala como crítica.

### Pago inferior

No se confirma salvo excepción autorizada.

## Datos modificados

* `Reservation`;
* `Event`;
* `Payment`;
* `Lead`;
* `AuditEvent`.

## Reglas relacionadas

* BR-RES-001 a BR-RES-007.
* INV-001.

## Resultado esperado

La fecha queda reservada únicamente después de validaciones.

## Criterios de aceptación

* No existe reserva sin pago confirmado.
* La fecha se valida antes de reservar.
* Se registra quién confirmó.

---

# 30. UC-026 — Solicitar cancelación de evento

## Objetivo

Registrar y escalar una solicitud de cancelación.

## Actor principal

Cliente.

## Precondiciones

* Existe evento o reserva identificable.

## Flujo principal

1. El sistema identifica la reserva.
2. Calcula tiempo restante.
3. Cambia estado a `CANCEL_REQUESTED`.
4. Crea handoff.
5. Si falta un mes o más:

   * informa que un asesor revisará las condiciones.
6. Si falta menos de un mes:

   * informa que no hay devolución;
   * escala igualmente.
7. Registra auditoría.

## Flujo alternativo — Cliente solicita cambio de fecha

Se trata como excepción y se escala.

## Excepciones

### No se identifica la reserva

El asesor debe localizarla manualmente.

### Emergencia alegada

No se promete excepción; se escala.

## Datos modificados

* `Reservation`;
* `Handoff`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CAN-001 a BR-CAN-006.
* INV-010.

## Resultado esperado

La cancelación queda registrada sin decisión automática indebida.

## Criterios de aceptación

* Siempre se escala.
* El bot no promete devolución.
* Se aplica la respuesta correspondiente al plazo.

---

# 31. UC-027 — Gestionar caso urgente

## Objetivo

Priorizar y notificar situaciones que requieren atención rápida.

## Actor principal

Cliente.

## Disparadores

* evento en menos de 72 horas;
* cliente presente sin atención;
* emergencia médica;
* incidente de seguridad;
* problema sanitario;
* doble reserva;
* pago erróneo;
* reserva incorrecta.

## Precondiciones

* Mensaje recibido.

## Flujo principal

1. El sistema detecta señales de urgencia.
2. Clasifica prioridad.
3. Crea handoff.
4. Notifica responsables.
5. Envía respuesta segura.
6. Pausa automatización cuando sea necesario.
7. Registra auditoría.

## Prioridades

```text
NORMAL
HIGH
URGENT
CRITICAL
```

## Excepciones

### Emergencia física

El bot indica contactar inmediatamente:

* personal presente;
* servicios de emergencia.

No espera a que el equipo responda por chat.

## Datos modificados

* `Handoff`;
* `Conversation`;
* `AuditEvent`;
* alertas.

## Reglas relacionadas

* BR-URG-001 a BR-URG-006.

## Resultado esperado

El equipo recibe notificación prioritaria.

## Criterios de aceptación

* Los casos críticos se notifican inmediatamente.
* No se oculta una emergencia detrás de un flujo normal.
* La acción queda auditada.

---

# 32. UC-028 — Gestionar mensaje duplicado

## Objetivo

Evitar que un webhook repetido produzca acciones duplicadas.

## Actor principal

Sistema.

## Disparador

Se recibe un `external_message_id` ya existente.

## Precondiciones

* Identificador externo disponible.

## Flujo principal

1. El sistema consulta el identificador.
2. Detecta que ya fue procesado.
3. No crea un nuevo mensaje.
4. No ejecuta nuevamente el orquestador.
5. No envía una nueva respuesta.
6. Registra el evento técnico si es necesario.
7. Responde al proveedor con éxito idempotente.

## Excepciones

### Mensaje almacenado pero proceso incompleto

El sistema reanuda desde un punto seguro, sin repetir acciones ejecutadas.

## Datos modificados

* registro técnico de idempotencia.

## Reglas relacionadas

* BR-SEC-007.
* INV-005.

## Resultado esperado

Un mensaje produce una sola acción lógica.

## Criterios de aceptación

* No se duplican citas.
* No se duplican leads.
* No se duplican respuestas.
* No se duplican pagos.

---

# 33. UC-029 — Gestionar fallo de IA

## Objetivo

Mantener una atención segura cuando OpenRouter o el modelo falla.

## Actor principal

Sistema.

## Disparador

* timeout;
* respuesta inválida;
* JSON incorrecto;
* baja confianza;
* proveedor indisponible.

## Precondiciones

* Mensaje almacenado.

## Flujo principal

1. El sistema registra la ejecución fallida.
2. Intenta reintento si es seguro.
3. Si es FAQ determinista, responde desde conocimiento.
4. Si puede usar menú básico, lo presenta.
5. Si la acción es crítica, escala.
6. Si no puede interpretar:

   * informa que el mensaje quedó registrado;
   * evita inventar.
7. Registra métricas y error.

## Flujo alternativo — Fallback de modelo

Puede utilizarse otro modelo configurado.

## Excepciones

### Reintentos agotados

Se escala o usa respuesta neutra.

## Datos modificados

* `AIExecution`;
* `Conversation`;
* `Handoff`;
* logs.

## Reglas relacionadas

* BR-AI-001 a BR-AI-008.

## Resultado esperado

El sistema falla de manera segura sin perder mensajes.

## Criterios de aceptación

* No se ejecutan acciones críticas con salida inválida.
* Las FAQ siguen funcionando.
* El error no se muestra técnicamente al cliente.

---

# 34. UC-030 — Gestionar fallo de calendario

## Objetivo

Evitar confirmaciones incorrectas cuando falla la integración de agenda.

## Actor principal

Sistema.

## Disparador

Error al:

* consultar;
* crear;
* actualizar;
* cancelar.

## Precondiciones

* Existe una solicitud de agenda.

## Flujo principal

1. El sistema registra el error.
2. No confirma la operación.
3. Conserva la solicitud.
4. Evita inconsistencias locales.
5. Crea handoff si corresponde.
6. Informa al cliente que no se completó la confirmación.
7. Programa reconciliación o revisión.

## Flujo alternativo — Fallo después de crear externamente

1. El sistema consulta el proveedor usando idempotencia.
2. Determina si el evento se creó.
3. Sincroniza el estado antes de reintentar.

## Excepciones

### Cancelación externa exitosa y local fallida

Se marca para reconciliación inmediata.

## Datos modificados

* `Appointment`;
* `IntegrationError`;
* `Handoff`;
* logs.

## Reglas relacionadas

* BR-APT-014.
* BR-APT-016.
* INV-002.

## Resultado esperado

El cliente no recibe una confirmación falsa.

## Criterios de aceptación

* No se crea una segunda cita al reintentar.
* El estado local y externo pueden reconciliarse.
* Se informa de forma segura.

---

# 35. UC-031 — Actualizar base de conocimiento

## Objetivo

Crear, modificar, aprobar o desactivar respuestas autorizadas.

## Actor principal

Administrador o Content Operator.

## Precondiciones

* Usuario autenticado.
* Permiso correspondiente.

## Flujo principal

1. El usuario abre base de conocimiento.
2. Crea o selecciona una entrada.
3. Define:

   * categoría;
   * variantes;
   * respuesta;
   * respuesta corta;
   * vigencia.
4. Guarda en `DRAFT`.
5. Envía a revisión.
6. Usuario autorizado aprueba.
7. Se asigna versión.
8. Cambia a `APPROVED`.
9. La versión anterior se conserva.
10. Registra auditoría.

## Flujo alternativo — Desactivar

1. Se cambia a `INACTIVE`.
2. Ya no se utiliza automáticamente.

## Excepciones

### Usuario sin autorización para aprobar

Puede editar borradores, pero no activar.

## Datos modificados

* `KnowledgeEntry`;
* `AuditEvent`.

## Reglas relacionadas

* BR-GEN-007.
* BR-AUD-004.
* BR-CFG-002.
* BR-CFG-003.

## Resultado esperado

Solo respuestas aprobadas y vigentes son utilizadas.

## Criterios de aceptación

* Existe versión.
* Existe aprobador.
* Las respuestas inactivas no se envían.
* Se conserva historial.

---

# 36. UC-032 — Cerrar conversación

## Objetivo

Finalizar una conversación sin perder información comercial.

## Actor principal

Bot o asesor.

## Disparador

* pregunta resuelta;
* cliente se despide;
* flujo completado;
* asesor finaliza;
* inactividad según política.

## Precondiciones

* No existe acción crítica pendiente.
* El estado permite cierre.

## Flujo principal

1. El sistema verifica acciones pendientes.
2. Genera o actualiza resumen.
3. Conserva lead y evento.
4. Cambia conversación a `RESOLVED`.
5. Registra fecha.
6. Puede cambiar posteriormente a `CLOSED`.
7. Registra auditoría.

## Flujo alternativo — Cliente desea continuar después

Se recupera o reabre la conversación.

## Excepciones

### Existe pago o cancelación pendiente

No se cierra automáticamente.

### Existe asesor activo

Solo el asesor o un manager puede cerrar.

## Datos modificados

* `Conversation`;
* `AuditEvent`.

## Reglas relacionadas

* BR-CON-009.
* BR-CON-010.

## Resultado esperado

La conversación se cierra, pero los datos permanecen disponibles.

## Criterios de aceptación

* No se eliminan leads.
* Se puede retomar posteriormente.
* No se cierra una acción crítica pendiente.

---

# 37. Matriz de trazabilidad entre casos de uso y reglas

| Caso   | Reglas principales                              |
| ------ | ----------------------------------------------- |
| UC-001 | BR-CUS-001, BR-CUS-002, BR-SEC-006, BR-SEC-007  |
| UC-002 | BR-KB-001 a BR-KB-016, BR-AI-007                |
| UC-003 | BR-CUS-003 a BR-CUS-005                         |
| UC-004 | BR-CUS-007, BR-LEAD-001 a BR-LEAD-003           |
| UC-005 | BR-EVT-001, BR-EVT-002, BR-AI-003, BR-AI-004    |
| UC-006 | BR-CON-001, BR-CON-002, BR-EVT-003 a BR-EVT-016 |
| UC-007 | BR-CUS-006, BR-QUOTE-003, BR-AUD-001            |
| UC-008 | BR-CON-003, BR-CON-005                          |
| UC-009 | BR-QREQ-001 a BR-QREQ-011                       |
| UC-010 | BR-LEAD-010, BR-HAND-003 a BR-HAND-005          |
| UC-011 | BR-QUOTE-001 a BR-QUOTE-006                     |
| UC-012 | BR-QUOTE-001 a BR-QUOTE-003                     |
| UC-013 | BR-APT-001 a BR-APT-015                         |
| UC-014 | BR-APT-010 a BR-APT-020, BR-NOT-001             |
| UC-015 | BR-APT-021 a BR-APT-025                         |
| UC-016 | BR-APT-026 a BR-APT-029                         |
| UC-017 | BR-NOT-001 a BR-NOT-005                         |
| UC-018 | BR-APT-030 a BR-APT-034                         |
| UC-019 | BR-HAND-001 a BR-HAND-011                       |
| UC-020 | BR-HAND-004 a BR-HAND-007                       |
| UC-021 | BR-HAND-008                                     |
| UC-022 | BR-HAND-012 a BR-HAND-015                       |
| UC-023 | BR-PAY-001 a BR-PAY-009                         |
| UC-024 | BR-PAY-004 a BR-PAY-008                         |
| UC-025 | BR-RES-001 a BR-RES-007                         |
| UC-026 | BR-CAN-001 a BR-CAN-006                         |
| UC-027 | BR-URG-001 a BR-URG-006                         |
| UC-028 | BR-SEC-007                                      |
| UC-029 | BR-AI-001 a BR-AI-008                           |
| UC-030 | BR-APT-014, BR-APT-016                          |
| UC-031 | BR-CFG-002, BR-CFG-003, BR-AUD-004              |
| UC-032 | BR-CON-009, BR-CON-010                          |

---

# 38. Matriz de prioridad de implementación

## Prioridad crítica

```text
UC-001
UC-002
UC-004
UC-005
UC-006
UC-009
UC-013
UC-014
UC-019
UC-020
UC-023
UC-024
UC-025
UC-028
UC-029
UC-030
```

## Prioridad alta

```text
UC-003
UC-007
UC-008
UC-010
UC-015
UC-016
UC-017
UC-022
UC-026
UC-027
UC-031
```

## Prioridad media

```text
UC-011
UC-012
UC-018
UC-021
UC-032
```

La prioridad media no significa que pueda omitirse del MVP, sino que su implementación puede realizarse después del núcleo crítico.

---

# 39. Casos de uso que requieren transacción o control de concurrencia

Los siguientes casos requieren protección especial:

## UC-014 — Agendar visita

Debe evitar:

* doble cita;
* sobrepasar máximo diario;
* confirmar un horario tomado.

## UC-015 — Reprogramar visita

Debe evitar:

* perder la cita anterior antes de confirmar la nueva;
* crear dos eventos.

## UC-016 — Cancelar visita

Debe mantener consistencia entre base local y calendario.

## UC-020 — Tomar conversación

Debe evitar dos asesores activos.

## UC-024 — Confirmar pago

Debe impedir confirmaciones duplicadas o contradictorias.

## UC-025 — Confirmar reserva

Debe impedir doble reserva y reserva sin pago.

## UC-028 — Mensaje duplicado

Debe garantizar idempotencia.

---

# 40. Casos de uso que siempre requieren auditoría

```text
UC-007 — Corregir datos
UC-009 — Crear solicitud
UC-010 — Asignar solicitud
UC-011 — Registrar cotización
UC-012 — Versionar cotización
UC-014 — Agendar visita
UC-015 — Reprogramar
UC-016 — Cancelar visita
UC-018 — Registrar inasistencia
UC-020 — Tomar conversación
UC-021 — Devolver al bot
UC-023 — Registrar pago
UC-024 — Confirmar pago
UC-025 — Confirmar reserva
UC-026 — Cancelar evento
UC-031 — Actualizar conocimiento
UC-032 — Cerrar conversación
```

---

# 41. Casos que no deben depender completamente de IA

Los siguientes casos deben poder ejecutarse con reglas deterministas:

* UC-001 — Iniciar conversación.
* UC-002 — FAQ autorizadas.
* UC-009 — Validar mínimos.
* UC-013 — Consultar disponibilidad.
* UC-014 — Crear cita.
* UC-015 — Reprogramar.
* UC-016 — Cancelar.
* UC-017 — Recordatorio.
* UC-020 — Asignar asesor.
* UC-023 — Registrar pago.
* UC-024 — Confirmar pago.
* UC-025 — Confirmar reserva.
* UC-028 — Deduplicación.
* UC-031 — Versionar conocimiento.

La IA puede ayudar a interpretar el mensaje, pero el resultado debe pasar por validación.

---

# 42. Casos expresamente fuera del MVP

No se implementarán todavía:

```text
UC-FUT-001 — Generar cotización automática
UC-FUT-002 — Calcular precio por reglas
UC-FUT-003 — Aplicar promoción automática
UC-FUT-004 — Generar contrato
UC-FUT-005 — Firmar contrato
UC-FUT-006 — Procesar pago en línea
UC-FUT-007 — Generar factura
UC-FUT-008 — Integrar Instagram
UC-FUT-009 — Transcribir notas de voz
UC-FUT-010 — Analizar fotografías
UC-FUT-011 — Gestionar proveedores
UC-FUT-012 — Gestionar operación posventa
UC-FUT-013 — Crear campañas comerciales
```

Estos casos deberán registrarse en el backlog posterior.

---

# 43. Criterios generales de aceptación

El catálogo de casos de uso se considerará implementado cuando:

1. Cada caso tenga al menos una prueba de flujo principal.
2. Cada excepción crítica tenga prueba.
3. Los datos modificados coincidan con la matriz de datos.
4. Las reglas aplicables estén implementadas en backend.
5. Los estados sean consistentes.
6. Las acciones críticas tengan auditoría.
7. Los errores de integración no generen confirmaciones falsas.
8. La IA no ejecute operaciones restringidas.
9. El bot se pause durante atención humana.
10. Las citas no se dupliquen.
11. Los pagos no se confirmen automáticamente.
12. Las reservas requieran pago validado.
13. Las cotizaciones enviadas conserven versiones.
14. Las respuestas autorizadas sean versionadas.
15. El cliente pueda retomar una conversación.

---

# 44. Definición de terminado de un caso de uso

Un caso de uso estará terminado cuando:

* su flujo principal esté implementado;
* los flujos alternativos estén contemplados;
* sus excepciones estén controladas;
* tenga validaciones;
* tenga autorización;
* tenga persistencia;
* tenga auditoría cuando aplique;
* tenga logs;
* tenga métricas;
* tenga pruebas unitarias;
* tenga pruebas de integración;
* tenga pruebas conversacionales cuando aplique;
* tenga documentación actualizada;
* cumpla sus criterios de aceptación.

---

# 45. Aprobación

Este documento queda listo para utilizarse como fuente oficial de los casos de uso del MVP.

Su aprobación implica que:

* los actores están definidos;
* los recorridos principales están delimitados;
* las excepciones críticas están identificadas;
* las operaciones humanas y automáticas están separadas;
* existe trazabilidad con las reglas de negocio;
* el alcance B está listo para convertirse en requerimientos funcionales;
* la futura opción A puede añadirse sin redefinir los flujos principales.
