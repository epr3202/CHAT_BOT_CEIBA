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

La pantalla principal es seguimiento administrativo de clientes/casos. Usa solo
los datos disponibles hoy en `GET /admin/handoffs`:

- cliente y teléfono extraídos del resumen determinístico;
- conversación;
- estado del handoff;
- asesor asignado;
- prioridad;
- motivo;
- fechas de creación, toma o devolución;
- acciones disponibles según estado.

El panel también cubre estas superficies actuales del backend:

- salud de API;
- simulación de webhook WhatsApp firmado;
- reenvío duplicado del último webhook;
- listado de handoffs por estado;
- tomar handoff;
- enviar respuesta humana vía outbox;
- devolver conversación al bot.
