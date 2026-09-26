# R1 — H02.Outbox

Unidad limitada a propiedad de reclamación y settlement de texto/documento. Base exacta R0:
`49fb61eb35a59b1142d4b2b81aff84fffc8db277`; rama `fix/r1-h02-outbox-20260908`.
La reproducción roja `84ad100264449fa5b44cb0734fa88a1470b02013`, run `34234497390`,
dio 4 controles aprobados y 15 fallos por mutaciones persistidas en PostgreSQL 16 migrado.
Los resultados finales y filas por caso se conservan en este paquete local.

## Causa y contrato

El código R0 bloqueaba la fila pero liquidaba exclusivamente por ID. Un consumidor antiguo
podía sobrescribir el resultado de otro, insertar otro Message o producir auditoría de fallo.

Se agrega `outbox.claim_token`, UUID nullable sin default de servidor ni backfill. Cada claim
asigna `uuid4()` dentro de la transacción breve con `FOR UPDATE SKIP LOCKED`. La probabilidad
de colisión de UUID aleatorios es despreciable; la identidad no depende de reloj, PID ni intentos.
El consumidor recibe `OutboxClaim` congelado, separado del ORM, con identidad que no se refresca.
Los campos de identidad son inmutables; el payload es una copia independiente para el envío.

Los settlements exigen `claim_token` como argumento obligatorio. Bajo `FOR UPDATE`, verifican
existencia, estado SENDING y coincidencia con un UUID válido; la actualización y el INSERT de
Message se confirman en esa misma transacción. Se devuelve APPLIED o DISCARDED. El descarte
solo registra outbox_id, tipo de resultado y motivo; no genera reintentos ni auditoría comercial.
Un segundo settlement queda descartado incluso con otro provider_message_id. El helper privado
de fallo solo se invoca bajo lock desde settlement autorizado o recuperación por el reaper.

La expiración efectiva ocurre cuando el reaper invalida la adquisición en su transacción.
El mero paso del reloj no revoca antes del reaper. Éxito, fallo y recuperación borran el token;
el reintento obtiene otro. HTTP, resolución/subida de media y descarga quedan fuera de estas
transacciones. Se conserva la política de attempts/backoff/FAILED y múltiples salidas válidas
por entrada, incluso con igual texto. No se cambia el worker de comprobantes.

## Pruebas y derivación del entorno

`tests/remediation/test_r1_outbox.py` porta el criterio persistido de `claim_probe.py`, sin
importar su plugin ni sustituir persistencia. Las mismas 19 pruebas rojas se ejecutan sobre
el candidato. La comparación usa SELECT de todas las columnas desde otra sesión, incluyendo
Message y AuditEvent. Los eventos ordenan la carrera y los timeouts solo evitan cuelgues.

Las pruebas adicionales cubren token obligatorio/inmutable, reloj repetido, doble éxito/fallo
secuencial y concurrente, competencia, salidas independientes para una misma entrada, observabilidad,
errores permanentes/reintentables y reintento tras media inválida. Un constraint trigger diferido
provoca un error real al COMMIT para demostrar rollback conjunto. El test de fallback documental
solo envuelve el settlement real con una barrera después de su rollback; no reemplaza sus escrituras.

El workflow nuevo dispara exclusivamente por push a `fix/r1-h02-outbox-*`. Dos jobs independientes:
suite completa más Ruff, y regresiones sobre Alembic. Ambos fallan ante fases incompletas, skips,
xfail, red inesperada o errores de preparación/cleanup. No hay continue-on-error.
El runner deriva del R0 congelado, manteniendo extracción desde el SHA exacto del push,
allowlist explícita respecto de R0 y hashes de archivos protegidos. Reutiliza sin modificar
`scripts/quality/r0/isolation.py`: rol, destino, propietario, system_identifier y PostgreSQL 16.
No se pasa autenticación GitHub a los tests; red Docker interna y credenciales sintéticas.

La suite conserva los 635 nodeids de R0 mediante un manifiesto. Su preparación original usa metadata.
El job focal aplica Alembic y solo trunca filas sintéticas entre casos: nunca recrea el esquema por
metadata. Paridad/legacy reutilizan el fixture Alembic existente que crea otra DB UUID en la misma
instancia atestada (su nombre histórico contiene `aiexec_parity`, pero el objeto comprobado es Outbox).
No se modifica ningún test R0 ni sus expectativas. No se ejecuta aplicación ni pytest en el PC.

## Migración, activación y rollback propuestos

Migración aditiva `20260908_0025_outbox_claim_token.py`, revisión `20260908_0025`, padre
`20260825_0024`. Conserva las 24 migraciones previas. La paridad comprueba UUID, nullabilidad y
ausencia de default; no se introducen restricciones adicionales ni unicidad por entrada.

Las filas previas PENDING/SENDING/SENT/FAILED conservan datos y reciben NULL. Un SENDING legado
se recupera después del timeout según claimed_at; si también falta claimed_at, según created_at.
No se inventa un propietario para callbacks antiguos. Tras recuperación vuelve a la política
normal de reintentos y solo una adquisición nueva puede liquidar.

Procedimiento propuesto, NO ejecutado en producción:

1. Detener nuevas adquisiciones y drenar/detener TODOS los consumidores antiguos. Confirmar que
   no quedan procesos antiguos capaces de liquidar por ID. El esquema nuevo por sí solo no los protege.
2. Revisar envíos en vuelo cuyo proveedor pudo aceptar el documento/texto sin resultado local conocido.
   La decisión de reintentar conserva el riesgo de entrega duplicada; no hay garantía exactly-once externa.
3. Aplicar la migración aditiva con consumidores detenidos, verificar revisión y columna nullable.
   Activar exclusivamente consumidores nuevos y observar recuperación/descarte/fallos.
4. Para rollback, detener y drenar consumidores nuevos. Preferir conservar la columna nullable si se
   retira código; volver a código antiguo pierde inmediatamente esta garantía. No operar versiones mixtas.
   Un downgrade elimina identidades y solo puede considerarse sin intentos activos, previa revisión de
   resultados externos inciertos. El ensayo downgrade/upgrade usa exclusivamente DB sintética del job.

Se omite `make migrate-cycle` por instrucción explícita R1; se emplean comandos Alembic directos
contra bases recién creadas y atestadas. La publicación roja autorizada es una excepción expresa
al gate habitual de commit después de pytest. No se modifica AGENTS ni despliegue.

## Fronteras y evidencia

La caché global de CatalogAsset y sus eventos de subida/invalidation pertenecen a MediaService y
pueden cambiar antes del settlement; no quedan cercados por este token y no se modifican aquí.
Una llamada externa ya iniciada puede ser aceptada. Tampoco se resuelven orden por conversación,
cancelación al takeover, comandos humanos, inbox ni H02.payment. H02 agregado y los demás hallazgos
mantienen su estado pendiente; esta unidad no autoriza producción.

El paquete final incluye informe, tabla por nodeid con filas antes/después, SHAs/runs/artefactos,
versiones/digests, manifiestos y diff canónico generado por Git. El candidate.diff histórico R0
se conserva intacto. No hubo PR, merge, tags ni despliegue.
