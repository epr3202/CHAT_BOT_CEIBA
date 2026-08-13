# Flujos conversacionales

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/conversation/flows.md`
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
* `/docs/conversation/states.md`

---

# 1. Propósito

Este documento define cómo debe desarrollarse cada conversación entre un cliente y el Asistente Conversacional de La Ceiba Club House.

Cada flujo describe:

* objetivo;
* disparador;
* estado inicial;
* datos requeridos;
* decisiones;
* validaciones;
* mensajes;
* acciones del backend;
* integraciones;
* transiciones de estado;
* excepciones;
* condiciones de escalamiento;
* resultado esperado;
* criterios de aceptación.

Los flujos aquí definidos deberán ser implementados mediante una combinación de:

```text
Comprensión mediante IA
+
máquina de estados
+
reglas de negocio deterministas
+
servicios de dominio
+
persistencia
+
auditoría
```

La IA podrá interpretar el lenguaje natural, pero no deberá controlar directamente operaciones críticas.

---

# 2. Principios generales de los flujos

## FLOW-GEN-001 — Uso del contexto

Antes de responder, el orquestador deberá consultar:

* cliente;
* conversación;
* estado;
* intención anterior;
* acción pendiente;
* última pregunta;
* lead activo;
* evento activo;
* visita activa;
* solicitud de cotización;
* handoff activo;
* datos confirmados;
* datos faltantes.

---

## FLOW-GEN-002 — No repetir información

El bot no preguntará nuevamente un dato con estado:

```text
CONFIRMED
```

Cuando el dato exista como:

```text
INFERRED
PENDING_CONFIRMATION
```

podrá solicitar confirmación.

---

## FLOW-GEN-003 — Una pregunta principal

Cada respuesta deberá contener máximo una pregunta principal compleja.

Se podrán solicitar dos datos relacionados en una sola pregunta natural.

Ejemplo válido:

> ¿Qué tipo de celebración estás planeando y para cuántas personas aproximadamente?

Ejemplo no recomendado:

> ¿Cómo te llamas, cuál es la fecha, cuántos invitados son, cuánto presupuesto tienes y qué servicios quieres?

---

## FLOW-GEN-004 — Confirmación antes de ejecutar

Se requiere confirmación expresa antes de:

* crear una visita;
* reprogramar una visita;
* cancelar una visita;
* crear una solicitud de cotización lista;
* solicitar la cancelación de un evento;
* aplicar una corrección crítica.

---

## FLOW-GEN-005 — Interrupciones prioritarias

Estos eventos podrán interrumpir cualquier flujo:

```text
EMERGENCY
COMPLAINT
PAYMENT_MESSAGE
EVENT_CANCELLATION
HUMAN_REQUEST
```

El flujo anterior deberá conservarse como contexto recuperable cuando corresponda.

---

## FLOW-GEN-006 — Respuestas autorizadas

Las políticas sensibles deberán utilizar respuestas aprobadas.

La IA podrá adaptar:

* saludo;
* conectores;
* extensión;
* tratamiento;
* tono.

No podrá cambiar:

* porcentaje;
* plazo;
* política;
* horario;
* capacidad;
* condiciones de cancelación;
* autoridad requerida.

---

## FLOW-GEN-007 — Registro antes de respuesta

Todo mensaje entrante deberá persistirse antes de que se ejecute una acción.

Toda respuesta saliente deberá registrarse con:

* conversación;
* remitente;
* texto;
* intención;
* acción;
* estado de envío;
* fecha.

---

## FLOW-GEN-008 — Idempotencia

Un mismo mensaje no podrá ejecutar el flujo dos veces.

Cada acción crítica deberá utilizar una clave de idempotencia.

---

# 3. Estructura estándar de un flujo

Cada flujo se documentará con:

```text
Identificador
Nombre
Objetivo
Disparadores
Precondiciones
Estado inicial
Datos conocidos
Datos requeridos
Flujo principal
Flujos alternativos
Errores
Escalamiento
Estados resultantes
Datos modificados
Servicios invocados
Respuestas
Criterios de aceptación
```

---

# 4. Catálogo de flujos

| ID       | Flujo                                 |
| -------- | ------------------------------------- |
| `FL-001` | Inicio y recuperación de conversación |
| `FL-002` | Saludo sin intención específica       |
| `FL-003` | Consulta de información general       |
| `FL-004` | Captura inicial de lead               |
| `FL-005` | Recopilación de datos del evento      |
| `FL-006` | Solicitud de cotización               |
| `FL-007` | Consulta del estado de una cotización |
| `FL-008` | Modificación de datos o cotización    |
| `FL-009` | Solicitud de visita                   |
| `FL-010` | Selección y confirmación de visita    |
| `FL-011` | Reprogramación de visita              |
| `FL-012` | Cancelación de visita                 |
| `FL-013` | Recordatorio de visita                |
| `FL-014` | Registro de inasistencia              |
| `FL-015` | Solicitud de asesor                   |
| `FL-016` | Toma de conversación por asesor       |
| `FL-017` | Devolución de conversación al bot     |
| `FL-018` | Recepción y revisión de pago          |
| `FL-019` | Confirmación de reserva               |
| `FL-020` | Cancelación de evento                 |
| `FL-021` | Gestión de queja                      |
| `FL-022` | Gestión de emergencia                 |
| `FL-023` | Cambio temporal de tema               |
| `FL-024` | Múltiples intenciones                 |
| `FL-025` | Cliente que retoma conversación       |
| `FL-026` | Baja confianza y fallback             |
| `FL-027` | Fallo de OpenRouter                   |
| `FL-028` | Fallo de calendario                   |
| `FL-029` | Recepción de archivos y multimedia    |
| `FL-030` | Cierre y reapertura                   |

---

# 5. FL-001 — Inicio y recuperación de conversación

## Objetivo

Crear o recuperar el contexto correspondiente cuando llega un mensaje.

## Disparador

Webhook válido de WhatsApp.

## Estado inicial

Puede ser:

```text
Sin conversación
NEW
BOT_ACTIVE
RESOLVED
HUMAN_ACTIVE
CLOSED
```

## Flujo principal

1. Recibir webhook.
2. Validar firma y estructura.
3. Obtener `external_message_id`.
4. Verificar idempotencia.
5. Normalizar número telefónico.
6. Buscar cliente.
7. Crear cliente provisional si no existe.
8. Buscar conversación activa.
9. Recuperar lead y evento relacionados.
10. Guardar mensaje.
11. Consultar estado de la conversación.
12. Actuar según estado.

## Decisión por estado

### Sin conversación

```text
Crear Conversation
→ NEW
→ BOT_ACTIVE
```

### `BOT_ACTIVE`

Enviar mensaje al orquestador.

### `RESOLVED`

Reabrir y pasar a `BOT_ACTIVE`.

### `HUMAN_ACTIVE`

No procesar mediante bot.

Enrutar el mensaje al asesor asignado.

### `CLOSED`

No procesar automáticamente, salvo política de reapertura.

## Mensaje duplicado

Si `external_message_id` ya existe:

* no volver a guardar;
* no clasificar;
* no responder;
* devolver éxito al proveedor.

## Servicios involucrados

* `WhatsAppAdapter`;
* `CustomerService`;
* `ConversationService`;
* `MessageService`;
* `IdempotencyService`.

## Resultado

Existe una conversación válida o el mensaje fue enrutado al asesor.

---

# 6. FL-002 — Saludo sin intención específica

## Objetivo

Dar la bienvenida e identificar la necesidad del cliente.

## Disparadores

* Hola.
* Buenos días.
* Buenas.
* Quisiera información.
* Hola de nuevo.

## Estado inicial

```text
NEW
BOT_ACTIVE
RESOLVED
```

## Flujo principal

1. Clasificar como `GREETING`.
2. Revisar si hay contexto anterior.
3. Si es cliente nuevo, enviar saludo general.
4. Si tiene un solo lead activo, puede mencionarse brevemente.
5. Si tiene varios leads, no asumir cuál desea continuar.
6. Preguntar qué desea hacer.

## Respuesta para cliente nuevo

> ¡Hola! Somos el equipo de La Ceiba Club House. Nos encantará ayudarte. ¿Qué tipo de celebración o experiencia estás planeando?

## Respuesta para cliente que regresa con un lead

> ¡Hola otra vez! La última vez estuvimos revisando una boda para aproximadamente 40 personas en diciembre. ¿Quieres continuar con esa celebración o deseas consultar algo diferente?

## Cliente con varios leads

> ¡Hola otra vez! Tenemos registradas varias conversaciones contigo. ¿Deseas continuar con la boda o con el cumpleaños que estuvimos revisando?

## Estado resultante

```text
BOT_ACTIVE
```

---

# 7. FL-003 — Consulta de información general

## Objetivo

Responder una pregunta frecuente mediante contenido aprobado.

## Disparadores

Consultas sobre:

* ubicación;
* mapa;
* parqueadero;
* capacidad;
* espacios;
* piscina;
* mascotas;
* alimentos;
* bebidas;
* licor;
* proveedores;
* alojamiento;
* cafetería;
* horarios;
* servicios;
* pagos;
* tipos de eventos.

## Estado inicial

```text
BOT_ACTIVE
COLLECTING_EVENT_DATA
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
```

## Flujo principal

1. Detectar `GENERAL_INFORMATION`.
2. Identificar subintención.
3. Guardar temporalmente el estado anterior.
4. Cambiar a `ANSWERING_INFORMATION`.
5. Consultar `KnowledgeEntry`.
6. Validar:

   * estado `APPROVED`;
   * fecha de vigencia;
   * versión.
7. Construir respuesta.
8. Enviar respuesta.
9. Revisar si existía acción pendiente.
10. Retomar flujo o pasar a `BOT_ACTIVE`.

## Ejemplo: ubicación

Cliente:

> ¿Dónde están ubicados?

Respuesta:

> Estamos en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander. También puedes encontrarnos aquí: https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw

## Ejemplo: capacidad

> La Ceiba es ideal para celebraciones íntimas de hasta aproximadamente 60 invitados. Para una experiencia más cómoda, recomendamos montajes de hasta 50 personas, dependiendo de la distribución y los servicios.

## Ejemplo: más de 60 invitados

Cliente:

> Quiero un evento para 85 personas.

Acciones:

```text
guest_count = 85
capacity_review_required = true
handoff_reason = CAPACITY_REVIEW
```

Respuesta:

> Para esa cantidad de invitados necesitamos revisar cuidadosamente la distribución y el tipo de montaje. Voy a compartir la información con nuestro equipo para confirmar qué alternativa podemos ofrecerte.

## Sin respuesta aprobada

1. No improvisar.
2. Crear handoff si la pregunta es relevante.
3. Informar:

> Para darte una respuesta correcta, necesitamos que nuestro equipo confirme esa información. Voy a compartir tu consulta con un asesor.

## Estado resultante

* estado anterior;
* `BOT_ACTIVE`;
* `WAITING_FOR_HUMAN`;
* `RESOLVED`.

---

# 8. FL-004 — Captura inicial de lead

## Objetivo

Crear una oportunidad comercial cuando el cliente expresa interés real.

## Disparadores

* Quiero hacer un evento.
* Estoy buscando un lugar.
* Quiero una boda.
* Quiero cotizar.
* Quiero conocer el lugar.

## Estado inicial

```text
BOT_ACTIVE
```

## Flujo principal

1. Detectar intención comercial.
2. Buscar un lead compatible.
3. Si no existe, crear lead:

   * estado `NEW`;
   * canal WhatsApp;
   * cliente relacionado.
4. Crear evento provisional.
5. Relacionar conversación con lead.
6. Cambiar lead a `QUALIFYING`.
7. Registrar datos entregados.
8. Calcular campos faltantes.
9. Iniciar el flujo adecuado:

   * evento;
   * cotización;
   * visita.

## Datos mínimos para crear lead

```text
customer_id
phone_number
channel
commercial_intent
```

## Regla

No es obligatorio pedir el nombre en el primer mensaje.

## Resultado

Existe un lead independiente para la oportunidad.

---

# 9. FL-005 — Recopilación de datos del evento

## Objetivo

Capturar progresivamente la información del evento sin convertir el chat en un formulario.

## Estado inicial

```text
COLLECTING_EVENT_DATA
```

## Orden recomendado

1. Tipo de evento.
2. Invitados.
3. Fecha.
4. Nombre.
5. Presupuesto.
6. Servicios.
7. Observaciones.

El orden se adapta según la información ya suministrada.

## Flujo principal

1. Cargar datos existentes.
2. Extraer todas las entidades del mensaje.
3. Validar tipos y formatos.
4. Persistir datos válidos.
5. Detectar correcciones.
6. Calcular campos faltantes.
7. Seleccionar siguiente pregunta.
8. Mantener estado mientras falten mínimos.
9. Pasar a `QUOTE_REQUEST_READY` cuando corresponda.

## Primera pregunta recomendada

> Para orientarte mejor, cuéntame qué tipo de celebración estás planeando y para cuántas personas aproximadamente.

## Pregunta de fecha

> Perfecto. ¿Ya tienes una fecha definida o todavía es flexible?

## Pregunta de nombre

> Antes de continuar, ¿con quién tenemos el gusto?

## Pregunta de presupuesto

> Para recomendarte una experiencia acorde con lo que imaginas, ¿tienes un presupuesto aproximado destinado a la celebración?

## Si no quiere informar presupuesto

> No hay problema. Podemos continuar con los demás detalles y nuestro equipo te orientará.

## Pregunta de servicios

> ¿Buscas principalmente el espacio o te gustaría una experiencia más completa con gastronomía, decoración, bebidas u otros servicios?

## Datos múltiples en un mensaje

Cliente:

> Soy Natalia, quiero una boda para 45 personas el 12 de diciembre y tengo 10 millones.

El sistema debe guardar:

```text
full_name = Natalia
event_type = WEDDING
guest_count = 45
event_date = 2026-12-12
estimated_budget = 10000000
```

El bot no debe volver a preguntarlos.

## Rango de invitados

Cliente:

> Seremos entre 40 y 50.

Guardar:

```text
guest_count_min = 40
guest_count_max = 50
guest_count_status = RANGE
```

Respuesta:

> Perfecto, registraré un estimado de entre 40 y 50 invitados. ¿Ya tienes una fecha definida?

## Fecha aproximada

Cliente:

> En diciembre.

Guardar:

```text
event_month = 2026-12
event_date_type = APPROXIMATE
```

No inventar día.

## Presupuesto inferior a referencia

Cliente:

> Tengo dos millones y medio.

Guardar:

```text
estimated_budget = 2500000
budget_range = BELOW_REFERENCE
```

Respuesta:

> Gracias por compartirnos tu presupuesto. Nuestro equipo revisará qué alternativa puede ajustarse mejor a lo que estás buscando.

## Más de 60 invitados

Crear handoff por revisión de capacidad.

## Estado resultante

* `COLLECTING_EVENT_DATA`;
* `QUOTE_REQUEST_READY`;
* `WAITING_FOR_APPOINTMENT_DATE`;
* `WAITING_FOR_HUMAN`.

---

# 10. FL-006 — Solicitud de cotización

## Objetivo

Crear una solicitud estructurada para que un asesor prepare la propuesta.

## Disparadores

* ¿Cuánto cuesta?
* Quiero cotizar.
* Mándame una propuesta.
* ¿Qué vale una boda?
* Quiero saber cuánto sale.

## Estado inicial

```text
BOT_ACTIVE
COLLECTING_EVENT_DATA
```

## Datos mínimos

```text
full_name
phone_number
event_type
date_resolved (fecha, mes, o tipo FLEXIBLE/UNKNOWN declarado)
guest_count OR guest_count_range
```

El silencio del cliente sobre la fecha no cuenta como `UNKNOWN`; si no se pronunció, `COLLECT_EVENT_DATE` sigue pendiente.

## Flujo principal

1. Detectar `QUOTE_REQUEST`.
2. Crear o recuperar lead.
3. Crear `QuoteRequest` en `DRAFT`.
4. Calcular datos faltantes.
5. Ejecutar `FL-005`.
6. Cuando estén completos:

   * generar resumen;
   * pasar a `QUOTE_REQUEST_READY`;
   * solicitar confirmación.
7. Cliente confirma.
8. Validar nuevamente los datos.
9. Cambiar solicitud a `READY`.
10. Calcular `due_at`:

    * máximo tres días hábiles.
11. Cambiar lead a `QUOTE_REQUESTED`.
12. Crear handoff `QUOTE_PREPARATION`.
13. Enviar respuesta final.

## Respuesta inicial a precio

> Cada evento en La Ceiba se diseña de manera personalizada. El valor depende principalmente de la fecha, la cantidad de invitados y los servicios que quieras incluir. ¿Qué tipo de celebración estás planeando y para cuántas personas aproximadamente?

## Resumen de confirmación

> Para confirmar: estás planeando una boda para aproximadamente 45 personas el 12 de diciembre, con interés en cena, decoración y DJ. ¿Está correcto?

## Respuesta después de confirmar

> Perfecto, la información quedó registrada. Nuestro equipo preparará una propuesta personalizada y te la compartirá por este mismo medio en un plazo de hasta tres días hábiles.

## Cliente corrige

1. No crear la solicitud lista.
2. Actualizar el dato.
3. Conservar auditoría.
4. Volver a mostrar resumen si es necesario.

## Cliente insiste en un precio inmediato

> Entiendo que quieras una referencia. En esta primera etapa, nuestras propuestas son preparadas por un asesor para que el valor corresponda realmente a tu celebración. Con la fecha, el tipo de evento y la cantidad de invitados podemos dejar la solicitud lista.

## Cliente no quiere compartir datos

> Claro. Cuando tengas más detalles, estaremos encantados de ayudarte. También puedes solicitar hablar directamente con uno de nuestros asesores.

## Operaciones prohibidas

* calcular total;
* ofrecer descuento;
* inventar rango;
* prometer precio;
* marcar cotización como enviada.

---

# 11. FL-007 — Consulta del estado de una cotización

## Objetivo

Informar el estado real de una solicitud o propuesta.

## Disparadores

* ¿Ya está mi cotización?
* ¿Cuándo me la envían?
* Sigo esperando la propuesta.
* ¿Cómo va?

## Flujo principal

1. Detectar `QUOTE_STATUS_QUERY`.
2. Identificar lead o solicitud.
3. Consultar `QuoteRequest`.
4. Consultar `Quote`, si existe.
5. Responder según estado.

## Respuestas por estado

### `DRAFT`

> Aún faltan algunos datos para completar la solicitud. Quedamos pendientes de [campo faltante].

### `READY` o `ASSIGNED`

> Tu solicitud ya está registrada y se encuentra en revisión por nuestro equipo. El plazo informado es de hasta tres días hábiles.

### `IN_PROGRESS`

> Nuestro equipo se encuentra preparando tu propuesta. Te la compartiremos por este mismo medio.

### `COMPLETED` con cotización enviada

> La propuesta ya fue preparada y enviada. Puedo ayudarte a revisar cualquier duda o comunicarte con un asesor.

### Vencida

1. Marcar incumplimiento de SLA.
2. Crear handoff prioritario.
3. Responder:

> Lamentamos la espera. Tu propuesta superó el tiempo previsto y vamos a revisar el caso con prioridad. Ya notificamos a nuestro equipo comercial.

## Escalamiento

Cuando:

* está vencida;
* no existe trazabilidad;
* el cliente manifiesta molestia;
* hay una inconsistencia.

---

# 12. FL-008 — Modificación de datos o cotización

## Objetivo

Gestionar cambios solicitados por el cliente.

## Disparadores

* Ya no son 30, son 55.
* Cambiamos la fecha.
* Quita el DJ.
* Agrega decoración.
* Necesito otra versión.

## Flujo principal

1. Detectar `MODIFY_EVENT_DATA` o `QUOTE_CHANGE_REQUEST`.
2. Identificar entidad afectada.
3. Recuperar valor anterior.
4. Normalizar nuevo valor.
5. Validar impacto.
6. Guardar corrección.
7. Crear auditoría.
8. Responder confirmando el cambio.
9. Si existe cotización enviada:

   * marcar revisión requerida;
   * crear tarea para nueva versión;
   * escalar al asesor.
10. Si existe reserva:

    * no modificar fecha automáticamente;
    * escalar.

## Ejemplo

Cliente:

> Ya no son 30, serán 55.

Respuesta:

> Perfecto, actualicé la cantidad estimada a 55 invitados.

## Cambio que supera capacidad

Cliente:

> Finalmente serán 80.

Acciones:

```text
guest_count = 80
capacity_review_required = true
handoff_reason = CAPACITY_REVIEW
```

## Cambio de fecha de evento reservado

Respuesta:

> Como la fecha ya está asociada a una reserva, este cambio debe revisarlo directamente nuestro equipo. Voy a trasladar tu solicitud a un asesor.

## Nueva versión de cotización

La versión anterior no se sobrescribe.

---

# 13. FL-009 — Solicitud de visita

## Objetivo

Recopilar y validar la fecha en la que el cliente desea conocer La Ceiba.

## Disparadores

* Quiero conocer.
* ¿Puedo ir?
* Quiero una visita.
* ¿Tienen disponibilidad el sábado?

## Estado inicial

```text
BOT_ACTIVE
```

## Flujo principal

1. Detectar `SCHEDULE_VISIT`.
2. Informar reglas:

   * martes a sábado;
   * 8:00, 9:00, 10:00 y 11:00;
   * duración 45 minutos;
   * máximo tres personas;
   * mínimo tres días de anticipación.
3. Cambiar a `WAITING_FOR_APPOINTMENT_DATE`.
4. Preguntar fecha.
5. Extraer fecha.
6. Resolver fecha relativa.
7. Confirmar fecha absoluta si es necesario.
8. Validar:

   * día permitido;
   * no festivo;
   * mínimo de anticipación;
   * fecha futura;
   * no bloqueo.
9. Consultar disponibilidad.
10. Pasar a selección de horario.

## Respuesta inicial

> Claro. Las visitas se realizan de martes a sábado a las 8:00, 9:00, 10:00 y 11:00 de la mañana. Duran 45 minutos, admiten hasta tres personas y deben programarse con mínimo tres días de anticipación. ¿Qué fecha te gustaría revisar?

## Fecha para hoy o mañana

> Para organizar adecuadamente la atención, las visitas deben programarse con mínimo tres días de anticipación. Puedo ayudarte a revisar una fecha posterior.

## Domingo o lunes

> Las visitas se realizan de martes a sábado. Puedo ayudarte a revisar el siguiente día disponible.

## Festivo

> Ese día no tenemos visitas programadas por ser festivo. Puedo mostrarte otras fechas disponibles.

## Fecha relativa

Cliente:

> El próximo sábado.

Bot:

> ¿Te refieres al sábado 8 de agosto de 2026?

No se consulta horario hasta confirmar.

---

# 14. FL-010 — Selección y confirmación de visita

## Objetivo

Permitir seleccionar un horario y crear la cita.

## Estado inicial

```text
WAITING_FOR_APPOINTMENT_SELECTION
```

## Flujo principal

1. Obtener horarios disponibles.
2. Mostrar máximo cuatro horarios.
3. Cliente selecciona.
4. Interpretar opción en contexto.
5. Guardar horario.
6. Solicitar asistentes si falta.
7. Validar máximo tres.
8. Solicitar motivo si falta.
9. Verificar nombre.
10. Generar resumen.
11. Cambiar a `APPOINTMENT_PENDING_CONFIRMATION`.
12. Solicitar confirmación.
13. Cliente confirma.
14. Revalidar disponibilidad.
15. Crear cita local.
16. Crear evento en calendario.
17. Guardar `external_calendar_id`.
18. Programar recordatorio.
19. Cambiar cita a `CONFIRMED`.
20. Cambiar conversación a `APPOINTMENT_CONFIRMED`.
21. Enviar confirmación.

## Presentación de horarios

> Para el jueves tenemos disponibles las 8:00, 9:00 y 11:00 de la mañana. ¿Cuál horario prefieres?

## Selección contextual

Cliente:

> La de las 9.

Guardar:

```text
preferred_visit_time = 09:00
```

## Más de tres personas

> Para las visitas podemos recibir hasta tres personas. ¿Podrían acompañarnos máximo tres asistentes o prefieres que el equipo revise una excepción?

Si solicita excepción, escalar.

## Resumen

> Confirmemos tu visita: jueves 13 de agosto a las 9:00 a. m., para conocer el espacio pensando en una boda, con dos asistentes. ¿Deseas que la agendemos?

## Confirmación final

> ¡Tu visita quedó confirmada! Te esperamos el jueves 13 de agosto a las 9:00 a. m. en la Calle 71 #52-34, Lagos del Cacique. La visita dura 45 minutos y un día antes te enviaremos un recordatorio.

## Conflicto durante confirmación

Si el horario fue tomado:

1. No crear cita.
2. Regresar a `WAITING_FOR_APPOINTMENT_SELECTION`.
3. Responder:

> Ese horario acaba de dejar de estar disponible. Lo siento. Para ese mismo día todavía puedo ofrecerte las opciones disponibles. ¿Cuál prefieres?

## Invariantes

```text
appointment_status = CONFIRMED
→ external_calendar_id != null
```

---

# 15. FL-011 — Reprogramación de visita

## Objetivo

Cambiar fecha y hora sin perder la cita original antes de confirmar la nueva.

## Disparadores

* Quiero cambiar mi cita.
* No puedo ir.
* Pásala para el sábado.
* Necesito otra hora.

## Flujo principal

1. Detectar `RESCHEDULE_VISIT`.
2. Buscar cita activa.
3. Si hay una sola, mostrarla.
4. Si hay varias, pedir identificarla.
5. Solicitar nueva fecha.
6. Validar fecha.
7. Consultar horarios.
8. Cliente selecciona.
9. Mostrar resumen.
10. Solicitar confirmación.
11. Revalidar disponibilidad.
12. Actualizar calendario.
13. Actualizar cita local.
14. Crear `AppointmentChange`.
15. Incrementar `reschedule_count`.
16. Cancelar recordatorio anterior.
17. Crear nuevo recordatorio.
18. Confirmar al cliente.

## Respuesta inicial

> Claro. Actualmente tienes una visita programada para el jueves 13 de agosto a las 9:00 a. m. ¿Qué nueva fecha te gustaría revisar?

## Confirmación

> La visita quedará reprogramada para el sábado 15 de agosto a las 10:00 a. m. ¿Confirmas el cambio?

## Error al actualizar

* conservar cita anterior;
* no afirmar que cambió;
* crear handoff;
* responder:

> No pudimos completar el cambio de la visita en este momento. Tu cita actual se mantiene y nuestro equipo revisará la solicitud.

---

# 16. FL-012 — Cancelación de visita

## Objetivo

Cancelar una visita únicamente después de confirmación.

## Disparadores

* Cancela mi cita.
* No voy a poder ir.
* Ya no necesito la visita.

## Flujo principal

1. Detectar `CANCEL_VISIT`.
2. Identificar cita activa.
3. Mostrar fecha y hora.
4. Preguntar si confirma.
5. Si responde no, conservar cita.
6. Si responde sí:

   * calcular anticipación;
   * cancelar en calendario;
   * cancelar localmente;
   * cancelar recordatorio;
   * registrar motivo opcional;
   * marcar `CANCELLED` o `LATE_CANCEL`;
   * confirmar al cliente.

## Confirmación

> Tienes una visita programada para el jueves 13 de agosto a las 9:00 a. m. ¿Confirmas que deseas cancelarla?

## Respuesta final

> Tu visita fue cancelada. Cuando lo desees, podemos ayudarte a revisar una nueva fecha.

## Cancelación tardía

Si faltan menos de 24 horas:

```text
appointment_status = LATE_CANCEL
```

No se reprende al cliente.

## Error del calendario

No marcar definitivamente como cancelada hasta reconciliar.

---

# 17. FL-013 — Recordatorio de visita

## Objetivo

Recordar la visita un día antes.

## Disparador

Tarea programada.

## Precondiciones

```text
appointment_status = CONFIRMED or RESCHEDULED
reminder_sent_at = null
appointment_not_cancelled = true
```

## Flujo principal

1. Consultar recordatorios pendientes.
2. Verificar cita.
3. Crear mensaje.
4. Enviar por WhatsApp.
5. Guardar mensaje.
6. Registrar `reminder_sent_at`.
7. Marcar resultado.

## Mensaje recomendado

> Hola, [nombre]. Te recordamos tu visita a La Ceiba mañana, [fecha], a las [hora]. Estamos en la Calle 71 #52-34, Lagos del Cacique. Puedes ver la ubicación aquí: https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw. La visita dura 45 minutos y te recomendamos llegar puntual. Si necesitas cancelar o reprogramar, puedes escribirnos por este medio.

## Reglas

* enviar una sola vez;
* no enviar si está cancelada;
* reemplazar recordatorio al reprogramar;
* reintentar sin duplicar.

---

# 18. FL-014 — Registro de inasistencia

## Objetivo

Registrar que el cliente no asistió y aplicar tratamiento progresivo.

## Actor

Business Manager o asesor autorizado.

## Flujo principal

1. Abrir cita.
2. Verificar que la hora pasó.
3. Seleccionar “No asistió”.
4. Cambiar a `NO_SHOW`.
5. Incrementar `no_show_count`.
6. Crear auditoría.
7. Ejecutar tratamiento por número.

## Primera inasistencia

> Hola, notamos que no pudiste acompañarnos en la visita programada. Esperamos que todo esté bien. Cuando lo desees, podemos ayudarte a revisar una nueva fecha.

## Segunda inasistencia

* permitir reprogramación;
* notificar internamente.

## Tercera inasistencia

* una nueva solicitud de visita crea handoff;
* no bloquear automáticamente.

---

# 19. FL-015 — Solicitud de asesor

## Objetivo

Registrar y enviar la conversación a una bandeja humana.

## Disparadores

* Quiero hablar con alguien.
* Pásame un asesor.
* Necesito una persona.
* Quiero hablar con Leandro.
* No me estás entendiendo.

## Flujo principal

1. Detectar `HUMAN_REQUEST`.
2. Determinar motivo.
3. Determinar horario humano.
4. Generar resumen.
5. Crear `Handoff` en `PENDING`.
6. Cambiar conversación a `WAITING_FOR_HUMAN`.
7. Enviar a bandeja.
8. Notificar al equipo.
9. Responder al cliente.

## Dentro del horario

> Claro. Voy a compartir tu conversación con nuestro equipo para que un asesor continúe contigo.

## Fuera del horario

> Tu solicitud quedó registrada. Un asesor continuará contigo dentro de nuestro horario de atención, de martes a sábado entre las 8:00 a. m. y las 4:00 p. m.

## Resumen mínimo

```text
Cliente
Teléfono
Motivo
Evento
Fecha
Invitados
Presupuesto
Servicios
Visita
Cotización
Datos faltantes
Último mensaje
Prioridad
```

---

# 20. FL-016 — Toma de conversación por asesor

## Objetivo

Asignar control exclusivo a un asesor.

## Flujo principal

1. Asesor abre bandeja.
2. Selecciona conversación.
3. Consulta resumen.
4. Presiona “Tomar conversación”.
5. Backend valida:

   * handoff disponible;
   * conversación no asignada;
   * permisos.
6. Asignar asesor.
7. Cambiar handoff:

   * `PENDING → ASSIGNED → ACCEPTED`.
8. Cambiar conversación a `HUMAN_ACTIVE`.
9. Establecer:

```text
bot_enabled = false
```

10. Permitir respuestas humanas.
11. Crear auditoría.

## Concurrencia

Si dos asesores intentan tomarla:

* solo uno gana;
* el otro recibe aviso;
* se utiliza control de versión o bloqueo.

## Invariante

```text
HUMAN_ACTIVE
→ máximo un asesor activo
→ bot_enabled = false
```

---

# 21. FL-017 — Devolución de conversación al bot

## Objetivo

Retomar la automatización después de una intervención humana.

## Flujo principal

1. Asesor registra resolución.
2. Actualiza:

   * cliente;
   * lead;
   * evento;
   * pago;
   * cotización;
   * reserva;
   * acción pendiente.
3. Selecciona “Devolver al bot”.
4. Backend valida que no exista acción humana crítica pendiente.
5. Actualiza resumen.
6. Cambia conversación a `RETURNED_TO_BOT`.
7. Elimina asignación activa.
8. Establece `bot_enabled = true`.
9. Carga contexto.
10. Cambia al estado correspondiente:

    * `BOT_ACTIVE`;
    * `COLLECTING_EVENT_DATA`;
    * `RESOLVED`.

## Regla

El bot no deberá preguntar otra vez información resuelta por el asesor.

---

# 22. FL-018 — Recepción y revisión de pago

## Objetivo

Registrar pagos informados sin confirmarlos automáticamente.

## Disparadores

* Ya pagué.
* Hice la transferencia.
* Envío de comprobante.
* Pagué el 50 %.
* ¿Ya recibieron?

## Flujo de reporte

1. Detectar `PAYMENT_MESSAGE`.
2. Identificar lead, cotización o reserva.
3. Guardar archivo o referencia.
4. Crear o actualizar `Payment`.
5. Cambiar a `PAYMENT_REVIEW`.
6. Calcular `review_due_at`:

   * máximo un día.
7. Crear handoff urgente.
8. Cambiar conversación a `WAITING_FOR_HUMAN`.
9. Enviar respuesta.

## Respuesta

> Gracias, recibimos la información de tu pago. Nuestro equipo realizará la validación y te dará confirmación en un plazo máximo de un día. La fecha quedará oficialmente separada cuando la verificación sea aprobada.

## Si no se identifica la reserva

El pago permanece sin relacionar y requiere revisión manual.

## Confirmación por asesor

1. Revisar comprobante.
2. Comparar valor.
3. Verificar recepción.
4. Marcar:

   * `PAYMENT_CONFIRMED`;
   * o `PAYMENT_REJECTED`.
5. Registrar responsable.
6. Informar al cliente.

## Prohibiciones del bot

* confirmar fondos;
* confirmar reserva;
* declarar el pago válido;
* leer datos sensibles como autorización.

---

# 23. FL-019 — Confirmación de reserva

## Objetivo

Separar oficialmente la fecha después de validar el pago.

## Actor

Asesor autorizado.

## Precondiciones

```text
quote_status = ACCEPTED or approved commercial condition
payment_status = PAYMENT_CONFIRMED
deposit_percentage = 50
event_date_available = true
terms_accepted = true
```

## Flujo principal

1. Validar pago.
2. Validar monto.
3. Validar fecha.
4. Validar que no exista reserva incompatible.
5. Crear o actualizar `Reservation`.
6. Cambiar a `RESERVED`.
7. Registrar:

   * cotización;
   * pago;
   * monto;
   * porcentaje;
   * asesor;
   * condiciones;
   * fecha.
8. Informar al cliente.
9. Actualizar lead a `WON`, si la política lo determina.
10. Crear auditoría.

## Respuesta

> Tu pago fue confirmado y la fecha quedó oficialmente separada. Nuestro equipo continuará acompañándote con los siguientes pasos de tu evento.

## Conflicto crítico

Si la fecha ya fue reservada:

* no crear reserva;
* prioridad `CRITICAL`;
* notificar Manager Leandro;
* pausar automatización;
* iniciar reconciliación.

---

# 24. FL-020 — Cancelación de evento

## Objetivo

Registrar la solicitud y aplicar la respuesta correspondiente, sin decidir excepciones automáticamente.

## Disparadores

* Quiero cancelar mi evento.
* Ya no vamos a hacer la boda.
* Necesito cancelar la reserva.
* Quiero devolución.

## Flujo principal

1. Detectar `EVENT_CANCELLATION`.
2. Identificar reserva.
3. Solicitar confirmación si la intención no es completamente clara.
4. Calcular días antes del evento.
5. Cambiar reserva a `CANCEL_REQUESTED`.
6. Crear handoff urgente.
7. Responder según plazo.

## Un mes o más

> Las solicitudes de cancelación realizadas con mínimo un mes de anticipación son revisadas directamente por nuestro equipo, de acuerdo con las condiciones de la reserva. Voy a trasladar tu solicitud a un asesor.

## Menos de un mes

> De acuerdo con nuestras condiciones, las cancelaciones realizadas con menos de un mes de anticipación no generan devolución. De todas formas, voy a compartir tu caso con nuestro equipo para que puedan orientarte.

## Excepciones

Solo un asesor o manager podrá decidir:

* devolución;
* cambio de fecha;
* saldo a favor;
* transferencia;
* compensación.

## Prohibiciones

El bot no deberá:

* aprobar devolución;
* prometer excepción;
* cancelar definitivamente la reserva;
* calcular penalidades.

---

# 25. FL-021 — Gestión de queja

## Objetivo

Responder de manera empática y escalar con prioridad.

## Disparadores

* Estoy inconforme.
* Nadie me responde.
* Esto no fue lo acordado.
* Quiero poner una queja.
* El servicio fue pésimo.

## Flujo principal

1. Detectar `COMPLAINT`.
2. Extraer:

   * tema;
   * descripción;
   * referencia;
   * solución solicitada.
3. Asignar prioridad mínima `URGENT`.
4. Crear handoff.
5. Notificar al equipo.
6. Cambiar a `WAITING_FOR_HUMAN`.
7. Enviar respuesta empática.
8. Cuando el asesor tome, pausar bot.

## Respuesta base

> Lamentamos que estés pasando por esta situación. Queremos revisar tu caso con la atención que merece. Voy a trasladar la conversación a nuestro equipo responsable.

## Prohibiciones

* discutir;
* negar;
* responsabilizar al cliente;
* prometer compensación;
* minimizar;
* responder defensivamente.

---

# 26. FL-022 — Gestión de emergencia

## Objetivo

Priorizar situaciones que afecten salud, seguridad u operación crítica.

## Disparadores

* Una persona se desmayó.
* Estoy en la puerta y nadie atiende.
* Hay un problema de seguridad.
* Tenemos doble reserva.
* Mi evento es mañana y nadie responde.
* Hay un problema con alimentos.

## Flujo principal

1. Detectar `EMERGENCY`.
2. Clasificar:

   * tipo;
   * ubicación;
   * peligro inmediato;
   * personas afectadas.
3. Asignar prioridad.
4. Crear alerta.
5. Crear handoff.
6. Notificar:

   * Manager Leandro;
   * personal disponible;
   * equipo en sitio.
7. Enviar respuesta segura.
8. Pausar el flujo ordinario.

## Emergencia física

> Contacta inmediatamente al personal presente en La Ceiba y a los servicios de emergencia. Voy a alertar al equipo responsable ahora mismo.

## Cliente presente sin atención

> Lamentamos la situación. Ya estamos alertando al equipo responsable para que puedan atenderte lo antes posible.

## Doble reserva

* prioridad `CRITICAL`;
* no prometer solución;
* preservar todos los registros;
* iniciar revisión inmediata.

---

# 27. FL-023 — Cambio temporal de tema

## Objetivo

Responder una pregunta secundaria y regresar al flujo anterior.

## Ejemplo

Cliente:

> Quiero cotizar una boda para 40 personas. Antes de seguir, ¿tienen parqueadero?

## Flujo

1. Estado original:

```text
COLLECTING_EVENT_DATA
pending_action = COLLECT_EVENT_DATE
```

2. Detectar `GENERAL_INFORMATION / PARKING`.
3. Guardar estado de retorno.
4. Pasar a `ANSWERING_INFORMATION`.
5. Responder:

> Sí, contamos con parqueadero para nuestros clientes e invitados. La disponibilidad depende de la cantidad de asistentes y del montaje del evento.

6. Retomar:

> Para continuar con la propuesta, ¿ya tienes una fecha definida?

7. Regresar a:

```text
COLLECTING_EVENT_DATA
```

## Regla

El cambio de tema no elimina datos ni acción pendiente.

---

# 28. FL-024 — Múltiples intenciones

## Objetivo

Atender mensajes que contienen más de una solicitud.

## Caso A — Cotización y visita

Cliente:

> Quiero cotizar una boda para 30 personas y también ir mañana a conocer.

Clasificación:

```text
primary_intent = QUOTE_REQUEST
secondary_intent = SCHEDULE_VISIT
```

Acciones:

1. Guardar boda y 30 invitados.
2. Informar que la visita requiere tres días.
3. Solicitar fecha válida.
4. Conservar pendiente la cotización.
5. Después de agenda, retomar datos de cotización.

## Caso B — Ubicación y precio

Cliente:

> ¿Dónde están y cuánto cuesta una boda?

Respuesta:

> Estamos en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga. Sobre la boda, el valor depende de la fecha, la cantidad de invitados y los servicios. ¿Para cuántas personas aproximadamente estás planeándola?

## Caso C — Pago y queja

Cliente:

> Ya pagué y nadie me confirma.

Clasificación:

```text
primary_intent = COMPLAINT
secondary_intent = PAYMENT_MESSAGE
priority = URGENT
```

Respuesta:

> Lamentamos la demora. Vamos a revisar la validación de tu pago con prioridad. Compartiré la conversación con nuestro equipo responsable para que continúe contigo.

## Prioridad

```text
EMERGENCY
COMPLAINT
PAYMENT_MESSAGE
EVENT_CANCELLATION
HUMAN_REQUEST
CANCEL_VISIT
RESCHEDULE_VISIT
SCHEDULE_VISIT
MODIFY_EVENT_DATA
QUOTE_REQUEST
GENERAL_INFORMATION
```

---

# 29. FL-025 — Cliente que retoma conversación

## Objetivo

Continuar una conversación anterior sin perder contexto.

## Disparador

Nuevo mensaje después de inactividad o resolución.

## Flujo principal

1. Identificar cliente.
2. Consultar conversaciones recientes.
3. Consultar leads activos.
4. Evaluar si existe:

   * un lead;
   * varios leads;
   * ninguna oportunidad activa.
5. Reabrir conversación o crear una nueva.
6. Mostrar contexto prudente.
7. Preguntar si desea continuar.

## Un lead

> La última vez estuvimos revisando una boda para aproximadamente 40 personas en diciembre. ¿Quieres continuar con esa celebración?

## Varios leads

> Tenemos registradas varias celebraciones contigo. ¿Deseas continuar con la boda o con el cumpleaños?

## Regla

No asumir que “el evento” corresponde automáticamente al lead más reciente si hay varios.

---

# 30. FL-026 — Baja confianza y fallback

## Objetivo

Resolver mensajes que no pueden interpretarse con seguridad.

## Primer fallo

1. Incrementar contador.
2. Responder:

> Quiero asegurarme de entenderte bien. ¿Buscas información, solicitar una cotización, agendar una visita o hablar con un asesor?

## Segundo fallo

> Aún no logro identificar exactamente lo que necesitas. Puedes contármelo nuevamente con tus palabras o pedir que te comuniquemos con un asesor.

## Tercer fallo

1. Crear handoff `LOW_CONFIDENCE`.
2. Cambiar a `WAITING_FOR_HUMAN`.
3. Responder:

> Voy a compartir tu conversación con nuestro equipo para que puedan ayudarte personalmente.

## Regla

Un mensaje interpretado correctamente reinicia el contador.

## Operaciones críticas

Con confianza insuficiente:

* no crear cita;
* no cancelar;
* no registrar corrección crítica;
* no cambiar reserva;
* no ejecutar pago.

---

# 31. FL-027 — Fallo de OpenRouter

## Objetivo

Continuar de manera segura cuando el proveedor de IA no responde.

## Tipos de fallo

* timeout;
* indisponibilidad;
* JSON inválido;
* esquema inválido;
* salida vacía;
* modelo no disponible;
* límite de consumo.

## Flujo principal

1. Guardar `AIExecution` fallida.
2. Verificar si el mensaje puede resolverse determinísticamente.
3. Si es FAQ:

   * responder desde conocimiento.
4. Si es opción o confirmación contextual:

   * usar máquina de estados.
5. Si necesita interpretación compleja:

   * reintentar según política.
6. Si persiste:

   * responder de forma neutra;
   * crear handoff cuando corresponda.
7. No perder el mensaje.

## Respuesta neutra

> En este momento no logramos procesar completamente tu solicitud. Tu mensaje quedó registrado y nuestro equipo podrá continuar contigo.

## Prohibición

No ejecutar una acción crítica con una salida inválida.

---

# 32. FL-028 — Fallo de calendario

## Objetivo

Evitar confirmaciones falsas o duplicadas.

## Fallo al consultar

1. No mostrar horarios inventados.
2. Crear handoff o solicitar intentar posteriormente.
3. Responder:

> En este momento no pudimos consultar la disponibilidad de visitas. Tu solicitud quedó registrada para que nuestro equipo pueda ayudarte.

## Fallo al crear cita

1. No cambiar a `APPOINTMENT_CONFIRMED`.
2. Consultar si el evento fue creado pese al error.
3. Reconciliar mediante clave de idempotencia.
4. Si no se puede determinar:

   * mantener pendiente;
   * crear handoff.

Respuesta:

> No pudimos completar la confirmación de la visita en este momento. Tu solicitud quedó registrada y nuestro equipo continuará contigo.

## Fallo al reprogramar

* conservar cita anterior;
* no confirmar nuevo horario;
* escalar.

## Fallo al cancelar

* no marcar cancelación final hasta confirmar;
* reconciliar estado externo y local.

---

# 33. FL-029 — Recepción de archivos y multimedia

## Objetivo

Guardar correctamente imágenes, documentos, audios y videos.

## Imagen de inspiración

1. Guardar archivo.
2. Clasificar `INSPIRATION_IMAGE`.
3. Asociar a evento o solicitud.
4. Responder:

> Gracias por compartir la referencia. La dejaré asociada a tu solicitud para que nuestro equipo pueda tenerla en cuenta al preparar la propuesta.

## Comprobante

Ejecutar `FL-018`.

## Audio sin transcripción

> Gracias por tu mensaje. En esta etapa podemos atenderte mejor mediante texto. También puedo compartir la conversación con un asesor.

## Documento desconocido

> Recibimos el archivo. ¿Podrías contarnos brevemente qué información contiene o qué necesitas que revisemos?

## Video

* almacenar;
* asociar;
* no analizar automáticamente;
* enviar a revisión si es necesario.

## Seguridad

* validar tamaño;
* validar MIME;
* escanear;
* acceso restringido;
* no publicar enlaces permanentes.

---

# 34. FL-030 — Cierre y reapertura

## Objetivo

Finalizar una interacción sin perder datos y permitir continuidad futura.

## Cierre por pregunta resuelta

Cliente:

> Gracias, era solo eso.

Respuesta:

> Con mucho gusto. Cuando quieras planear una celebración o conocer La Ceiba, estaremos encantados de ayudarte.

Estado:

```text
RESOLVED
```

## Pausa voluntaria

Cliente:

> Luego continúo.

Respuesta:

> Claro. La información que ya compartiste quedará registrada para que podamos continuar cuando lo desees.

## Cierre por asesor

El asesor deberá:

* registrar nota;
* actualizar datos;
* seleccionar resolver;
* liberar conversación.

## No cerrar automáticamente cuando exista

* pago en revisión;
* cancelación;
* queja;
* emergencia;
* asesor activo;
* creación de cita pendiente;
* reserva pendiente.

## Reapertura

Nuevo mensaje:

```text
RESOLVED → BOT_ACTIVE
```

## Cierre administrativo

```text
RESOLVED → CLOSED
```

Solo por acción autorizada o política.

---

# 35. Flujo integral de cotización

```text
Cliente solicita precio
        ↓
Detectar QUOTE_REQUEST
        ↓
Crear/recuperar cliente y lead
        ↓
Crear QuoteRequest DRAFT
        ↓
Extraer datos existentes
        ↓
¿Datos mínimos completos?
    ├── No → preguntar siguiente dato
    │           ↓
    │      guardar respuesta
    │           ↓
    │      volver a validar
    │
    └── Sí → generar resumen
                ↓
          solicitar confirmación
                ↓
          ¿Cliente confirma?
            ├── No → corregir y volver
            └── Sí → QuoteRequest READY
                          ↓
                    calcular due_at
                          ↓
                    crear handoff
                          ↓
                    asesor prepara propuesta
                          ↓
                    registrar Quote
                          ↓
                    enviar al cliente
```

---

# 36. Flujo integral de visita

```text
Cliente solicita visita
        ↓
Informar reglas
        ↓
Solicitar fecha
        ↓
Resolver y confirmar fecha
        ↓
Validar día, festivo y anticipación
        ↓
Consultar disponibilidad
        ↓
Mostrar horarios
        ↓
Cliente selecciona
        ↓
Solicitar asistentes y motivo
        ↓
Mostrar resumen
        ↓
Cliente confirma
        ↓
Revalidar disponibilidad
        ↓
¿Sigue disponible?
    ├── No → ofrecer nuevos horarios
    └── Sí → crear cita local
                  ↓
            crear evento externo
                  ↓
            programar recordatorio
                  ↓
            confirmar al cliente
```

---

# 37. Flujo integral de handoff

```text
Se detecta condición humana
        ↓
Determinar motivo
        ↓
Determinar prioridad
        ↓
Generar resumen
        ↓
Crear Handoff PENDING
        ↓
Conversation WAITING_FOR_HUMAN
        ↓
Enviar a bandeja
        ↓
Asesor selecciona “Tomar”
        ↓
Validar exclusividad
        ↓
Handoff ACCEPTED
        ↓
Conversation HUMAN_ACTIVE
        ↓
bot_enabled = false
        ↓
Asesor atiende
        ↓
¿Devuelve al bot?
    ├── Sí → actualizar contexto
    │          ↓
    │      RETURNED_TO_BOT
    │          ↓
    │      BOT_ACTIVE
    └── No → RESOLVED o CLOSED
```

---

# 38. Flujo integral de pago y reserva

```text
Cliente informa pago
        ↓
Guardar mensaje/comprobante
        ↓
Payment PAYMENT_REVIEW
        ↓
Crear handoff urgente
        ↓
Asesor verifica
        ↓
¿Pago válido?
    ├── No → PAYMENT_REJECTED
    │          ↓
    │      informar motivo
    │
    └── Sí → PAYMENT_CONFIRMED
                  ↓
            validar depósito 50 %
                  ↓
            validar fecha
                  ↓
            validar condiciones
                  ↓
            ¿Todo correcto?
              ├── No → revisión humana
              └── Sí → Reservation RESERVED
                            ↓
                      informar al cliente
```

---

# 39. Flujo integral de cancelación de evento

```text
Cliente solicita cancelar
        ↓
Identificar reserva
        ↓
Confirmar intención
        ↓
Calcular días antes del evento
        ↓
Reservation CANCEL_REQUESTED
        ↓
Crear handoff urgente
        ↓
¿Faltan menos de 30 días?
    ├── Sí → informar no devolución
    │
    └── No → informar revisión humana
                  ↓
            asesor decide
                  ↓
        cancelar / mantener / reprogramar
                  ↓
            registrar auditoría
```

---

# 40. Datos modificados por flujo

| Flujo                 | Entidades principales                      |
| --------------------- | ------------------------------------------ |
| Inicio                | `Customer`, `Conversation`, `Message`      |
| Información           | `Conversation`, `Message`, métricas        |
| Lead                  | `Customer`, `Lead`, `Event`                |
| Cotización            | `Lead`, `Event`, `QuoteRequest`, `Handoff` |
| Modificación          | `Lead`, `Event`, `Quote`, `AuditEvent`     |
| Visita                | `Appointment`, `Notification`, `Lead`      |
| Reprogramación        | `Appointment`, `AppointmentChange`         |
| Cancelación de visita | `Appointment`, `Notification`              |
| Handoff               | `Conversation`, `Handoff`                  |
| Pago                  | `Payment`, `Attachment`, `Handoff`         |
| Reserva               | `Reservation`, `Payment`, `Event`, `Lead`  |
| Cancelación de evento | `Reservation`, `Handoff`                   |
| Queja                 | `Handoff`, `Conversation`, `Lead`          |
| Emergencia            | `Handoff`, alertas, `AuditEvent`           |

---

# 41. Servicios de dominio requeridos

```text
CustomerService
LeadService
EventService
ConversationService
MessageService
IntentClassificationService
EntityExtractionService
KnowledgeService
QuoteRequestService
QuoteService
AppointmentService
CalendarAdapter
NotificationService
HandoffService
PaymentService
ReservationService
AttachmentService
AuditService
ConfigurationService
HolidayService
IdempotencyService
```

---

# 42. Acciones críticas y validaciones

| Acción            | Validaciones obligatorias                              |
| ----------------- | ------------------------------------------------------ |
| Crear solicitud   | Datos mínimos y confirmación                           |
| Crear cita        | Fecha, hora, asistentes, disponibilidad y confirmación |
| Reprogramar       | Cita activa, nueva disponibilidad y confirmación       |
| Cancelar visita   | Cita activa y confirmación                             |
| Confirmar pago    | Asesor autorizado                                      |
| Confirmar reserva | Pago confirmado, 50 %, fecha y condiciones             |
| Cancelar evento   | Reserva identificada y handoff                         |
| Aplicar descuento | Permiso y auditoría                                    |
| Devolver al bot   | Resolución guardada y sin pendiente crítico            |

---

# 43. Errores funcionales esperados

```text
CUSTOMER_NOT_FOUND
LEAD_NOT_FOUND
EVENT_NOT_FOUND
QUOTE_REQUEST_NOT_FOUND
APPOINTMENT_NOT_FOUND
APPOINTMENT_NOT_AVAILABLE
APPOINTMENT_DATE_INVALID
APPOINTMENT_ATTENDEE_LIMIT
CALENDAR_UNAVAILABLE
PAYMENT_NOT_FOUND
PAYMENT_NOT_CONFIRMED
RESERVATION_NOT_FOUND
RESERVATION_CONFLICT
KNOWLEDGE_NOT_APPROVED
HUMAN_HANDOFF_REQUIRED
INVALID_STATE_TRANSITION
DUPLICATE_MESSAGE
DUPLICATE_OPERATION
```

Cada error deberá tener:

* código técnico;
* mensaje interno;
* mensaje seguro para cliente;
* nivel;
* acción de recuperación;
* necesidad de handoff.

---

# 44. Métricas de los flujos

El sistema deberá medir:

* cantidad de inicios;
* preguntas frecuentes resueltas;
* leads creados;
* porcentaje de datos completados;
* solicitudes de cotización creadas;
* solicitudes abandonadas;
* visitas consultadas;
* visitas confirmadas;
* conflictos de horario;
* reprogramaciones;
* cancelaciones;
* inasistencias;
* handoffs;
* tiempo hasta asignación;
* pagos reportados;
* pagos confirmados;
* reservas confirmadas;
* cancelaciones de evento;
* quejas;
* emergencias;
* fallbacks;
* errores por integración;
* reaperturas.

---

# 45. Casos de prueba obligatorios

## Información

* ubicación;
* capacidad;
* parqueadero;
* piscina;
* servicio sujeto a proveedor;
* FAQ no aprobada.

## Cotización

* sin datos;
* datos parciales;
* datos completos;
* rango de invitados;
* fecha aproximada;
* presupuesto inferior;
* cliente que rechaza dar información;
* corrección antes de confirmar;
* cambio después de cotización.

## Agenda

* hoy;
* mañana;
* domingo;
* festivo;
* fecha válida;
* día completo;
* horario fuera del catálogo;
* más de tres asistentes;
* conflicto al confirmar;
* fallo de calendario.

## Handoff

* solicitud directa;
* fuera de horario;
* toma simultánea;
* devolución al bot;
* conversación humana sin bot.

## Pagos

* “ya pagué”;
* comprobante;
* estado pendiente;
* confirmación humana;
* rechazo;
* pago sin reserva identificada.

## Cancelaciones

* visita ordinaria;
* visita tardía;
* evento con más de un mes;
* evento con menos de un mes;
* solicitud de excepción.

## Interrupciones

* pago durante cotización;
* queja durante agenda;
* emergencia durante cualquier flujo;
* consulta informativa durante captura.

---

# 46. Criterios de aceptación

Los flujos se considerarán correctamente implementados cuando:

1. Cada flujo tenga un disparador identificable.
2. Las intenciones y entidades se validen.
3. No se repitan preguntas confirmadas.
4. Los cambios de tema conserven contexto.
5. Los múltiples datos se extraigan juntos.
6. Las fechas relativas se confirmen.
7. Las solicitudes de cotización no calculen precios.
8. Las visitas respeten todas las reglas.
9. No existan citas duplicadas.
10. Las cancelaciones requieran confirmación.
11. Los handoffs pausen el bot.
12. Solo un asesor tome una conversación.
13. Los pagos siempre pasen a revisión.
14. Las reservas requieran pago confirmado.
15. Las cancelaciones de evento siempre escalen.
16. Las quejas reciban prioridad.
17. Las emergencias interrumpan flujos ordinarios.
18. Las fallas de IA no pierdan mensajes.
19. Las fallas de calendario no produzcan confirmaciones falsas.
20. Cada acción crítica genere auditoría.
21. Los mensajes duplicados no repitan acciones.
22. Los archivos se almacenen de manera segura.
23. Los estados resultantes sean válidos.
24. Las respuestas sensibles provengan de contenido aprobado.
25. Los flujos puedan retomarse después de varios días.

---

# 47. Definición de terminado

La implementación de los flujos estará terminada cuando:

* exista el orquestador;
* exista la máquina de estados;
* existan clasificadores y extractores;
* existan validadores;
* existan servicios de dominio;
* existan contratos internos;
* exista persistencia;
* exista idempotencia;
* exista control de concurrencia;
* exista auditoría;
* existan respuestas aprobadas;
* existan pruebas unitarias;
* existan pruebas de integración;
* existan pruebas conversacionales;
* existan pruebas end-to-end;
* existan métricas;
* existan alertas;
* exista recuperación ante fallos;
* los flujos críticos funcionen sin depender completamente de IA.

---

# 48. Aprobación

Este documento queda listo como fuente oficial para:

* diseño del orquestador;
* implementación de servicios;
* prompts;
* máquina de estados;
* integración con WhatsApp;
* integración con calendario;
* panel administrativo;
* pruebas;
* auditoría;
* monitoreo.

Su aprobación implica que:

* los recorridos principales están definidos;
* las decisiones están delimitadas;
* los mensajes y validaciones están especificados;
* las operaciones críticas tienen controles;
* los errores tienen rutas de recuperación;
* el MVP puede pasar a requerimientos funcionales y arquitectura sin redefinir la experiencia conversacional.
