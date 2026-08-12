# Frontend operativo

Panel local para operar las funcionalidades disponibles del MVP sin modificar el
backend.

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
- acción `Tomar` disponible para cualquier conversación.
- filtro por estado conversacional;
- filtro `Mis conversaciones` cuando se usa token de agente.

El panel también cubre estas superficies actuales del backend:

- salud de API;
- simulación de webhook WhatsApp firmado;
- reenvío duplicado del último webhook;
- listado de conversaciones;
- toma directa de conversaciones elegibles con token individual de agente;
- listado de handoffs por estado;
- tomar handoff;
- chat de handoff con polling AJAX;
- enviar respuesta humana vía outbox;
- devolver conversación al bot.

## Autenticación

El panel separa dos credenciales:

- `Cédula agente`: cédula registrada para el asesor con `POST /admin/agents`.
  Se guarda en `localStorage` bajo `ceiba.agentDocumentId`, se valida con
  `GET /admin/me` y define la identidad usada para tomar conversaciones, tomar
  handoffs, responder y devolver. En Postgres no se guarda la cédula en claro:
  solo se persiste su `token_hash`.
- `Token admin`: `ADMIN_API_TOKEN`, reservado para vistas y acciones de gestión.
  Se guarda en `sessionStorage` bajo `ceiba.adminToken`. Si existe un valor antiguo
  en `localStorage`, el panel lo migra a `sessionStorage` y elimina la copia
  persistente al cargar.

Crear o actualizar un asesor para que use su cédula como credencial:

```bash
curl -X POST http://127.0.0.1:8000/admin/agents \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Emerson","document_id":"1020304050"}'
```

La respuesta devuelve `token` con esa cédula una sola vez por compatibilidad con el
flujo de tokens, pero la base solo conserva el hash.

## Vistas operativas

### Conversaciones

Lista conversaciones de `GET /admin/conversations`. Esta vista sirve como bandeja
general de operación:

- conversaciones sin handoff aparecen con su estado conversacional actual;
- conversaciones con handoff muestran estado `Pendiente`, `Asignado` o `Devuelto`;
- el botón `Tomar` llama `POST /admin/conversations/{conversation_id}/take`;
- tomar una conversación elegible crea un `Handoff(reason=MANUAL_TAKEOVER)`,
  pausa el bot y mueve la conversación a `HUMAN_ACTIVE`;
- la toma directa requiere token individual de agente y no envía mensaje
  automático al cliente;
- si la conversación está en `WAITING_FOR_HUMAN`, se debe tomar el handoff
  pendiente existente;
- el botón `Responder` abre la bandeja `Tomados` y enfoca el handoff cuando aplica.

### Handoffs

La bandeja humana mantiene las colas históricas por estado:

- `Pendientes`: handoffs creados por el bot u operación, todavía sin asesor activo;
- `Tomados`: conversaciones en atención humana;
- `Devueltos`: casos que ya regresaron al bot.

En `Tomados`, cada tarjeta muestra dos fuentes:

- resumen determinístico del momento de escalamiento o toma manual;
- hilo de chat vivo consultado con `GET /admin/conversations/{conversation_id}/messages`.

El hilo usa polling AJAX cada 3 segundos mediante `setInterval`. También se refresca
después de presionar `Enviar`. Esto permite ver mensajes nuevos del cliente sin
recargar la página mientras el bot permanece pausado.

Estados de mensajes salientes:

- mensajes ya materializados como `Message OUTBOUND` aparecen como burbujas
  salientes sin estado adicional;
- filas `outbox` todavía no enviadas aparecen como salientes con `pending`,
  `sending` o `failed`;
- si el worker falla contra Meta, el hilo permite ver que el mensaje fue escrito,
  aunque la investigación técnica se hace en `outbox.last_error`.

### Simulador

El simulador firma un payload local y lo envía al backend por `/webhook`. Es útil
para validar deduplicación y flujo local. No debe confundirse con WhatsApp real:
para WhatsApp real se debe usar Cloudflare, webhook configurado en Meta y worker
sin `WHATSAPP_API_BASE_URL=http://localhost:8081`.

## Persistencia y reinicios

El navegador solo conserva token admin y preferencias locales. Los casos operativos
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
