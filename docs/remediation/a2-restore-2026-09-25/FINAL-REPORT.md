# A2 — Restauración y recuperación

**Estado: CERRADO — ocho criterios verificados en una restauración independiente de A12.**

Inicio: 20260925T015452Z. Fin: 2026-09-25T01:55:05.457756+00:00.
Autoridad: sección A2 de `/home/emerson/SCOPE (1).md`, titulado SCOPE.md,
y procedencia del checkpoint definida por A12. No se modifican los criterios.

## Criterios de aceptación

| # | Estado | Evidencia ejecutada |
|---|---|---|
| 1 | ✅ | .dump.gpg no vacío, 1698156 bytes; SHA-256 calculado en este pase y coincidente con A12 y el fichero .sha256 adyacente. |
| 2 | ✅ | gpg --batch --decrypt → pg_restore --list: GPG=0, pg_restore=0, resultado combinado=0; lista no vacía. Lectura completa con drenaje en memoria, detallada abajo. |
| 3 | ✅ | Restore en nuevo PostgreSQL 16.15 temporal usando --exit-on-error --no-owner --no-privileges: GPG=0, pg_restore=0, resultado combinado=0. |
| 4 | ✅ | SELECT version_num FROM public.alembic_version devuelve una sola revisión: 20260910_0027. Sin migraciones en A2. |
| 5 | ✅ | Los conteos de message, audit_event, customer, conversation, inbox_job, outbox y lead coinciden exactamente con el origen/checkpoint derivado registrado por A12. |
| 6 | ✅ | 33 foreign keys y 39 índices únicos (incluidas PK, UNIQUE y parciales) comprobados: cero violaciones, todos validados/válidos y listos. |
| 7 | ✅ | Evidencia revisada antes de guardar: metadatos, SQL de agregación, conteos y resultados; sin filas, PII, DSN ni valores de secretos. |
| 8 | ✅ | Producción y staging persistente solo inspeccionados en READ ONLY; no fueron borrados, recreados ni usados como destino. Nueva DB temporal eliminada. |

## Archivo seleccionado y procedencia

- Archivo: `/var/backups/ceiba-staging/20260925T013333111699Z.dump.gpg`.
- Tamaño: **1698156 bytes**.
- SHA-256: `0d3cc984c38f5a51e0072e224ed55efc64e7cc67b2c04f973d291745c44fcc8a`.
- Permisos: archivo 0600; directorio de backup configurado en operations.json y target.json.
- Los dos archivos de configuración coinciden en los campos de operación; no se cambiaron.
- Referencia: `docs/remediation/a12-checkpoint-2026-09-25/FINAL-REPORT.md`.
- SHA-256 del informe A12 verificado: `57781a773ea5ea6c6c4cb11e890fa6611bc8930a4f0b4aa10d46d2ed5db31f99`.

El checkpoint fue generado en A12 desde una copia aislada de producción, migrada allí
con la cadena existente hasta 0027. A2 seleccionó ese archivo y no generó otro backup.
La comparación usa los conteos registrados en esa copia al generar el checkpoint,
no los datos actuales de producción. El estado productivo en 0024 no se modificó.

## Separación del destino

| Metadato | Resultado |
|---|---|
| Contenedor creado para este pase | `ceiba-a2-20260925t015452z` |
| ID | `fc3fd8d0b021e12f2ed655f87e77759d7482cc454d95d2700154566156bcb5e5` |
| PostgreSQL | `16.15 (Debian 16.15-1.pgdg13+2)` |
| Imagen local usada | `sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` |
| system_identifier temporal | `7689285502829776940` |
| Red | network_mode=none, sin IP externa ni puertos publicados |
| Datos | PGDATA y socket en tmpfs; cero binds/volúmenes operacionales |
| Aplicación/consumidores | No iniciados |
| Migraciones/bootstrap de aplicación | No ejecutados |

La DB destino se creó exclusivamente para esta restauración; no se reutilizó la DB
temporal de A12, ya eliminada, ni la DB persistente de staging.

## Comandos y códigos de salida

El cliente PostgreSQL se ejecutó en el contenedor temporal porque no está instalado
en el host. Todas las variables de conexión del restore apuntaron al destino temporal.

| Operación | Códigos |
|---|---|
| SHA-256 del checkpoint, sidecar y referencia A12 | comprobaciones exitosas |
| gpg --batch --decrypt <checkpoint> → pg_restore --list | 0 / 0 |
| gpg --batch --decrypt <checkpoint> → pg_restore --exit-on-error --no-owner --no-privileges | 0 / 0 |
| SELECT version_num FROM public.alembic_version | 0 |
| Presencia y conteos de las siete tablas | todas 0 |
| Consultas de foreign keys y unique constraints | todas 0 |
| docker rm -f <ID exclusivo del temporal A2> | 0 |
| Inspección final de limpieza, checksum y continuidad operacional | 0 |

Comando del restore:
```sh
gpg --batch --decrypt <checkpoint> |
  docker exec -i <A2-temporal> pg_restore --exit-on-error \
    --no-owner --no-privileges -U <rol-temporal> -d <DB-temporal>
```

Se observó y exigió el código de salida de ambos procesos. Un código distinto de 0
abortaba la comprobación y el cierre.

### Lista y drenaje de la tubería

Se ejecutaron `gpg --batch --decrypt <checkpoint>` y `pg_restore --list` conectados
por pipe. Se reutilizó el manejo de lectura completa documentado en A12:
pg_restore puede terminar al leer el índice antes de que GPG termine de escribir.
El padre mantuvo abierto el lector y descartó los bytes restantes en memoria antes
de esperar a GPG. No se ocultaron errores ni se guardó un dump descifrado.

```python
decrypt = subprocess.Popen(
    ["gpg", "--batch", "--decrypt", checkpoint],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
)
verify = subprocess.run(
    ["docker", "exec", "-i", temporary, "pg_restore", "--list"],
    stdin=decrypt.stdout, capture_output=True,
)
while decrypt.stdout.read(65536):
    pass
decrypt.stdout.close()
decrypt_rc = decrypt.wait()
assert decrypt_rc == 0 and verify.returncode == 0
```

En este pase: **GPG=0, pg_restore --list=0**, lista no vacía;
1309986 bytes restantes descartados en memoria.
El restore consumió el archivo íntegro sin bytes restantes y terminó 0/0.

No se afirma que una tubería sin este drenaje esté acreditada como exitosa:
A12 observó Broken pipe en esa variante. El procedimiento del repositorio no se modificó.

## Revisión y conteos comparados

Consulta ejecutada en READ ONLY:
```sql
SELECT version_num FROM public.alembic_version;
```
Resultado único: `20260910_0027`.

| Tabla public | Origen/checkpoint A12 | Restauración independiente A2 | Coincide |
|---|---:|---:|---|
| message | 6625 | 6625 | sí |
| audit_event | 6417 | 6417 | sí |
| customer | 45 | 45 | sí |
| conversation | 181 | 181 | sí |
| inbox_job | 0 | 0 | sí |
| outbox | 3289 | 3289 | sí |
| lead | 27 | 27 | sí |

Se ejecutaron `SELECT to_regclass('public.<tabla>') IS NOT NULL;` y
`SELECT count(*) FROM public.<tabla>;` para cada nombre indicado, mediante
psql -X -qAt -v ON_ERROR_STOP=1, dentro de BEGIN READ ONLY / COMMIT.
inbox_job existe y su conteo cero coincide con el checkpoint migrado; no se inventaron filas.

## Integridad

Se enumeraron las foreign keys de public en pg_constraint y los índices únicos
en pg_index. Las consultas contaron referencias sin padre y grupos duplicados,
respetando columnas nulas, MATCH SIMPLE/FULL, expresiones, predicados parciales y
NULLS NOT DISTINCT. Se comprobó convalidated para FK e indisvalid/indisready para
índices únicos. No se alteraron constraints ni se reconstruyeron índices.

| Tipo | Constraint o índice | Violaciones/grupos duplicados |
|---|---|---:|
| foreign_key | `agent_session_agent_id_fkey` | 0 |
| foreign_key | `ai_execution_conversation_id_fkey` | 0 |
| foreign_key | `appointment_assigned_manager_id_fkey` | 0 |
| foreign_key | `appointment_change_appointment_id_fkey` | 0 |
| foreign_key | `appointment_customer_id_fkey` | 0 |
| foreign_key | `appointment_lead_id_fkey` | 0 |
| foreign_key | `catalog_event_type_map_catalog_asset_id_fkey` | 0 |
| foreign_key | `catalog_send_catalog_asset_id_fkey` | 0 |
| foreign_key | `catalog_send_lead_id_fkey` | 0 |
| foreign_key | `catalog_send_outbound_message_id_fkey` | 0 |
| foreign_key | `conversation_customer_id_fkey` | 0 |
| foreign_key | `event_lead_id_fkey` | 0 |
| foreign_key | `event_service_request_event_id_fkey` | 0 |
| foreign_key | `fk_conversation_active_lead_id_lead` | 0 |
| foreign_key | `fk_conversation_assigned_agent_id_agent` | 0 |
| foreign_key | `fk_handoff_assigned_agent_id_agent` | 0 |
| foreign_key | `fk_outbox_catalog_asset_id_catalog_asset` | 0 |
| foreign_key | `handoff_conversation_id_fkey` | 0 |
| foreign_key | `inbox_job_conversation_id_fkey` | 0 |
| foreign_key | `inbox_job_message_id_fkey` | 0 |
| foreign_key | `lead_customer_id_fkey` | 0 |
| foreign_key | `message_conversation_id_fkey` | 0 |
| foreign_key | `message_customer_id_fkey` | 0 |
| foreign_key | `message_provider_status_message_id_fkey` | 0 |
| foreign_key | `outbox_conversation_id_fkey` | 0 |
| foreign_key | `outbox_message_id_fkey` | 0 |
| foreign_key | `payment_evidence_conversation_id_fkey` | 0 |
| foreign_key | `payment_evidence_customer_id_fkey` | 0 |
| foreign_key | `payment_evidence_lead_id_fkey` | 0 |
| foreign_key | `payment_evidence_message_id_fkey` | 0 |
| foreign_key | `payment_evidence_reviewed_by_agent_id_fkey` | 0 |
| foreign_key | `quote_request_event_id_fkey` | 0 |
| foreign_key | `quote_request_lead_id_fkey` | 0 |
| unique | `agent_name_key` | 0 |
| unique | `agent_pkey` | 0 |
| unique | `agent_session_pkey` | 0 |
| unique | `agent_session_token_hash_key` | 0 |
| unique | `ai_execution_pkey` | 0 |
| unique | `alembic_version_pkc` | 0 |
| unique | `appointment_change_pkey` | 0 |
| unique | `appointment_external_calendar_id_key` | 0 |
| unique | `appointment_pkey` | 0 |
| unique | `audit_event_pkey` | 0 |
| unique | `blocked_date_pkey` | 0 |
| unique | `catalog_asset_pkey` | 0 |
| unique | `catalog_event_type_map_pkey` | 0 |
| unique | `catalog_send_pkey` | 0 |
| unique | `conversation_pkey` | 0 |
| unique | `customer_phone_number_key` | 0 |
| unique | `customer_pkey` | 0 |
| unique | `event_pkey` | 0 |
| unique | `event_service_request_pkey` | 0 |
| unique | `handoff_pkey` | 0 |
| unique | `holiday_pkey` | 0 |
| unique | `inbox_job_pkey` | 0 |
| unique | `knowledge_entry_pkey` | 0 |
| unique | `lead_pkey` | 0 |
| unique | `message_external_message_id_key` | 0 |
| unique | `message_pkey` | 0 |
| unique | `message_provider_status_pkey` | 0 |
| unique | `outbox_pkey` | 0 |
| unique | `payment_evidence_pkey` | 0 |
| unique | `quote_request_pkey` | 0 |
| unique | `uq_agent_document_id` | 0 |
| unique | `uq_appointment_active_slot` | 0 |
| unique | `uq_catalog_asset_event_type` | 0 |
| unique | `uq_catalog_send_proactive_lead_asset` | 0 |
| unique | `uq_inbox_job_message` | 0 |
| unique | `uq_knowledge_entry_code_version` | 0 |
| unique | `uq_payment_evidence_message_id` | 0 |
| unique | `uq_provider_status` | 0 |
| unique | `webhook_event_pkey` | 0 |

**Resultado: 33 FK y 39 índices únicos; cero violaciones.**
Todas las comprobaciones retornaron 0. Los nombres son metadatos de esquema,
no valores de claves ni datos personales.

<details>
<summary>Consultas exactas de integridad ejecutadas, sin filas ni valores de negocio</summary>

Cada consulta siguiente terminó con código 0 y devolvió únicamente el agregado 0.

```sql
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.agent_session c WHERE (c."agent_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.agent p WHERE p."id" = c."agent_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.ai_execution c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.appointment c WHERE (c."assigned_manager_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.agent p WHERE p."id" = c."assigned_manager_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.appointment_change c WHERE (c."appointment_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.appointment p WHERE p."appointment_id" = c."appointment_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.appointment c WHERE (c."customer_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.customer p WHERE p."id" = c."customer_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.appointment c WHERE (c."lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.catalog_event_type_map c WHERE (c."catalog_asset_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.catalog_asset p WHERE p."catalog_asset_id" = c."catalog_asset_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.catalog_send c WHERE (c."catalog_asset_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.catalog_asset p WHERE p."catalog_asset_id" = c."catalog_asset_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.catalog_send c WHERE (c."lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.catalog_send c WHERE (c."outbound_message_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.outbox p WHERE p."id" = c."outbound_message_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.conversation c WHERE (c."customer_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.customer p WHERE p."id" = c."customer_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.event c WHERE (c."lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.event_service_request c WHERE (c."event_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.event p WHERE p."event_id" = c."event_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.conversation c WHERE (c."active_lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."active_lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.conversation c WHERE (c."assigned_agent_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.agent p WHERE p."id" = c."assigned_agent_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.handoff c WHERE (c."assigned_agent_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.agent p WHERE p."id" = c."assigned_agent_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.outbox c WHERE (c."catalog_asset_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.catalog_asset p WHERE p."catalog_asset_id" = c."catalog_asset_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.handoff c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.inbox_job c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.inbox_job c WHERE (c."message_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.message p WHERE p."id" = c."message_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.lead c WHERE (c."customer_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.customer p WHERE p."id" = c."customer_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.message c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.message c WHERE (c."customer_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.customer p WHERE p."id" = c."customer_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.message_provider_status c WHERE (c."message_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.message p WHERE p."id" = c."message_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.outbox c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.outbox c WHERE (c."message_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.message p WHERE p."id" = c."message_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.payment_evidence c WHERE (c."conversation_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.conversation p WHERE p."id" = c."conversation_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.payment_evidence c WHERE (c."customer_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.customer p WHERE p."id" = c."customer_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.payment_evidence c WHERE (c."lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.payment_evidence c WHERE (c."message_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.message p WHERE p."id" = c."message_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.payment_evidence c WHERE (c."reviewed_by_agent_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.agent p WHERE p."id" = c."reviewed_by_agent_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.quote_request c WHERE (c."event_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.event p WHERE p."event_id" = c."event_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM public.quote_request c WHERE (c."lead_id" IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM public.lead p WHERE p."lead_id" = c."lead_id"); COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.agent WHERE TRUE AND (name) IS NOT NULL GROUP BY name HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.agent WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.agent_session WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.agent_session WHERE TRUE AND (token_hash) IS NOT NULL GROUP BY token_hash HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.ai_execution WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.alembic_version WHERE TRUE AND (version_num) IS NOT NULL GROUP BY version_num HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.appointment_change WHERE TRUE AND (appointment_change_id) IS NOT NULL GROUP BY appointment_change_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.appointment WHERE TRUE AND (external_calendar_id) IS NOT NULL GROUP BY external_calendar_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.appointment WHERE TRUE AND (appointment_id) IS NOT NULL GROUP BY appointment_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.audit_event WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.blocked_date WHERE TRUE AND (blocked_date) IS NOT NULL GROUP BY blocked_date HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.catalog_asset WHERE TRUE AND (catalog_asset_id) IS NOT NULL GROUP BY catalog_asset_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.catalog_event_type_map WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.catalog_send WHERE TRUE AND (catalog_send_id) IS NOT NULL GROUP BY catalog_send_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.conversation WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.customer WHERE TRUE AND (phone_number) IS NOT NULL GROUP BY phone_number HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.customer WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.event WHERE TRUE AND (event_id) IS NOT NULL GROUP BY event_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.event_service_request WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.handoff WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.holiday WHERE TRUE AND (holiday_date) IS NOT NULL GROUP BY holiday_date HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.inbox_job WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.knowledge_entry WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.lead WHERE TRUE AND (lead_id) IS NOT NULL GROUP BY lead_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.message WHERE TRUE AND (external_message_id) IS NOT NULL GROUP BY external_message_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.message WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.message_provider_status WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.outbox WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.payment_evidence WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.quote_request WHERE TRUE AND (quote_request_id) IS NOT NULL GROUP BY quote_request_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.agent WHERE TRUE AND (document_id) IS NOT NULL GROUP BY document_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.appointment WHERE (((appointment_status)::text = ANY (ARRAY[('PENDING_CONFIRMATION'::character varying)::text, ('CONFIRMED'::character varying)::text, ('RESCHEDULED'::character varying)::text]))) AND (appointment_date) IS NOT NULL AND (start_time) IS NOT NULL GROUP BY appointment_date, start_time HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.catalog_event_type_map WHERE TRUE AND (catalog_asset_id) IS NOT NULL AND (event_type) IS NOT NULL GROUP BY catalog_asset_id, event_type HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.catalog_send WHERE (((trigger)::text = 'PROACTIVE'::text)) AND (lead_id) IS NOT NULL AND (catalog_asset_id) IS NOT NULL GROUP BY lead_id, catalog_asset_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.inbox_job WHERE TRUE AND (message_id) IS NOT NULL GROUP BY message_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.knowledge_entry WHERE TRUE AND (code) IS NOT NULL AND (version) IS NOT NULL GROUP BY code, version HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.payment_evidence WHERE TRUE AND (message_id) IS NOT NULL GROUP BY message_id HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.message_provider_status WHERE TRUE AND (provider_message_id) IS NOT NULL AND (status) IS NOT NULL AND (provider_timestamp) IS NOT NULL GROUP BY provider_message_id, status, provider_timestamp HAVING count(*) > 1) duplicates; COMMIT;
BEGIN READ ONLY; SET LOCAL statement_timeout = '30s'; SELECT count(*) FROM (SELECT 1 FROM public.webhook_event WHERE TRUE AND (id) IS NOT NULL GROUP BY id HAVING count(*) > 1) duplicates; COMMIT;
```

</details>

## Preservación y limpieza

| DB operacional | system_identifier antes/después | Resultado |
|---|---|---|
| chat_bot_ceiba-db-1 | `7673357661635788835` | Mismo ID de contenedor, imagen, StartedAt y volumen; revisión continúa 20260825_0024 |
| ceiba-staging-db-1 | `7688380279747375140` | Mismo ID de contenedor, imagen, StartedAt y volumen; alembic_version continúa ausente |

En A2 estas DB solo recibieron consultas de metadatos en READ ONLY.
La actividad normal de producción pudo continuar; no se afirma que sus datos
quedaran congelados durante el pase.

El contenedor temporal fue eliminado verificando previamente su ID y etiqueta
de propiedad A2. La inspección final encontró **cero contenedores, volúmenes y
redes con prefijo ceiba-a2-**. PGDATA residió en tmpfs y se destruyó con el contenedor.
El checkpoint cifrado permanece y su SHA-256 final sigue coincidiendo.
No se escribieron dumps en claro. El ejecutor local efímero se elimina al cerrar la evidencia.

No se modificaron app, migraciones, scripts existentes ni perfiles Compose.
No se ejecutaron despliegues, migraciones, downgrade, PITR, replicación, cambios de
motor, retención, DNS ni Cloudflare. No se inspeccionaron ramas.
No se ejecutaron pytest/ruff, commit ni push: este pase solo realiza la verificación
operativa de restore y su documentación.

## Revisión de evidencia e historial

Se revisó esta evidencia antes de guardarla. Solo contiene metadatos, nombres de
esquema, agregados y códigos de salida; no incluye credenciales, DSN, claves,
secretos, filas ni PII. La custodia GPG existente se usó sin exportar claves.

Este informe reemplaza el diagnóstico A2 abierto registrado a las
2026-09-25T01:05:44.952700+00:00 (SHA-256 anterior:
`a7cc1bf0ecc48f824b6f2a59cf76c145ef075ecec1e6efa26ad77907343ce3b5`).
Aquel diagnóstico era correcto: el directorio estaba vacío, staging sin esquema
y producción en 0024 sin inbox_job. A12 resolvió únicamente la preparación del
checkpoint mediante una copia temporal. El presente pase acredita por separado
los ocho criterios A2, sin modificar producción ni heredar el restore de A12
como resultado de A2.

**A2 CERRADO.**

