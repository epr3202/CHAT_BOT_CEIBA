# R2 - H01: recuperacion durable del inbox

Implementacion candidata, no desplegada. Base exacta R1:
`66a398124c007bdc54895fe891601e470910ce8e`.
Rama exclusiva: `fix/r2-h01-inbox-20260908`. No PR, merge, main, VPS ni despliegue.

La evidencia descargada y el cierre final pueden permanecer solo en el arbol local.
El informe `validation_report.md` y su matriz complementan este documento cuando
termine la validacion; su ausencia en GitHub no significa que hayan sido publicados.

## Causa y reproduccion

R1 consideraba duplicado un Message ya confirmado antes de completar B/C. La
reentrega podia marcar el evento PROCESSED sin producir los efectos faltantes.
RED `080b50934d1ec62b1f878b25ada7cf2584afde45`, run
[34241139241](https://github.com/epr3202/CHAT_BOT_CEIBA/actions/runs/34241139241),
conserva producto R1: 676 casos unicos, 673 pasan y 3 fallan en call con setup y
teardown completos. El focal recoge 37 R1 + 4 reproducciones: 38 pasan, 3 fallan.
Fallan Message confirmado, evento parcialmente materializado y clasificacion
interrumpida antes de los efectos; el control normal pasa. No son errores de importacion.

El primer candidato `4c68d1b959cbf5cce3a2f88c37b8a0e97faff901`, run
[34244248850](https://github.com/epr3202/CHAT_BOT_CEIBA/actions/runs/34244248850),
se conserva como intento fallido. El control nuevo de agenda consultaba una columna
incorrecta; ademas quedaron pendientes el inventario estricto de tablas y la
compatibilidad de clasificacion previa durante control humano. Sus dos ensayos de
SIGKILL/reinicio y las 37 regresiones R1 pasaron. Esto no aprueba aquel candidato.

## Fronteras persistentes

1. La API confirma WebhookEvent con `intake_version=2` antes de BackgroundTasks.
   El consumidor recupera RECEIVED aunque nunca haya arrancado esa tarea.
2. La expansion del evento confirma Message y su InboxJob UNIQUE(message_id) en
   una misma transaccion; PREPARED es una proyeccion del evento, no finalizacion
   del mensaje. Un conflicto esperado se resuelve por la identidad externa ya
   persistida; otro IntegrityError se propaga o queda como fallo de expansion.
   La creacion de cliente usa ON CONFLICT sobre phone y bloqueo del cliente.
3. Una adquisicion corta confirma PROCESSING, UUID nuevo y claimed_at. El snapshot
   congelado separa el token del ORM mutable. Clasificacion y telemetria IA ocurren
   fuera de los locks del inbox. Se conserva la clasificacion previa de R1 incluso
   en turnos humanos; su resultado no autoriza responder durante pausa.
4. Antes de aplicar, se bloquean Customer, Conversation e InboxJob, en ese orden;
   se recargan propietario, control humano y contexto. Efectos locales de
   orquestacion, auditoria, lead/evento/handoff, metadatos de pago, encolado de
   catalogo, Outbox y COMPLETED comparten commit. Un trigger SQL diferido prueba
   el rollback real de ese conjunto. Message y AuditEvent siguen append-only.
5. WebhookEvent.PROCESSED se calcula posteriormente cuando todos sus trabajos
   estan COMPLETED. Una caida entre estos commits no reejecuta la orquestacion.

COMPLETED significa turno resuelto y efectos locales confirmados. No significa
entrega a Meta. SILENT_HUMAN_ACTIVE, SILENT_WAITING_FOR_HUMAN y SILENT_BOT_DISABLED
son decisiones explicitas; no se infieren de Outbox. Un turno puede tener varias
salidas legitimas. Las ramas multimedia conservan su comportamiento, incluido H03.
Estados del proveedor y eventos ignorables no crean trabajo artificial.

## Coordinacion y reintentos

API, CLI y el nuevo bucle del worker usan el mismo protocolo de inbox. R1 Outbox
mantiene sus funciones y token separados; solo se agrega el bucle a run_worker.
No se crea un framework de cola ni una tarea por cada error.

El menor id de trabajo no completado de cada conversacion define el orden local.
Se adquiere como maximo uno por conversacion y lote; una conversacion en FAILED o
REVIEW detiene sus siguientes turnos, pero otras progresan. No se promete ordenar
por timestamp del proveedor. El fingerprint de Conversation y nombre del cliente
detecta cambios entre clasificacion y efectos; se recalcula en un intento nuevo.
Los demas agregados se leen de nuevo al decidir. Esto no completa H06 ni coordina
todos los comandos humanos ajenos al protocolo.

El reloj vuelve elegible una reclamacion para el reaper; la revocacion solo es
efectiva cuando este confirma su cambio bajo bloqueo. Si el propietario finaliza
primero, gana ese commit. Un resultado tardio debe coincidir en id, Message, estado
y UUID; de otro modo no escribe ni reabre el trabajo. Se prueba tambien una nueva
adquisicion con el mismo reloj y dos callbacks concurrentes de la misma adquisicion.

Parametros validados: INBOX_POLL_INTERVAL_SECONDS=1, INBOX_BATCH_SIZE=10 (1..100),
INBOX_CLAIM_TIMEOUT_SECONDS=120, INBOX_MAX_ATTEMPTS=5 (1..100),
INBOX_MAX_BACKOFF_SECONDS=300. Tras fallo o abandono local: espera
min(2**attempts, max_backoff); al agotar, FAILED. Expansion tiene contador separado
y termina EXHAUSTED. Indices de estados, vencimiento y orden respaldan las consultas.
La cancelacion cooperativa libera exclusivamente su propia adquisicion local; no
es prueba de muerte de proceso ni sustituye el reaper.

## Efectos separados y limite externo

La agenda ya confirma transacciones propias y llama al calendario. El adaptador
R2 difiere esas llamadas fuera del settlement: revierte el intento local, valida
propiedad/contexto en transaccion corta, ejecuta el servicio original sin locks,
y vuelve a decidir usando solo el resultado de esa misma adquisicion. Comprueba
orden e identidad de argumentos de negocio al reutilizar el resultado. Conserva
las claves de agenda existentes y no modifica sus reglas ni sus transacciones.

Antes de confirm/reschedule/cancel se confirma EXTERNAL y el nombre de operacion.
Si el resultado se pierde, el proceso muere, cambia el contexto o falla despues de
un posible efecto separado, queda REVIEW/EXTERNAL_OUTCOME_UNCERTAIN. No hay replay
automatico de esa operacion. Cuando se obtiene resultado, se guardan solo sus IDs
tecnicos disponibles. Appointment y sus auditorias separadas conservan evidencia
adicional vinculada a conversacion/request_id; la ausencia de external_result no
prueba que no hubo aceptacion. Un reaper no puede deshacer una llamada ya en vuelo.
No se promete exactly-once externo ni se resuelve la reconciliacion de H07.

AIExecution puede confirmar telemetria de varios intentos de clasificacion. No es
marcador de efectos de negocio. Pago registra metadatos en el settlement; descarga
posterior y H02.payment quedan separados. Subida/descarga de medios ocurre en los
consumidores existentes; Outbox sigue referenciando catalog_asset_id. No se altera
MediaService, el orden de salidas, H03/H04/H05/H07/H17/H29 ni comandos humanos.

## Migracion e historia

Head nuevo 20260908_0026 sobre 0025; ninguna migracion historica cambia. InboxJob
vive en channel.models, ya importado por models_registry. WebhookEvent anterior
queda intake_version=NULL; no hay backfill de trabajos ni de exito. Inventario:
eventos sin version y mensajes INBOUND sin InboxJob son historicos no demostrados,
aunque tengan Outbox o etiqueta PROCESSED. Una reentrega nueva de un Message
historico crea control REVIEW/origin=LEGACY sin repetir efectos.

El ensayo SQL parte de 0025 con filas sinteticas, refleja columnas, nullability,
constraints e indices, valida head 0026 y preservacion de historia. El ciclo
descendente/ascendente con consumidores detenidos destruye los controles InboxJob:
se registra expresamente esa perdida. No es rollback productivo probado.

Cambios individuales de tests previos: test_r1_outbox_migration.py fija el destino
del upgrade a 0025 para conservar el ensayo 0024->0025, sin retirar sus aserciones.
test_models_registry.py incorpora inbox_job al conjunto exacto esperado. No se
elimina ninguna tabla esperada ni ningun nodo R1/R0. Los dobles HTTP R0 permanecen
congelados. El resto de las pruebas nuevas reside en tests/remediation/r2.

## Intervencion y activacion futura (no ejecutada)

`python scripts/reprocess_webhook_events.py --inventory-legacy` solo cuenta.
`--event-id ID` usa el mismo protocolo y reporta resultados reales por estado,
incluido SKIPPED_MISSING_OR_COMPLETED; no cuenta ids solicitados como exitos.
`--retry-job ID --reason MOTIVO_TECNICO` permite un nuevo presupuesto solo a NEW,
FAILED, sin operacion externa; registra AuditEvent INBOX_MANUAL_RETRY y devuelve
sus eventos EXHAUSTED a PREPARED. REVIEW requiere reconciliacion antes de cualquier
decision; el script rechaza otorgarle un reintento ciego.

`--event-id ID --adopt-unmaterialized` admite exclusivamente un evento legacy
RECEIVED/FAILED seleccionado que no tiene ningun Message de su payload. La
presencia de un mensaje historico obliga a revisar evidencia, no a inferir exito.
Para REVIEW, inspeccionar InboxJob, Message, eventos, Outbox, Appointment y auditoria
por IDs; contrastar calendario por su identidad existente cuando corresponda.
Documentar resolucion humana y preparar una intervencion revisada caso a caso.
R2 no implementa una herramienta generica que marque historia como completada.

Antes de activar: inventariar y detener TODAS las instancias API con BackgroundTasks,
workers y ejecuciones CLI antiguas; impedir recepcion nueva durante la frontera o
mantenerla pendiente en el proveedor; drenar/identificar operaciones en vuelo y
conservar evidencia. No basta detener el worker. Migrar preservando datos y arrancar
API/worker/CLI del mismo candidato verificado, sin coexistencia con procesadores
antiguos. Las entradas previas siguen legacy; las nuevas llevan version 2. Observar
RECEIVED/PREPARED, edad/attempts de trabajos y FAILED/REVIEW/EXHAUSTED. Los logs R2
usan IDs tecnicos, estado y tipo de error; no contenido ni tokens de reclamacion.

Ante retroceso, detener todos los productores/consumidores y preservar controles,
preferir correccion hacia adelante. Downgrade borra evidencia de finalizacion y no
autoriza reactivar el consumidor R1 ni reenviar historial. Operaciones externas
inciertas requieren seleccion/reconciliacion separada.

## Verificacion autorizada

Exclusivamente push R2 activa remediation-r2-inbox.yml. Suite candidata completa
con 672 nodos conservados + 34 nuevos; focal independiente con 37 R1 + 34 R2 sobre
Alembic real. Los focales no se suman otra vez. Dos procesos hijos se sincronizan
por senal posterior al commit; se mata solo el PID senalado y otro bucle real
recupera automaticamente, sin llamar manualmente process_webhook_event.

Python 3.12 y PostgreSQL 16 efimeros en Actions, destino/rol/owner/system_identifier
atestados, red externa bloqueada y proveedores doblados. El hijo instala los mismos
guards. Se registran SHA, importaciones, manifiestos, resultados por fase, Ruff,
filas sinteticas y hashes. Fallos y artefactos incompletos mantienen el gate rojo.
En el PC solo se editan archivos, se hace analisis estatico y se verifica evidencia.
La autorizacion especifica de R2 permite publicar RED/candidatos antes de pytest
verde y sustituye make migrate-cycle por el ciclo Alembic aislado. No cambia docs
de negocio ni autoriza nuevas capacidades de la IA.
