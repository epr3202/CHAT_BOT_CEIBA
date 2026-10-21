# A12 — Preparación de checkpoint compatible para A2

**Estado: CERRADO — 8/8 criterios acreditados. A2 permanece ABIERTO.**

Autoridad: sección A12 del documento local `/home/emerson/SCOPE (1).md`, titulado SCOPE.md.
Ejecución: 2026-09-25 UTC; checkpoint de origen creado a las 01:28:02,
restauración/migración y checkpoint derivado entre 01:33:17 y 01:33:35.
Checkout utilizado: `98cec43788dd886c3c78b447555c3fd7e0360717` en `/home/deploy/ceiba-staging`.
Este informe no certifica la restauración final del checkpoint derivado exigida por A2.

## Criterios cerrados

| # | Resultado | Evidencia observada |
|---|---|---|
| 1 | ✅ | App y worker del proyecto chat_bot_ceiba declaran production, apuntan a la misma DB del servicio db y comparten su red; revisión de origen 20260825_0024. Cadena existente 0024 → 0025 → 0026 → 0027 verificada por AST. |
| 2 | ✅ | Checkpoint completo cifrado de origen conservado; tamaño, SHA-256 y verificación GPG/pg_restore list registrados abajo. Ambos procesos retornaron 0 con drenaje completo de la tubería. |
| 3 | ✅ | Restore en PostgreSQL 16.15 temporal con --exit-on-error --no-owner --no-privileges: GPG=0, pg_restore=0. Identidad distinta de producción y staging. |
| 4 | ✅ | python -m alembic upgrade 20260910_0027 sobre la copia temporal: código 0; se observaron únicamente las tres transiciones autorizadas. |
| 5 | ✅ | SELECT version_num FROM alembic_version devolvió únicamente 20260910_0027. Siete tablas presentes, incluida inbox_job. |
| 6 | ✅ | Checkpoint derivado distinto del origen, cifrado, no vacío, SHA-256 registrado y listado verificado: GPG=0, pg_restore=0. |
| 7 | ✅ | Conteos de siete tablas registrados antes y después del dump derivado, idénticos. 33 foreign keys y 39 índices únicos comprobados: 0 violaciones. Evidencia revisada, sin filas ni PII ni valores de secretos. |
| 8 | ✅ | Producción usada solo para consultas READ ONLY y pg_dump; staging persistente solo inspeccionado. Identidades y arranques operacionales sin cambios. Todos los recursos temporales A12 eliminados; checkpoints cifrados conservados. |

## Checkpoints conservados

Directorio ya configurado en operations.json y target.json: `/var/backups/ceiba-staging`, modo 0700.
Destinatario y almacén GPG existentes de deploy, sin exportar ni copiar claves.
Archivos cifrados modo 0600; cada uno conserva su fichero adyacente `.sha256`.

| Uso | Archivo | Bytes | SHA-256 |
|---|---|---:|---|
| Origen producción 0024 | `/var/backups/ceiba-staging/20260925T012802095693Z.dump.gpg` | 1691083 | `25e94c1e471675d8002bd9dc9cdb50751161d05e12d1743987d8814c1a8e4d71` |
| **Derivado preparado para A2, revisión 0027** | `/var/backups/ceiba-staging/20260925T013333111699Z.dump.gpg` | 1698156 | `0d3cc984c38f5a51e0072e224ed55efc64e7cc67b2c04f973d291745c44fcc8a` |

Procedencia: producción → checkpoint de origen → restore temporal → migraciones existentes → checkpoint derivado.
No se clonaron servidores, archivos de producción, secretos ni infraestructura.

## Cadena existente ejecutada

| Archivo | down_revision | revision | SHA-256 del archivo |
|---|---|---|---|
| `alembic/versions/20260908_0025_outbox_claim_token.py` | `20260825_0024` | `20260908_0025` | `4ff599e7428130c4231409697f59ae397a26a3acc3f7ec65b5497355fd04086c` |
| `alembic/versions/20260908_0026_durable_inbox.py` | `20260908_0025` | `20260908_0026` | `363f6fa66e9ea90bfa80d48a71e32bf62c4d4f0747b7877b1f204587c8facbbe` |
| `alembic/versions/20260910_0027_outbox_admission.py` | `20260908_0026` | `20260910_0027` | `4cd2b066608c6922d78f210452c45eaf7774c5bbf30c781a51c28d62e40fbe4c` |

Se leyeron archivos del checkout actual; no se inspeccionaron ni integraron ramas.
La migración 0026 crea inbox_job sin backfill histórico; su conteo cero es observado, no simulado.

## Destino aislado y preservación operacional

- Contenedor temporal: `ceiba-a12-20260925t013317z-db`.
- PostgreSQL: `16.15 (Debian 16.15-1.pgdg13+2)`.
- Imagen: `sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`.
- system_identifier temporal: `7689279945459761196`, distinto de ambos operacionales.
- network_mode=none, sin puertos publicados; PostgreSQL escuchó solo en loopback de su namespace.
- PGDATA y socket en tmpfs; sin volúmenes persistentes ni mounts de datos operacionales.
- Ejecutor de migración efímero, filesystem de solo lectura, namespace de red del PostgreSQL temporal y código/migraciones del checkout montados RO; no se iniciaron API, worker ni consumidores.
- Se reutilizó únicamente la imagen Python/dependencias ya instalada, sin copiar secretos de contenedores.
- No se ejecutaron bootstrap del esquema de aplicación, downgrade, PITR, replicación, despliegues ni modificaciones de configuración existente.

| Recurso operacional | system_identifier antes/después | Revisión al terminar | Continuidad |
|---|---|---|---|
| chat_bot_ceiba-db-1 | `7673357661635788835` | 20260825_0024 | mismo contenedor, imagen, StartedAt y volumen |
| ceiba-staging-db-1 | `7688380279747375140` | alembic_version continúa ausente | mismo contenedor, imagen, StartedAt y volumen |

La afirmación de preservación se refiere a las operaciones de A12. La aplicación productiva siguió activa;
no se afirma que su actividad normal haya congelado los datos durante el dump consistente de pg_dump.

## Conteos de referencia para A2

Medidos en la copia migrada, sin consumidores ni escrituras concurrentes; coinciden antes y después de generar el checkpoint derivado.

| Tabla public | Antes del dump derivado | Después |
|---|---:|---:|
| message | 6625 | 6625 |
| audit_event | 6417 | 6417 |
| customer | 45 | 45 |
| conversation | 181 | 181 |
| inbox_job | 0 | 0 |
| outbox | 3289 | 3289 |
| lead | 27 | 27 |

Estos son los conteos del origen/checkpoint derivado que A2 deberá comparar con su propia restauración.

## Comandos y resultados

Se invocó la función existente `scripts.release.encrypted_backup` sin modificarla,
con el Compose del origen identificado y luego con el Compose temporal exclusivo de A12.
La función ejecutó `pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"` conectado por tubería a
`gpg --batch --encrypt --recipient <destinatario-configurado> --output <checkpoint>`.
Sus comprobaciones de pg_dump, cifrado y archivo no vacío pasaron. Los códigos de dump y
cifrado fueron 0; la validación inicial por lista encontró la incidencia descrita más abajo.

| Operación | Resultado |
|---|---|
| Consultas READ ONLY de identidad/revisión/presencia | 0 |
| pg_dump -Fc de producción → GPG encrypt | 0 / 0 |
| Validación completa checkpoint origen: GPG → pg_restore --list | 0 / 0 |
| docker compose <A12 temporal> up -d --pull never db | 0 |
| GPG → pg_restore --exit-on-error --no-owner --no-privileges | 0 / 0 |
| python -m alembic upgrade 20260910_0027, destino temporal | 0 |
| Consultas de revisión, tablas, conteos y constraints en copia | todas 0 |
| pg_dump -Fc de copia migrada → GPG encrypt | 0 / 0 |
| Validación completa checkpoint derivado: GPG → pg_restore --list | 0 / 0 |
| docker rm -f <contenedor temporal de A12> | 0 |
| Comprobación final de recursos y checksums | 0 |

Comando de restore ejecutado (nombres temporales sustituidos):
```sh
gpg --batch --decrypt <checkpoint-origen> |
  docker exec -i <A12-temporal> pg_restore --exit-on-error \
    --no-owner --no-privileges -U <rol-temporal> -d <DB-temporal>
```

Las consultas se enviaron por stdin a:
```sh
docker exec -i <contenedor> sh -c \
  'psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Consultas observadas, dentro de BEGIN READ ONLY / COMMIT:
```sql
SELECT current_setting('server_version');
SELECT system_identifier FROM pg_control_system();
SELECT version_num FROM public.alembic_version;
SELECT to_regclass('public.<tabla>') IS NOT NULL;
SELECT count(*) FROM public.<tabla>;
```
Se sustituyó <tabla> por cada uno de los siete nombres indicados; no se consultaron filas de negocio.

### Incidencia de tubería y manejo aplicado

La verificación original del script falló con `GPG=2 / pg_restore --list=0`:
pg_restore termina tras leer el índice y GPG encuentra `Broken pipe` al seguir escribiendo.
La clave sí descifra: descifrado íntegro hacia /dev/null retornó 0.
No se modificó scripts/release.py, no se ignoró el código de GPG y no se presentó
la tubería original sin drenaje como exitosa.

Para la validación de A12, el ejecutor temporal mantuvo abierto el extremo lector,
ejecutó los mismos comandos y drenó en memoria los bytes restantes antes de cerrar
la tubería y esperar a GPG. Cualquier código distinto de cero aborta. Equivalente exacto
del manejo ejecutado:
```python
decrypt = subprocess.Popen(
    ["gpg", "--batch", "--decrypt", checkpoint],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
)
verify = subprocess.run(
    ["docker", "exec", "-i", container, "pg_restore", "--list"],
    stdin=decrypt.stdout, capture_output=True,
)
while decrypt.stdout.read(65536):
    pass  # Descartar en memoria; ningún archivo descifrado.
decrypt.stdout.close()
decrypt_rc = decrypt.wait()
assert decrypt_rc == 0 and verify.returncode == 0
```

Resultados finales completos: origen 0/0 y derivado 0/0.
El restore consumió todo el archivo por sí mismo y retornó 0/0.
El script del repositorio conserva su comportamiento original; A2 deberá registrar
su propia verificación y no heredar estos resultados como certificación final.

## Comprobaciones de integridad

Se consultaron pg_constraint, pg_attribute y pg_index para construir consultas de solo lectura.
Para cada FK se contó la ausencia de padre con NOT EXISTS, respetando columnas nulas
y MATCH SIMPLE/FULL; se comprobó convalidated.
Para cada índice único (incluidos PK, UNIQUE y parciales) se contaron grupos duplicados
con GROUP BY/HAVING count(*) > 1, respetando expresiones, predicados y NULLS NOT DISTINCT;
se comprobaron indisvalid e indisready. No se reconstruyeron índices ni se alteraron constraints.

Todas las consultas finalizaron con código 0:

| Tipo | Nombre | Violaciones/grupos duplicados |
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

Total: **33 foreign keys y 39 índices únicos; cero violaciones**, todos validados/válidos y listos según corresponda.

## Limpieza y revisión de evidencia

Se eliminaron el contenedor de migración, los contenedores PostgreSQL temporales creados
en ambos intentos y sus definiciones temporales en /dev/shm.
La comprobación final devuelve cero contenedores, volúmenes, redes y directorios
temporales con prefijo ceiba-a12-. Solo se eliminaron recursos propios de A12.
No se guardaron dumps en claro; PGDATA temporal residió en tmpfs y se destruyó al eliminar el contenedor.
Ambos checkpoints cifrados y sus SHA-256 se conservaron. El ejecutor local temporal se elimina al cerrar la evidencia.

Se revisó el informe antes de guardarlo: contiene únicamente metadatos, nombres de esquema,
conteos y resultados. No contiene DSN, credenciales, claves, PII ni filas.
El diff de app, alembic, scripts y perfiles Compose existentes es vacío.
No se ejecutaron pruebas de aplicación, commit ni push; las comprobaciones son las operativas de A12.

**A12 cerrado. A2 no ejecutado ni cerrado por este informe.**

