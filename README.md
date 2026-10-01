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

La suite usa `TEST_DATABASE_URL` y por defecto apunta a:

```text
postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba_test
```

Los helpers de test se niegan a resetear una base cuyo nombre no incluya `test`.
No usar la base operativa `ceiba` para `pytest`; ahí viven las conversaciones,
handoffs, agentes, mensajes y auditoría del entorno local.

## Despliegue continuo

Cada push a `main` dispara GitHub Actions:

1. CI levanta PostgreSQL 16, crea `ceiba_test`, instala `pip install -e ".[dev]"`,
   ejecuta `ruff check .` y luego `pytest -x -q`.
2. Si CI pasa y el evento no es un pull request, el job de deploy entra por SSH al VPS.
3. El servidor ejecuta `./deploy.sh`: actualiza el checkout a `origin/main`, construye
   `app` y `worker`, corre `alembic upgrade head` en un contenedor efímero, recarga la
   base de conocimiento, reinicia `app` y `worker`, y valida `GET /health`.

Secrets requeridos en GitHub:

| Secret | Contenido |
| --- | --- |
| `DEPLOY_SSH_KEY` | Llave privada SSH con permiso para entrar al VPS y leer el repo. |
| `DEPLOY_HOST` | Host o IP del VPS. |
| `DEPLOY_USER` | Usuario SSH que ejecuta el despliegue. |
| `DEPLOY_PATH` | Ruta absoluta del checkout productivo en el servidor. |

El `.env` de producción vive solo en el servidor y lo consume Docker Compose; no se
sube al repositorio ni a GitHub Actions.

Antes del primer despliegue de W2-b, crear el directorio persistente. La imagen actual no
declara `USER`, por lo que `app` y `worker` se ejecutan como `root` dentro del contenedor:

```bash
sudo install -d -m 0750 -o root -g root /opt/ceiba/payment-evidence
```

El volumen se monta read-write en ambos servicios como `/data/payment-evidence`. Configurar
`PAYMENT_EVIDENCE_DIR=/data/payment-evidence` y
`PAYMENT_EVIDENCE_RETENTION_DAYS=365` en el `.env` productivo. La retención queda declarada,
pero W2-b no borra archivos automáticamente.

Rollback operativo:

```bash
ssh <DEPLOY_USER>@<DEPLOY_HOST>
cd <DEPLOY_PATH>
git reset --hard <tag-o-sha>
./deploy.sh
```

Las migraciones no se revierten automáticamente. Un rollback que cruce una migración
destructiva requiere un `alembic downgrade` manual, revisado caso por caso antes de
volver a levantar la versión anterior.

Un downtime de aproximadamente 10-30 segundos por deploy es tolerable: Meta reintenta
webhooks y el dedup por `external_message_id` evita duplicados.

## Simular webhook local

Con la app local arriba y `META_APP_SECRET` definido:

```bash
python scripts/simulate_webhook.py --phone 3001112233 --text "Hola"
```

El script genera un payload realista de mensaje entrante de WhatsApp Cloud API,
lo firma con `X-Hub-Signature-256` usando HMAC-SHA256 y lo envía a
`http://localhost:8000/webhook`.

## Reiniciar una conversación local de pruebas

Para probar de nuevo con el mismo número sin borrar historial append-only:

```bash
.venv/bin/python scripts/reset_local_conversation.py --phone +573016976242
```

Sin `--execute`, el comando solo muestra un dry-run. Para aplicar el reset:

```bash
.venv/bin/python scripts/reset_local_conversation.py --phone +573016976242 --execute
```

El script se niega a correr con `ENVIRONMENT=production`. Por diseño no ejecuta
`DELETE` sobre `message` ni `audit_event`: conserva mensajes y auditoría, cierra las
conversaciones del cliente, limpia el nombre guardado, resuelve handoffs abiertos,
desactiva outbox pendiente del teléfono y registra un `audit_event` nuevo. El siguiente
mensaje entrante de ese número crea una conversación activa nueva.

## Panel admin (frontend)

1. Crear o actualizar un usuario administrador:

```bash
.venv/bin/python scripts/create_admin.py --name "Admin" --document-id "90000000"
```

2. El script solicita el PIN dos veces con `getpass`; no se pasa por argumento.
3. Abrir el panel e ingresar con cédula + PIN. La sesión dura 12 horas o hasta logout.

El panel muestra una bandeja vacía cuando no hay casos abiertos. R4 añade una ruta
determinista estrecha para peticiones textuales inequívocas de asesor, antes de IA,
sobre turnos elegibles según R2. La transferencia usa la pausa y las plantillas
vigentes; no salta trabajos bloqueados ni cubre agotamiento de fallback.
[Contrato, SHA candidato y validación R4](docs/remediation/r4-h05-explicit-human-2026-09-08/README.md).

### Operación local con WhatsApp real

Para probar con el número real de WhatsApp no se debe levantar `fake_meta_server.py`
ni configurar `WHATSAPP_API_BASE_URL=http://localhost:8081` en el worker. Ese modo
marca outbox como enviados contra el doble local y el cliente real no recibe nada.

Terminales recomendadas:

```bash
docker compose up -d db
.venv/bin/alembic upgrade head
.venv/bin/python scripts/load_knowledge.py
```

```bash
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

```bash
.venv/bin/python -m app.channel.worker
```

```bash
node frontend/server.mjs
```

La URL pública de Cloudflare debe registrarse en Meta como:

```text
https://<subdominio>.trycloudflare.com/webhook
```

La verificación de Meta usa `META_VERIFY_TOKEN`. El envío real del worker usa
`META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_GRAPH_API_VERSION` y
`WHATSAPP_API_BASE_URL`. `META_PHONE_NUMBER_ID` es el identificador numérico del
teléfono en WhatsApp Cloud API; no es el número telefónico visible.

Errores frecuentes del outbox:

- `https://graph.facebook.com/vXX.0//messages` con HTTP 400: falta
  `META_PHONE_NUMBER_ID`.
- HTTP 401 contra `/messages`: `META_ACCESS_TOKEN` está ausente, vencido, no
  corresponde al app/phone number, o no tiene permisos vigentes.
- `wamid.fake...` en mensajes salientes: el worker estaba apuntando al doble local
  de Meta, no a Graph API real.

Después de cambiar `.env`, reiniciar API y worker. Ambos cargan configuración al
arrancar.

### Operación de handoffs en el panel

La pestaña `Clientes` lista conversaciones persistidas, incluso si todavía no tienen
handoff. Desde ahí se puede tomar cualquier conversación con el botón `Tomar`.
Esa acción administrativa:

- crea un handoff si no existe uno activo;
- asigna o reasigna el caso al asesor configurado;
- mueve la conversación a `HUMAN_ACTIVE`;
- deja `bot_enabled = false`;
- registra auditoría `CONVERSATION_MANUAL_TAKEOVER`;
- permite responder por outbox desde la bandeja `Tomados`.

La pestaña `Handoffs` muestra las colas `Pendientes`, `Tomados` y `Devueltos`.
El hilo del caso tomado se actualiza por AJAX cada 3 segundos y también refresca
inmediatamente después de enviar un mensaje humano. Los mensajes del cliente que
llegan durante `HUMAN_ACTIVE` se guardan, aparecen en el panel y no disparan
respuesta automática del bot.

Reiniciar API, worker o frontend no libera ni borra un caso tomado. El estado vive
en Postgres: `conversation.state = HUMAN_ACTIVE`, `conversation.bot_enabled = false`
y `handoff.status = TAKEN`.

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
| `SELF_SERVICE_BOOKING_ENABLED` | No | `false` | Habilita BOOKING determinista de precio fijo; requiere plantillas aprobadas |
| `BOOKING_BANK_NAME` | No | vacío | Banco para instrucciones aprobadas |
| `BOOKING_ACCOUNT_TYPE` | No | vacío | Tipo de cuenta |
| `BOOKING_ACCOUNT_NUMBER` | No | vacío | Número de cuenta; obligatorio para enviar PAYMENT |
| `BOOKING_ACCOUNT_HOLDER` | No | vacío | Titular de la cuenta |
| `BOOKING_EXCLUSIVITY_KEYWORD` | No | `exclusividad` | D3: texto que bloquea en título o descripción de Calendar |
| `BOOKING_HOURS_START` | No | `12:00` | Inicio permitido en Bogotá; **pendiente confirmación Leandro** |
| `BOOKING_HOURS_END` | No | `21:00` | Fin permitido en Bogotá; **pendiente confirmación Leandro** |
| `BOOKING_MIN_LEAD_DAYS` | No | `1` | Anticipación por fecha local, en días de calendario |
| `BOOKING_DEPOSIT_PERCENT` | No | `50` | Anticipo sugerido; redondeo hacia arriba a múltiplos de COP 1.000 |

Como excepción provisional autorizada para B1b-1, las reglas `BOOKING_*` se configuran
por entorno; D3 y la ventana están pendientes de confirmación de Leandro. Los
horarios de visita, anticipacion de visitas,
asistentes, presupuesto referente y SLAs pertenecen a la futura tabla `Configuration`
descrita en `docs/product/scope.md` §18.2.

Verificación B1b-1 (solo ADMIN, sin frontend):
`GET /admin/reservations/availability?plan_id=<uuid>&starts_at=<ISO-con-zona>`.
Codificar el signo `+` como `%2B` al construir la URL. Devuelve `available`,
`blockers` (`kind` y referencia), `starts_at`, `ends_at`, `deposit_amount_cop` y
`window: {ok, reason}`. `available` exige ventana válida y ausencia de bloqueadores.
Los motivos de ventana son `TIMEZONE_REQUIRED`, `INVALID_RANGE`,
`CROSSES_MIDNIGHT`, `OUTSIDE_HOURS` y `MIN_LEAD_DAYS`; una ventana válida usa `reason=null`.
Plan inexistente: 404; plan inactivo o fecha sin zona: 422; AGENT: 403;
Calendar inaccesible o sin calendarios configurados: 503.
La consulta lee todos los IDs de `GOOGLE_FREEBUSY_CALENDAR_IDS` mediante
[Google Calendar events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).
Se requieren permisos para leer los detalles de los eventos, además de freebusy.
La consulta no crea reservas ni bloquea franjas; B2 deberá revalidar al aceptar el pago.

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

B2-1 / B1b-2 (0030 y 0031): las solicitudes no bloquean antes del pago. ADMIN
acepta un comprobante con `amount_cop > 0` y nota opcional de hasta 255 caracteres;
rechaza con nota obligatoria. Acumulado inferior al 50 % → PAYMENT_PENDING;
alcanza el anticipo y D3 libre → RESERVED → Calendar después del commit. Calendar
caído no revierte la reserva: reintento ADMIN en sync-calendar. Saldo un día antes,
NULL para pago total. Dos planes no exclusivos pueden coincidir.

ADMIN y AGENT pueden crear solicitudes manuales por teléfono sin conversación;
POST /admin/reservations recibe phone, plan_id, starts_at con zona, full_name y note
opcionales. ADMIN reprograma con PATCH /admin/reservations/{id}/schedule, cancela
y reintenta Calendar. El detalle incluye evidencias, anticipo y faltante.
El monto por evidencia se lee de la auditoría de aceptación. El panel pide el
monto verificado al aceptar; la nota es opcional al aceptar y obligatoria al rechazar.

El flujo autoservicio queda apagado por defecto. Para activarlo, Leandro publica
por versión las diez propuestas RESP-BOOKING-* DRAFT y se configuran los cuatro
datos bancarios. Si falta un dato, el bot escala y no envía instrucciones incompletas.
SELF_SERVICE_BOOKING_ENABLED apagado conserva el handoff de #34. El worker expira
cada hora las solicitudes PAYMENT_PENDING vencidas. Ejecución manual:
`.venv/bin/python scripts/expire_reservations.py`.

Las migraciones tienen downgrade de esquema completo. 0031 limpia los cuatro
pending_action nuevos y elimina booking_draft. 0030 rechaza un downgrade con
reservas manuales sin conversación: vincularlas antes, sin eliminar pagos ni auditoría.

Pendiente de Leandro: aprobación de las propuestas, valores bancarios y si 21:00
es fin del servicio o última hora de inicio. BOOKING_HOURS_END configura el fin
de ventana; el motor existente comprueba la duración completa.

B2-3 (0033) añade pre-revisión asistida de imágenes de comprobantes. Está apagada
por defecto: `PAYMENT_REVIEW_AI_ENABLED=false`. Al activarla, el worker lee imágenes
JPEG, PNG y WebP descargadas y registra propuestas inmutables; PDFs y descargas
fallidas permanentes requieren revisión manual (`SKIPPED`). Una propuesta nunca
acepta un pago, modifica una reserva ni genera mensajes al cliente. El asesor
verifica el archivo y confirma con el formulario existente. «Aceptar propuesta»
prellena el monto; el clic posterior en «Aceptar» envía el `review_id` auditado.
ADMIN puede reintentar con `POST /admin/payment-evidence/{id}/prereview`.

| Variable | Default | Uso |
| --- | --- | --- |
| `PAYMENT_REVIEW_AI_ENABLED` | `false` | Habilita worker y reintento ADMIN |
| `OPENROUTER_MODEL_VISION` | `google/gemini-2.5-flash-lite` | Modelo con entrada de imágenes |
| `PAYMENT_REVIEW_CONFIDENCE_OK` | `0.80` | Confianza alta |
| `PAYMENT_REVIEW_CONFIDENCE_MIN` | `0.50` | Confianza media |
| `PAYMENT_REVIEW_MAX_ATTEMPTS` | `2` | Intentos automáticos por comprobante; máximo 2 |

Se usa `OPENROUTER_TIMEOUT_SECONDS`; cada intento hace una llamada y un parseo
estricto, sin reintentos internos. Cada reintento humano agrega otra fila.
El modelo default acepta imágenes según [OpenRouter](https://openrouter.ai/google/gemini-2.5-flash-lite/)
y [Google](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite).
La imagen viaja como `image_url` con data URL base64. No se envían el monto
esperado ni los datos de la cuenta configurada.

Privacidad: las imágenes se envían a OpenRouter y al proveedor que atienda el
modelo. Revisar sus condiciones de retención antes de habilitar la función.
No se registran imágenes, base64, respuestas crudas ni nombres del remitente en
logs o `ai_execution`; los campos extraídos se guardan en la revisión privada.
La API muestra solo iniciales del remitente; el audit contiene códigos de checks,
propuesta e identificadores, sin PII del remitente. Esto no detecta falsificaciones.
La conciliación bancaria pertenece a B2-4.

Evaluación local: crear fuera del repositorio, o en `receipt-eval-data/` (ignorada),
un set de 30–50 comprobantes reales anonimizados y un `labels.jsonl`. Incluir Nequi,
Bancolombia, Daviplata y PSE, imágenes nítidas y borrosas, recortes y texto adicional.
Anonimizar nombres, teléfonos, identificaciones, cuentas completas y referencias
sin eliminar los últimos cuatro dígitos necesarios para las etiquetas; revisar
visualmente cada archivo y etiquetar antes de consultar el modelo.
Ejemplo de línea (todos los datos son sintéticos):

```json
{"evidence":"nequi-01.png","amount_cop":125000,"transaction_date":"2026-10-01","reference":"TX-123","destination_account_last4":"1234","bank":"Nequi"}
```

Ejecutar `.venv/bin/python -m scripts.eval_receipts /ruta/local/set --now 2026-10-01T15:00:00Z`.
Para una matriz útil de sugerencias, añadir `--reservation-json /ruta/reserva.json`
con `price_cop`, `amount_paid_cop`, `created_at` ISO con zona; opcionalmente
`--previous-references /ruta/referencias.json` (array de referencias ya aceptadas).
Las filas de la matriz provienen de aplicar las reglas a las etiquetas y las
columnas de aplicarlas a la extracción; no son una medición de autenticidad.
Sin reserva, AMOUNT es UNKNOWN y no habrá ACCEPT. Los errores se cuentan como
FAILED y como fallos de exactitud en los campos etiquetados. El reporte contiene
exactitud por campo y matriz, sin imágenes ni extracciones individuales.

CI renderiza ocho imágenes sintéticas con Pillow y mockea OpenRouter con respx.
Esto prueba payload, parser, verificaciones y aislamiento, incluida una imagen
con instrucciones maliciosas; no demuestra precisión real ni resistencia del
modelo a inyección. La precisión real se mide con el set local anterior.

Verificación: `pytest tests/payment_prereview -q`,
`npm --prefix tests/frontend test -- test_d_payment_prereview.spec.mjs` y
`make migrate-cycle`. El downgrade 0033 elimina la tabla de propuestas y su
telemetría RECEIPT_EXTRACTION; conserva pagos, reservas y audits append-only.
