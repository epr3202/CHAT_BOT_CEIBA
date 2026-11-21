# Frontend operativo

Panel web de operación de La Ceiba Club House. El servidor Node sirve el frontend y transmite las solicitudes autenticadas a la API FastAPI.

## Ejecutar

Backend en una terminal:

```bash
uvicorn app.main:app --reload
```

Frontend en otra:

```bash
node frontend/server.mjs
```

Abrir:

```text
http://localhost:5173
```

Variables opcionales:

- `FRONTEND_PORT`: puerto del frontend, default `5173`.
- `API_BASE_URL`: URL del backend, default `http://127.0.0.1:8000`.
- `META_APP_SECRET`: secreto usado por `server.mjs` para firmar
  `/api/webhook/simulate`. Si está definido en el proceso Node, el campo de secreto
  del panel es opcional.

La pantalla principal es seguimiento administrativo de clientes/casos. Usa
`GET /admin/conversations` para listar todas las conversaciones persistidas, no
solo las que ya tienen handoff:

- cliente y teléfono estructurados;
- conversación;
- estado conversacional;
- último mensaje registrado;
- estado del handoff si existe;
- asesor asignado;
- prioridad;
- motivo;
- última actividad;
- acción `Tomar` según estado y asignación del caso;
- filtro por estado conversacional;
- filtro `Mis conversaciones` para la sesión autenticada.

Las etiquetas de presentación viven en `labels.mjs`, con un diccionario por
enumeración. `label(kind, value)` devuelve la etiqueta española o un elemento
`code` con el valor desconocido (sin interpretar HTML); un dato vacío se muestra
como `Sin dato`. Los filtros y formularios conservan los valores de la API.
Los resúmenes traducen sus campos estructurados y prefijos de dirección, sin
modificar nombres ni mensajes de los clientes. Las fechas usan `es-CO`, formato
corto de fecha y hora y zona `America/Bogota`, independiente del navegador.

El panel también cubre estas superficies actuales del backend:

- salud de API;
- simulación de webhook WhatsApp firmado;
- reenvío duplicado del último webhook;
- listado de conversaciones;
- toma directa de conversaciones elegibles con sesión de `ADMIN` o `AGENT`;
- listado de handoffs por estado;
- tomar handoff;
- chat de handoff con polling AJAX;
- enviar respuesta humana vía outbox;
- devolver conversación al bot.

## Autenticación

El panel usa login con cédula + PIN contra `POST /admin/login`. El token de sesión se
guarda en `sessionStorage` bajo `ceiba.sessionToken`; al cargar se eliminan claves
legadas de `localStorage` como `ceiba.agentDocumentId` y `ceiba.adminToken`.

Crear el primer administrador:

```bash
.venv/bin/python scripts/create_admin.py --name "Admin" --document-id "90000000"
```

Un `ADMIN` crea usuarios con `POST /admin/agents` y luego asigna o restablece
credenciales con `POST /admin/agents/{id}/credentials`. El PIN mínimo es de 6
caracteres y solo se conserva como bcrypt.

El panel conserva en `localStorage` preferencias de vista, bandeja, filtros de
conversaciones y `Mis conversaciones`. Reiniciar frontend, backend, worker o
Cloudflare no debe sacar un caso tomado de la bandeja mientras la base Postgres se
conserve.

## Vistas operativas

### Conversaciones

Lista conversaciones de `GET /admin/conversations`. Esta vista sirve como bandeja
general de operación:

- conversaciones sin handoff aparecen con su estado conversacional actual;
- conversaciones con handoff muestran estado `Pendiente`, `Asignado` o `Devuelto`;
- el botón **Tomar para responder** en una conversación con bot llama `POST /admin/conversations/{conversation_id}/take`;
- tomar una conversación elegible crea un `Handoff(reason=MANUAL_TAKEOVER)`,
  pausa el bot y mueve la conversación a `HUMAN_ACTIVE`;
- la toma directa siempre queda asignada al usuario autenticado;
- la toma directa no envía mensaje automático al cliente;
- el historial de tomas/devoluciones se carga al abrir el detalle del caso;
- si la conversación está en `WAITING_FOR_HUMAN`, se debe tomar el handoff
  pendiente existente;
- seleccionar el nombre abre el hilo. En móvil, **Volver** regresa a la lista y devuelve el foco al contacto;
- el historial y la respuesta comparten una columna. Cada conversación conserva su borrador en memoria hasta cerrar sesión;
- **Enviar** y Ctrl+Enter encolan la respuesta. El texto se conserva si la API devuelve error. Solo el responsable del caso tomado puede responder o devolverlo al bot;
- la búsqueda y los filtros se aplican en la API antes de paginar. **Cargar más** continúa el listado. Los contadores corresponden a los casos cargados;
- un administrador puede reasignar un caso tomado a otro agente activo y registrar el motivo.

**Todas** reúne las conversaciones de todo el equipo. El selector **Estado** permite buscar pendientes por tomar, casos con asesor y casos devueltos al bot. **Mis conversaciones** muestra exclusivamente las que el usuario de la sesión tiene tomadas y en atención. La búsqueda por texto opera dentro de la lista seleccionada. Quien tenía abierta la antigua bandeja humana vuelve a **Mis conversaciones**. Su filtro de asignación anterior sigue disponible en **Todas**.

Al tomar el caso, el panel abre **Mis conversaciones** y enfoca el editor del mismo hilo. Al devolverlo al bot o reasignarlo a otro asesor se retira de la lista personal. El resumen de escalamiento, la prioridad y las acciones de asignación se consultan en Conversaciones. Mientras el panel está visible, el historial abierto se actualiza cada tres segundos y la lista personal cada quince. Al volver a la pestaña se vuelven a consultar las asignaciones.

### Apertura y entrega de mensajes

El indicador **Sin abrir** cuenta los entrantes que el asesor de la sesión todavía no ha visto. Al mostrarse una burbuja en el área visible del hilo se registra la primera apertura. La migración `20261120_0040` crea `agent_message_open` con clave compuesta de asesor y mensaje. Los mensajes anteriores empiezan sin una apertura acreditada. La lista, la simple consulta del historial por API o la lectura por otro asesor conservan el contador personal.

Los salientes ya enviados muestran **Leído por el contacto** al recibir el acuse `read` del proveedor. En ausencia de acuse muestran **Sin confirmación de lectura**. El outbox conserva sus estados de pendiente, envío en curso, fallo, supresión, revisión y descarte.

### Calendario y comprobantes

En **Calendario**, cada día muestra títulos de eventos. Al seleccionar una fecha se abre su agenda lateral, y al pulsar un evento se ve la descripción completa. Las flechas del teclado permiten cambiar de día. Las visitas vinculadas se distinguen de las reservas y los eventos. El administrador también puede revisar las visitas locales y administrar bloqueos y festivos. Para una reserva vinculada, la fecha y el horario proceden del intervalo del evento sincronizado en Bogotá. Los datos comerciales de la solicitud permanecen en su expediente. Las horas se presentan en Bogotá. Las fechas de fin de los eventos de día completo son exclusivas. Una incidencia al leer los calendarios se muestra como error y permite reintentar con **Actualizar**.

La API usa el adaptador existente. Con `CALENDAR_ADAPTER=google` se necesitan la cuenta de servicio y los permisos de lectura de eventos de los calendarios elegidos. `GOOGLE_AGENDA_CALENDAR_IDS` admite una lista separada por comas. Si está vacía se muestra el calendario principal `GOOGLE_CALENDAR_ID`. Un calendario configurado únicamente en `GOOGLE_FREEBUSY_CALENDAR_IDS` aporta ocupación y conserva la privacidad de sus títulos y descripciones. La vista consulta un máximo de 42 días por petición.

En **Comprobantes** y en el detalle de una reserva, **Monto verificado (COP)** se rellena con la propuesta válida de la última pre-revisión completada. El asesor puede editarla. **Aceptar** registra el importe que queda en el campo y la referencia de la pre-revisión. Si falta el monto o la lectura indica otra moneda, el campo permite entrada manual.

**Ver comprobante** abre JPEG, PNG, WebP o PDF dentro del panel usando el mismo permiso administrativo que la descarga. En PDF hay controles de página. **Descargar**, pre-revisar, aceptar y rechazar siguen siendo acciones independientes. El visor sirve PDF.js desde `frontend/vendor/pdfjs`; la imagen o el documento se procesa en el navegador.

### Gestión por entidad

| Sección | Acciones del panel |
|---|---|
| Agentes | Crear, consultar ficha, editar nombre y rol, asignar o cambiar credenciales, activar y desactivar. El historial se conserva. |
| Conversaciones | Consultar Todas o Mis conversaciones, tomar, responder, reasignar como administrador y devolver al bot. |
| Comprobantes | Consultar y revisar evidencia, visualizar o descargar el archivo disponible y registrar la decisión humana. |
| Planes y reservas | Editar planes existentes, consultar disponibilidad, crear manualmente, filtrar, ver detalle, reprogramar, cancelar y reintentar la sincronización elegible. |
| Catálogos | Consultar categorías y archivos, cargar PDF y gestionar sus asociaciones y estado conforme al rol. |
| Avisos a asesores | Consultar destinatarios y entregas, crear o editar destinatarios y solicitar prueba según permisos. |
| Calendario | Leer eventos y visitas, crear/consultar/editar/retirar un bloqueo de fecha y registrar un festivo manual. |

### Simulador

El simulador firma un payload local y lo envía al backend por `/webhook`. Es útil
para validar deduplicación y flujo local. No debe confundirse con WhatsApp real:
para WhatsApp real se debe usar Cloudflare, webhook configurado en Meta y worker
sin `WHATSAPP_API_BASE_URL=http://localhost:8081`.

## Persistencia y reinicios

El navegador solo conserva token de sesión en `sessionStorage` y preferencias locales.
Los casos operativos
viven en Postgres. Reiniciar API, worker, frontend o Cloudflare no cambia:

```text
conversation.state
conversation.bot_enabled
handoff.status
handoff.assigned_to
message
outbox
audit_event
```

Por eso un caso tomado sigue tomado después de reiniciar procesos, siempre que no se
borre la base de datos.

El [inventario del panel](../docs/testing/panel-operativo.md) relaciona los destinos de navegación con las operaciones HTTP y las comprobaciones del rediseño.
