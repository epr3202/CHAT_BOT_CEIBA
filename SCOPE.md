# SCOPE.md

## A0 — Reconciliación de evidencia huérfana
Incluye: evaluar el commit exclusivo `13c0e9f8c3d434f7f5e1bf7a2a1667272626137e` de `rescue-adversarial-suites`; ejecutar sus pruebas contra el candidato R11; decidir únicamente entre incorporar esas pruebas sin modificar producto o documentarlas como supersedidas.

NO incluye: cambios en código productivo; corrección de fallos funcionales descubiertos por esas pruebas; refactor de IA; modificación de normalización de `event_type`; incorporación de otras ramas históricas.

### Criterios de aceptación (cerrados)
- [ ] `git log fix/r11-preprod-readiness-20260914..rescue-adversarial-suites --oneline` devuelve únicamente el commit huérfano identificado.
- [ ] `git diff --name-only fix/r11-preprod-readiness-20260914...rescue-adversarial-suites` no identifica código productivo fuera de `tests/`.
- [ ] Las pruebas rescatadas se ejecutan contra R11 y su resultado queda registrado como PASS o FAIL.
- [ ] Si pasan y siguen siendo aplicables, se incorporan solo archivos de pruebas; `git diff --name-only <R11-base>..<resultado>` no muestra cambios productivos.
- [ ] Si se consideran supersedidas, existe evidencia escrita de la razón y el commit no se incorpora.
- [ ] No queda una decisión ambigua sobre `rescue-adversarial-suites`.

### Fuera de validación
Calidad general del clasificador, nuevos casos adversariales, cobertura global, rendimiento de IA y funcionalidades no ejercitadas por esas pruebas.

---

## A1 — Provisionamiento de preproducción
Incluye: destino staging aislado; host y daemon Docker/Compose identificados; proyecto Compose identificado; PostgreSQL 16 identificado; TLS configurado; acceso administrativo restringido; directorios persistentes requeridos; nombres de secretos requeridos; `target.json` real sin placeholders.

NO incluye: despliegue productivo; llamadas reales a Meta; ejecución PRE-01..18; restauración de backup; activación de Calendar writes; PaymentEvidence automático; reminders; exposición pública del administrador.

### Criterios de aceptación (cerrados)
- [ ] `docker info` termina con código 0 en el host objetivo.
- [ ] `docker compose version` termina con código 0 y corresponde a Compose v2.
- [ ] `target.json` contiene valores reales para `environment`, `hostname`, `checkout_path`, `project`, `database_system_identifier`, `backup_dir`, `backup_gpg_recipient`, `close_hook`, `smoke_hook` y `reopen_hook`; ningún valor conserva `<...>` ni `NOT_PROVISIONED`.
- [ ] `environment` de `target.json` es exactamente `staging`.
- [ ] La identidad real de PostgreSQL coincide con `database_system_identifier` de `target.json`.
- [ ] Los secretos requeridos por `docs/deployment.md` están provisionados por nombre y ninguno se almacena en Git.
- [ ] `docker compose -f compose.protected.yml config` termina con código 0 usando la configuración staging.
- [ ] El certificado TLS del hostname configurado puede validarse sin error desde el canal autorizado.
- [ ] El acceso administrativo está restringido a la política VPN/IP aprobada y no queda expuesto públicamente.

### Fuera de validación
Alta disponibilidad, escalamiento horizontal, balanceo multi-host, rendimiento, Disaster Recovery regional y arquitectura cloud futura.

---

## A2 — Restauración y recuperación

**Estado: CERRADO — 8/8 criterios verificados el 2026-09-25 UTC mediante restauración independiente del checkpoint derivado de A12.** Evidencia: [Informe A2](docs/remediation/a2-restore-2026-09-25/FINAL-REPORT.md); copia en el repositorio: `docs/remediation/a2-restore-2026-09-25/FINAL-REPORT.md`. Este cierre posterior sustituye el estado abierto de A2 registrado al cerrar A12.

Incluye: generar o seleccionar checkpoint cifrado válido; verificar checksum; verificar lista de restauración; restaurar en PostgreSQL 16 desechable y separado; comparar revisión Alembic, conteos definidos, constraints e integridad.

NO incluye: restauración sobre DB operacional; downgrade Alembic; recuperación punto-en-tiempo; replicación; cambio de motor de base de datos; políticas nuevas de retención.

### Criterios de aceptación (cerrados)
- [x] Existe archivo `.dump.gpg` no vacío y su SHA-256 queda registrado.
- [x] `gpg --batch --decrypt <backup> | pg_restore --list` termina con código 0.
- [x] La restauración sobre una base PostgreSQL 16 desechable termina con código 0 usando `pg_restore --exit-on-error --no-owner --no-privileges`.
- [x] `SELECT version_num FROM alembic_version;` en la DB restaurada devuelve exactamente `20260910_0027`.
- [x] Se comparan origen/checkpoint y restauración para `message`, `audit_event`, `customer`, `conversation`, `inbox_job/outbox` y `lead`, y los conteos coinciden.
- [x] La comprobación de foreign keys y unique constraints termina sin violaciones.
- [x] La evidencia no contiene PII ni valores de secretos.
- [x] La DB operacional no fue borrada, recreada ni usada como destino del restore.

### Fuera de validación
RPO/RTO contractual, restauraciones parciales, PITR, backups incrementales, rendimiento de restore y escenarios de desastre no listados.

---

## A3 — Certificación E2E de preproducción
Incluye: desplegar el artefacto R11 congelado en staging con ingress general cerrado; validar identidad/configuración; usar cuenta/canal controlado autorizado; ejecutar exactamente PRE-01 a PRE-18 en orden; registrar evidencia de cada gate.

NO incluye: tráfico general de clientes; producción; nuevas funcionalidades; Calendar writes; PaymentEvidence automático; reminders; correcciones descubiertas durante la certificación dentro del mismo alcance.

### Criterios de aceptación (cerrados)
- [ ] El SHA desplegado coincide exactamente con el candidato congelado aprobado.
- [ ] Los IDs de imágenes desplegadas coinciden con `manifest.json`.
- [ ] `GET /live` devuelve HTTP 200 y `{"status":"alive"}`.
- [ ] `GET /ready` devuelve HTTP 200 y `{"status":"ready"}`.
- [ ] `GET /health` devuelve HTTP 200 con `status=ok`, `database=ok` y `environment=staging`.
- [ ] PRE-01 a PRE-18 tienen cada uno resultado individual PASS con evidencia.
- [ ] PRE-03 demuestra inbound Meta controlado → webhook → Inbox durable.
- [ ] PRE-06 demuestra Outbox enqueue → claim → envío → acknowledgement.
- [ ] PRE-08 y PRE-09 demuestran pausa, visibilidad, ownership y operación humana autorizada.
- [ ] PRE-10 demuestra captura multimedia pasiva sin automatización PaymentEvidence.
- [ ] PRE-11 demuestra que la ruta automática histórica de pago permanece bloqueada.
- [ ] PRE-12 demuestra cero escrituras Calendar.
- [ ] PRE-13 y PRE-14 demuestran rechazo de simulador/fake adapter en entorno protegido.
- [ ] PRE-15 y PRE-16 demuestran recuperación durable e idempotencia.
- [ ] PRE-17 demuestra degradación segura ante fallo controlado de proveedor.
- [ ] PRE-18 demuestra trazabilidad completa sin secretos ni PII.
- [ ] El `smoke_hook` termina con código 0 únicamente después de estar presentes las 18 evidencias.

### Fuera de validación
Carga, concurrencia masiva, latencia objetivo, cuentas de clientes reales distintas al canal controlado y edge cases no incluidos en PRE-01..18.

---

## A4 — Cierre de readiness para producción
Incluye: consolidar evidencia de A1, A2 y A3; ejecutar preflight de despliegue; emitir veredicto binario `READY_FOR_PRODUCTION` o `BLOCKED`; identificar únicamente blockers concretos fallidos.

NO incluye: desplegar en producción; corregir blockers; cambios de producto; hardening adicional; features futuras.

### Criterios de aceptación (cerrados)
- [ ] A1 está cerrado con todos sus criterios ✅.
- [ ] A2 está cerrado con todos sus criterios ✅.
- [ ] A3 está cerrado con todos sus criterios ✅.
- [ ] `./deploy.sh <sha> --manifest <manifest> --target <target>` sin `--execute` termina con código 0.
- [ ] El preflight confirma SHA, tree, image IDs, entorno, proyecto, identidad DB y revisión `20260910_0027`.
- [ ] Existe un único veredicto final: `READY_FOR_PRODUCTION` o `BLOCKED`.
- [ ] Si el veredicto es `BLOCKED`, cada blocker referencia una evidencia fallida concreta; no se incluyen riesgos hipotéticos.

### Fuera de validación
Mejoras recomendables, escalabilidad futura, optimizaciones, cambios de arquitectura y backlog no bloqueante.

---

## A5 — Integración controlada del candidato
Incluye: integrar en `main` exactamente el candidato certificado; preservar su código productivo y migraciones; ejecutar CI sobre el resultado; demostrar que no se introdujo funcionalidad adicional.

NO incluye: refactors; dependency upgrades; actualización de bases Docker/Node; cambios de features; limpieza general; activación de flags OFF; incorporación automática de ramas antiguas.

### Criterios de aceptación (cerrados)
- [ ] Antes de integrar, el SHA certificado está registrado.
- [ ] `git merge-base --is-ancestor <sha-certificado> main` termina con código 0 después de la integración.
- [ ] El diff de código productivo entre el candidato certificado y el resultado integrado es vacío, salvo archivos de gobierno documental explícitamente aprobados.
- [ ] La revisión Alembic máxima sigue siendo `20260910_0027`.
- [ ] `PAYMENT_EVIDENCE_AUTOMATION_ENABLED=false`.
- [ ] `CALENDAR_WRITES_ENABLED=false`.
- [ ] El CI completo de `main` termina SUCCESS.
- [ ] No se incorporan commits exclusivos de otras ramas sin un alcance aprobado.

### Fuera de validación
Reescritura de historial, estrategia Git futura, eliminación de ramas antiguas y mejoras adicionales del pipeline.

---

## A6 — Go-live y rollback controlado
Incluye: ejecutar despliegue productivo del artefacto certificado; cerrar ingress; checkpoint cifrado; preflight; migración únicamente hasta 0027 cuando corresponda; arranque ordenado API → worker → frontend; health/smoke; reapertura; validar disponibilidad de rollback hacia un artefacto seguro certificado.

NO incluye: downgrade de esquema; rebuild durante promoción; deployment desde una rama mutable; activación de features OFF; reparación de datos inciertos; replay automático de Outbox incierto.

### Criterios de aceptación (cerrados)
- [ ] Existe un artefacto seguro certificado utilizable para rollback; si no existe, A6 permanece ❌.
- [ ] `./deploy.sh <sha> --manifest <manifest> --target <target> --execute` termina con código 0.
- [ ] El checkpoint cifrado previo al cambio pasa las validaciones de A2 aplicables al despliegue.
- [ ] `SELECT version_num FROM alembic_version;` devuelve exactamente `20260910_0027`.
- [ ] `GET /live` devuelve 200.
- [ ] `GET /ready` devuelve `{"status":"ready"}` con HTTP 200.
- [ ] `GET /health` devuelve `status=ok`, `database=ok` y `environment=production`.
- [ ] API, worker y frontend aparecen activos/healthy según el contrato de despliegue.
- [ ] El smoke productivo aprobado termina con código 0.
- [ ] El ingress se reabre únicamente después de los gates anteriores.
- [ ] `./rollback.sh <safe-sha> --manifest <safe-manifest> --target <target>` sin `--execute` termina con código 0 contra el artefacto seguro.
- [ ] No se ejecutó downgrade de Alembic.
- [ ] No se reconstruyó ninguna imagen durante la promoción.

### Fuera de validación
Rollback destructivo de base de datos, rollback de esquema, multi-región, auto-scaling y disponibilidad contractual.

---

## A7 — Hardening operativo de producción
Incluye: distributed login throttling del administrador; revisión/bloqueo de exposición pública administrativa; separación de roles DB con least privilege; alerta operativa ante worker unhealthy; controles operativos documentados de retención y PII mencionados por R11.

NO incluye: nuevo sistema IAM; SSO; SIEM completo; WAF general; observabilidad empresarial; rediseño de infraestructura; nuevas funcionalidades del chatbot.

### Criterios de aceptación (cerrados)
- [ ] Existe una prueba automatizada que demuestra rechazo HTTP 429 al superar el límite de login configurado.
- [ ] El límite utilizado por la prueba aparece explícitamente en configuración y no depende de memoria local de un único proceso si existen múltiples procesos.
- [ ] Un request administrativo desde una ruta no autorizada no alcanza la aplicación administrativa.
- [ ] Un request administrativo desde el canal VPN/IP autorizado sí puede alcanzar el endpoint previsto.
- [ ] La aplicación no opera en producción con el rol propietario/superusuario de PostgreSQL para sus operaciones normales.
- [ ] Las operaciones normales de API y worker pasan utilizando los roles DB definidos.
- [ ] Una condición `unhealthy` controlada del worker genera una alerta observable al canal operativo configurado.
- [ ] Existe una política operativa concreta de retención/PII aplicable a los datos existentes y puede señalarse el mecanismo que la ejecuta.
- [ ] La suite existente permanece verde.

### Fuera de validación
Certificaciones regulatorias, pentest completo, DDoS, SOC/SIEM, secretos rotativos automáticos, HA y amenazas no demostradas por el código actual.

---

## A8 — H05 agotamiento/fallback de transferencia humana
Incluye: únicamente la parte pendiente `H05.agotamiento_fallback`.

NO incluye: cambiar la solicitud explícita de humano ya implementada; ownership; comandos de agente; reglas de horario; rediseño del handoff; features de CRM.

### Criterios de aceptación (cerrados)
- [ ] Antes de modificar producto existe una definición explícita y aprobada de qué condición exacta constituye “agotamiento”.
- [ ] Antes de modificar producto existe una definición explícita y aprobada de cuál es la acción de fallback esperada.
- [ ] Si cualquiera de esas dos definiciones falta, A8 se reporta ❌ `BLOCKED_BY_PRODUCT_DECISION` y no se implementa código.
- [ ] Una vez definidas, existe una prueba que reproduce exactamente la condición de agotamiento aprobada.
- [ ] Esa prueba demuestra el fallback aprobado y no una conducta adicional.
- [ ] Las pruebas de solicitud explícita de humano existentes permanecen verdes.

### Fuera de validación
Cualquier supuesto sobre número de reintentos, tiempos, mensajes o destinatarios no documentados expresamente.

---

## A9 — Escrituras de Calendar
Incluye: habilitar únicamente las operaciones de Calendar ya existentes en el proyecto para crear, actualizar y cancelar cuando el gate correspondiente esté habilitado; mantener bloqueo completo cuando esté deshabilitado.

NO incluye: reminders; disponibilidad avanzada nueva; múltiples proveedores de calendario; UI de calendario; Google Workspace provisioning; nuevas reglas comerciales de agenda.

### Criterios de aceptación (cerrados)
- [ ] Con `CALENDAR_WRITES_ENABLED=false`, create/update/cancel no producen llamadas de escritura al proveedor.
- [ ] Con `CALENDAR_WRITES_ENABLED=true` y configuración válida, los flujos existentes de create/update/cancel alcanzan el adapter Google previsto.
- [ ] `pytest -q tests/test_slice2b2_gcal_adapter_adversarial.py tests/test_slice2b3_wiring_adversarial.py tests/test_slice2b11_reschedule_calendar_adversarial.py` termina con código 0.
- [ ] La habilitación no activa PaymentEvidence ni reminders.
- [ ] El comportamiento OFF de R11 permanece cubierto por prueba.
- [ ] No se introducen adaptadores fake permitidos en staging/production.

### Fuera de validación
Cuotas de Google a escala, calendarios múltiples nuevos, sincronización bidireccional no existente, UI y reglas no documentadas.

---

## A10 — Automatización PaymentEvidence
Incluye: habilitar únicamente la automatización de PaymentEvidence ya representada por el módulo existente; conservar captura multimedia pasiva; mantener el gate OFF como comportamiento seguro cuando esté deshabilitado.

NO incluye: conciliación bancaria; pasarela de pagos; OCR nuevo; aprobación automática del pago si no existe en el contrato actual; facturación; reembolsos.

### Criterios de aceptación (cerrados)
- [ ] Con `PAYMENT_EVIDENCE_AUTOMATION_ENABLED=false`, la captura multimedia puede persistirse pero no dispara procesamiento automático de PaymentEvidence.
- [ ] Con el gate habilitado en entorno de prueba, el worker de PaymentEvidence existente procesa únicamente los inputs admitidos por su contrato actual.
- [ ] `pytest -q tests/test_w2b_payment_evidence_adversarial.py` termina con código 0.
- [ ] Los hashes/evidencias permanecen compatibles con el contrato vigente.
- [ ] La habilitación no activa Calendar writes ni reminders.
- [ ] El gate OFF continúa siendo el default del release hasta que este alcance sea cerrado y autorizado para promoción.

### Fuera de validación
Reconocimiento visual nuevo, bancos, APIs financieras, antifraude, conciliación contable y reglas de negocio no existentes.

---

## A11 — Recordatorios
Incluye: cerrar primero la especificación mínima de la funcionalidad de reminders porque el material actual solo demuestra que está diferida/deshabilitada; implementar únicamente después de definir disparador, destinatario, momento de envío y condición de cancelación.

NO incluye: asumir frecuencia; asumir plantillas; asumir canal; campañas; marketing; secuencias comerciales; cron jobs genéricos; Calendar writes.

### Criterios de aceptación (cerrados)
- [ ] Existe decisión explícita aprobada para el disparador del reminder.
- [ ] Existe decisión explícita aprobada para el destinatario.
- [ ] Existe decisión explícita aprobada para el momento de envío.
- [ ] Existe decisión explícita aprobada para la condición de cancelación.
- [ ] Mientras cualquiera de los cuatro puntos anteriores falte, A11 se reporta ❌ `BLOCKED_BY_PRODUCT_DECISION` y no se modifica código.
- [ ] Una vez definidos, cada comportamiento aprobado tiene una prueba binaria asociada.
- [ ] No se implementan reminders adicionales a los cuatro elementos aprobados.
- [ ] Calendar writes y PaymentEvidence no cambian como efecto lateral.

### Fuera de validación
Frecuencias, campañas, plantillas, canales, reintentos y reglas no aprobadas expresamente.

---

## A12 — Preparación de checkpoint compatible para A2

**Estado: CERRADO — 8/8 criterios verificados el 2026-09-25 UTC.** Evidencia: [Informe A12](docs/remediation/a12-checkpoint-2026-09-25/FINAL-REPORT.md); copia en el repositorio: `docs/remediation/a12-checkpoint-2026-09-25/FINAL-REPORT.md`. A2 permanece abierto.

Incluye: usar producción exclusivamente como origen de lectura para generar un checkpoint cifrado mediante el procedimiento y destinatario GPG existentes; restaurarlo en PostgreSQL 16 temporal, desechable y separada; aplicar únicamente sobre esa copia las migraciones existentes necesarias hasta `20260910_0027`; verificar revisión, tablas, conteos agregados y constraints; generar desde la copia migrada un checkpoint `.dump.gpg` cifrado, no vacío y con SHA-256 registrado para ejecutar A2 posteriormente; eliminar únicamente los recursos temporales creados para A12 y conservar el checkpoint cifrado derivado.

Ruta existente verificada mediante `revision` y `down_revision`: `20260825_0024` → `20260908_0025` (`alembic/versions/20260908_0025_outbox_claim_token.py`) → `20260908_0026` (`alembic/versions/20260908_0026_durable_inbox.py`, crea `inbox_job`) → `20260910_0027` (`alembic/versions/20260910_0027_outbox_admission.py`). Si esta ruta no puede verificarse en el código utilizado, A12 queda bloqueado y no se sustituye por pasos inventados.

NO incluye: cualquier escritura, migración, restauración o cambio en producción; restaurar sobre la DB operacional o la DB persistente de staging; cambios de código o creación/modificación de migraciones; cambios de configuración, infraestructura, DNS, Cloudflare o políticas de retención; downgrade, PITR, replicación o cambios de motor; inspeccionar o integrar ramas o inventariar funcionalidades pendientes; guardar dumps sin cifrar de forma persistente; imprimir credenciales, secretos, datos personales o filas. La única excepción operativa es crear, usar y eliminar el PostgreSQL temporal aislado aquí autorizado; no se alteran recursos existentes. Solo se autoriza ejecutar las migraciones existentes indicadas sobre esa copia temporal, sin iniciar consumidores de aplicación.

### Criterios de aceptación (cerrados)
Cada criterio requiere evidencia observada de comandos, códigos de salida y resultados; no basta un procedimiento propuesto. Si falta evidencia o falla un criterio, A12 permanece abierto.

- [x] Se identifica inequívocamente el origen de producción, se observa la revisión inicial `20260825_0024` mediante consulta de solo lectura y se registra la cadena existente completa hasta `20260910_0027`, con archivos y enlaces `revision`/`down_revision` coincidentes con la ruta anterior.
- [x] Se genera mediante el procedimiento y destinatario GPG configurados un checkpoint completo de origen `.dump.gpg` en el directorio de backup configurado; el archivo existe, no está vacío y quedan registrados su tamaño y SHA-256. `gpg --batch --decrypt <checkpoint-origen> | pg_restore --list`, con propagación de errores del pipeline, termina con código 0.
- [x] Se verifica que el destino es PostgreSQL 16 temporal, sin exposición pública y separado tanto de producción como de la DB persistente de staging; la restauración del checkpoint de origen termina con código 0 usando `pg_restore --exit-on-error --no-owner --no-privileges`, con propagación de errores del descifrado y restore y sin dump persistente en claro.
- [x] Se verifica la identidad del destino temporal antes de migrar; `alembic upgrade 20260910_0027` termina con código 0 dirigido exclusivamente a esa copia y aplica únicamente `20260908_0025`, `20260908_0026` y `20260910_0027`, sin crear ni modificar migraciones.
- [x] `SELECT version_num FROM alembic_version;` en la copia temporal devuelve una única fila con exactamente `20260910_0027`; se comprueba la presencia de `public.message`, `public.audit_event`, `public.customer`, `public.conversation`, `public.inbox_job`, `public.outbox` y `public.lead`.
- [x] Se genera desde la copia migrada, mediante el procedimiento y destinatario GPG existentes y en el directorio de backup configurado, un checkpoint derivado `.dump.gpg` distinto del checkpoint de origen; existe, no está vacío y se registran tamaño, SHA-256 y procedencia. `gpg --batch --decrypt <checkpoint-derivado> | pg_restore --list`, con propagación de errores del pipeline, termina con código 0; el checkpoint derivado queda conservado e identificado para A2.
- [x] Se registran los conteos agregados de las siete tablas requeridas en la copia migrada correspondientes al checkpoint derivado, sin escrituras concurrentes; las comprobaciones de foreign keys y unique constraints terminan sin violaciones y se registran comandos, códigos de salida y resultados. La evidencia se revisa antes de guardarse y no contiene filas, PII ni valores de secretos.
- [x] La evidencia demuestra que producción se usó únicamente como origen de lectura y nunca fue modificada ni usada como destino; tampoco se restauró sobre staging persistente. Se confirma la eliminación de todos y únicamente los recursos temporales creados para A12, la ausencia de dumps persistentes sin cifrar y la conservación del checkpoint cifrado preparado para A2.

### Fuera de validación
A12 prepara un checkpoint compatible; no certifica la restauración final ni cierra A2. A2 debe ejecutarse después usando el checkpoint derivado y mantiene intactos sus ocho criterios vigentes; para su comparación, el origen/checkpoint de referencia es la copia migrada correspondiente al checkpoint derivado y sus conteos registrados. Quedan fuera la actualización de producción, la certificación funcional de la aplicación y cualquier recuperación o cambio no incluido expresamente.

---

## Regla global
Cada chat trabaja UN alcance. Todo lo que esté fuera del "Incluye" se registra en BACKLOG, no se implementa ni se diseña.

## BACKLOG
(vacío al inicio)