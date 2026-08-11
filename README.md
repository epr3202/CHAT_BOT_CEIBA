# Asistente Conversacional La Ceiba Club House

Andamiaje inicial de FastAPI para el asistente conversacional de La Ceiba Club House.

## Levantar entorno

1. Crear el archivo local de variables:

```bash
cp .env.example .env
```

2. Levantar Postgres y la app:

```bash
docker compose up --build
```

3. Verificar salud:

```bash
curl http://localhost:8000/health
```

## Migraciones

Con la base de datos arriba:

```bash
alembic upgrade head
```

Las migraciones destructivas (`downgrade`) requieren que no haya procesos conectados a la
base de datos, incluyendo `uvicorn`, workers y sesiones de `pytest`. Si un comando de
Alembic queda colgado, diagnosticar conexiones activas antes de asumir un bug:

```bash
make audit-conns
```

Para verificar una migración de punta a punta, usar:

```bash
make migrate-cycle
```

## Tests

Instalar dependencias de desarrollo y correr la suite:

```bash
pip install -e ".[dev]"
pytest -x -q
```

## Simular webhook local

Con la app local arriba y `META_APP_SECRET` definido:

```bash
python scripts/simulate_webhook.py --phone 3001112233 --text "Hola"
```

El script genera un payload realista de mensaje entrante de WhatsApp Cloud API,
lo firma con `X-Hub-Signature-256` usando HMAC-SHA256 y lo envía a
`http://localhost:8000/webhook`.

## Pruebas locales sin Meta

Esta receta prueba el flujo completo webhook → orquestador → outbox → worker sin enviar
mensajes reales por Meta. La clasificación de intención sigue usando OpenRouter, así que
`OPENROUTER_API_KEY` debe ser una llave real.

1. Levantar la base de datos:

```bash
docker compose up -d db
```

2. Aplicar migraciones y cargar la base de conocimiento:

```bash
make migrate
.venv/bin/python scripts/load_knowledge.py
```

3. Terminal 1: levantar la API local:

```bash
uvicorn app.main:app --reload
```

4. Terminal 2: levantar el doble de Meta:

```bash
.venv/bin/python scripts/fake_meta_server.py --port 8081
```

Para ejercitar reintentos y backoff del worker en vivo:

```bash
.venv/bin/python scripts/fake_meta_server.py --port 8081 --fail-rate 0.3
```

5. Terminal 3: levantar el worker apuntando al doble de Meta:

```bash
WHATSAPP_API_BASE_URL=http://localhost:8081 .venv/bin/python -m app.channel.worker
```

6. Terminal 4: abrir el WhatsApp de terminal:

```bash
.venv/bin/python scripts/chat_simulator.py --phone +573001112233
```

Comandos útiles dentro del simulador:

- `/state`: muestra estado conversacional, acción pendiente, confirmación pendiente,
  contador de entendimiento fallido y si el bot está habilitado.
- `/handoffs`: muestra los handoffs de la conversación.
- `/dup`: reenvía el último webhook con el mismo id de mensaje; no debe producir una
  segunda respuesta.
- `/new`: rota a un teléfono aleatorio para iniciar una conversación fresca.
- `/quit`: sale del simulador.

## Variables de entorno

| Variable | Obligatoria | Default | Uso |
| --- | --- | --- | --- |
| `ENVIRONMENT` | No | `development` | Slice 0: modo de arranque y logging |
| `LOG_LEVEL` | No | `INFO` | Slice 0: nivel de logs |
| `DATABASE_URL` | Si | Ninguno | Slice 0: conexion a PostgreSQL |
| `DB_POOL_SIZE` | No | `5` | Slice 0: pool SQLAlchemy |
| `DB_MAX_OVERFLOW` | No | `5` | Slice 0: pool SQLAlchemy |
| `META_APP_SECRET` | Si | Ninguno | Slice 0: firma de webhook |
| `META_VERIFY_TOKEN` | No | `""` | Slice 0: verificacion inicial de webhook |
| `META_ACCESS_TOKEN` | Si | Ninguno | Slice 0: envio por WhatsApp Cloud API |
| `META_PHONE_NUMBER_ID` | No | `""` | Slice 0: endpoint de envio WhatsApp |
| `META_WABA_ID` | No | No leido por `Settings` | Futuro: gestion de plantillas Meta |
| `META_GRAPH_API_VERSION` | No | `v20.0` | Slice 0: URL de Graph API |
| `WHATSAPP_API_BASE_URL` | No | `https://graph.facebook.com` | Local sim: base URL para envio WhatsApp |
| `WEBHOOK_MAX_BODY_BYTES` | No | `1048576` | Slice 0: limite de body del webhook |
| `OUTBOX_POLL_INTERVAL_SECONDS` | No | `1` | Slice 0: frecuencia del worker |
| `OUTBOX_BATCH_SIZE` | No | `10` | Slice 0: tamano de lote del worker |
| `OUTBOX_SENDING_TIMEOUT_SECONDS` | No | `120` | Slice 0: reaper de filas `SENDING` |
| `OUTBOX_MAX_ATTEMPTS` | No | `5` | Slice 0: corte de reintentos outbox |
| `OUTBOX_MAX_BACKOFF_SECONDS` | No | `300` | Slice 0: techo de backoff outbox |
| `OPENROUTER_API_KEY` | Si | Ninguno | Slice 1: llamadas a IA |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | Slice 1: endpoint OpenRouter |
| `OPENROUTER_MODEL_INTENT` | No | `None` | Slice 1: clasificacion de intencion |
| `OPENROUTER_MODEL_EXTRACTION` | No | `None` | Slice 1: extraccion estructurada |
| `OPENROUTER_MODEL_DRAFTING` | No | `None` | Slice 1: borradores no sensibles |
| `OPENROUTER_MODEL_SUMMARY` | No | `None` | Slice 1: resumen para handoff |
| `OPENROUTER_TIMEOUT_SECONDS` | No | `15` | Slice 1: timeout HTTP |
| `OPENROUTER_MAX_RETRIES` | No | `1` | Slice 1: reintentos HTTP |
| `AI_CONFIDENCE_SAFE` | No | `0.85` | Slice 1: umbral de decision segura |
| `AI_CONFIDENCE_PROBABLE` | No | `0.70` | Slice 1: umbral probable |
| `AI_CONFIDENCE_UNCERTAIN` | No | `0.50` | Slice 1: umbral incierto |
| `HUMAN_HOURS_DAYS` | No | `1,2,3,4,5` | Slice 1: dias de atencion humana, weekday Python |
| `HUMAN_HOURS_START` | No | `08:00` | Slice 1: inicio de atencion humana |
| `HUMAN_HOURS_END` | No | `16:00` | Slice 1: fin de atencion humana |

Las reglas de negocio no van en variables de entorno. Horarios de visita, anticipacion,
asistentes, presupuesto referente y SLAs pertenecen a la futura tabla `Configuration`
descrita en `docs/product/scope.md` §18.2.

Limitacion conocida Slice 1: la seleccion de la plantilla de escalamiento humano distingue
dias y horas configuradas, pero no bloquea festivos. El calendario de festivos llega con
la fuente de configuracion del Slice 3.

## Checklist de humo en producción

Pasos:

1. Ejecutar migraciones con `alembic upgrade head`.
2. Levantar `app` y `worker`.
3. Verificar `GET /health`.
4. Registrar en Meta la URL pública `https://<dominio>/webhook`.
5. Usar `META_VERIFY_TOKEN` como token de verificación en Meta.
6. Enviar un mensaje desde el número real de prueba hacia el WhatsApp Business.
7. Confirmar que se crea `customer`, `conversation`, `message` INBOUND y `outbox`.
8. Confirmar que el worker marca el `outbox` como `SENT` y persiste `message` OUTBOUND.
9. Reenviar el mismo payload o repetir con el mismo `message-id` en local para validar dedup.

Logs a revisar:

- `whatsapp_webhook_accepted`
- `whatsapp_message_duplicate`
- `outbox_poll_completed`
- `outbox_send_failed`
- `outbound_message_duplicate`

Para intentos con firma inválida, revisar `audit_event` con acción
`WHATSAPP_WEBHOOK_INVALID_SIGNATURE`.
