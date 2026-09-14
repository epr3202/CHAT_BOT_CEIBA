# R10 — Release scope enforcement (contrato previo al CI)

Base exacta R9 `a9ce7f34342f19022ae608ab48bad4b0654b52d2`, árbol
`812dda4da5dabdc0c985a98884c474442ec5012c`, run `34519324683` aprobado.
HEAD inicial y árbol comprobados en `.r9-work`, limpio. R10 usa un worktree nuevo
en `fix/r10-release-scope-20260914`; la copia principal sucia y R9 se conservan.
`docs/system_context.md` no forma parte de R9; no se crea.

## Alcance y decisiones

La autorización R10 reduce explícitamente el alcance histórico de agenda y
comprobantes. No completa H02.payment, H05, H07/H08/H09 ni habilita funcionalidades.
Inbox, Outbox, WhatsApp real, IA, conversación, catálogos, captura general,
handoff y operación humana siguen ON. Captura pasiva conserva Message y auditoría.

ReleaseScope centraliza ENVIRONMENT (development/testing/production/staging) y
PAYMENT_EVIDENCE_AUTOMATION_ENABLED / CALENDAR_WRITES_ENABLED, ambos false por
defecto. Production y staging rechazan true: no existe una habilitación productiva
por credenciales o por un flag accidental. Una autorización futura requiere otra
revisión de esta política. Dev/testing permiten opt-in explícito para ensayar la
implementación histórica. No se introducen modelos, migraciones ni dependencias
de aplicación. Head sigue 20260910_0027, 27 migraciones preservadas.

## Productores y fronteras

PaymentEvidence se creaba desde create_handoff_and_pause(PAYMENT_REVIEW), desde
route_non_text_in_session (activo y pausado) y el helper de servicio. Todos llegan
a create_payment_evidence, que ahora devuelve None antes de consultar/escribir
cuando OFF. El wrapper de caso abierto también evita consultas innecesarias.
La captura pausada registra AUTOMATION_DISABLED, conserva contenido y completa
Inbox; no eleva prioridad ni altera el resumen mediante evidencia inexistente.

El worker general omite solo el loop de comprobantes cuando OFF. La entrada pública
del consumidor vuelve a validar OFF antes de claim, descarga, filesystem o
settlement: tampoco procesa filas históricas pendientes. No borra ni modifica
evidencia histórica. Las rutas accept/reject humanas y su autenticación no cambian.
No existe aprobación automática y no se introduce una.

VisitSchedulingService devuelve resultado explícito de handoff con plantilla de
error aprobada antes de DB/freebusy/insertar citas al intentar confirmar,
reprogramar o cancelar con writes OFF. FakeCalendarAdapter y GoogleCalendarAdapter
comprueban la misma política antes de create/update/delete: CalendarWritesDisabled,
subtipo de CalendarUnavailableError, sin HTTP ni éxito ficticio. Las lecturas
existentes permanecen; no se añade agenda. No se toca el protocolo Inbox R2.

Settings rechaza CALENDAR_ADAPTER=fake y endpoints alternativos de Meta/OpenRouter
en production/staging. No sustituye fake por google. Configurar google no concede
permiso de escritura. La construcción directa de FakeCalendarAdapter también se
rechaza en entornos protegidos. No se inspeccionan secretos operativos.

Frontend rechaza POST /api/webhook/simulate antes de leer/firmar/enviar su body en
production/staging. Sin ENVIRONMENT, Node usa production; valores desconocidos
fallan al arrancar. NODE_ENV=production/staging tampoco permite simular. Dev/testing
requieren ENVIRONMENT explícito. Los tres scripts de simulación/doble comprueban
el entorno antes de iniciar su operación; no se arrancan en este PC.

Reminders sigue OFF: no se conecta process_due_reminders ni un nuevo dispatcher.
El método histórico latente conserva su limitación de marcar sin enviar; R10 no lo
repara ni lo anuncia como recordatorios implementados.

## Pruebas y perfil histórico

Tests R10 se escribieron antes del producto. No se atribuye RED funcional remoto.
Cubren captura multimedia sin evidencia, deduplicación, continuidad Inbox/Outbox,
arranque sin consumer de comprobantes, filas históricas inmóviles cuando OFF,
aceptación humana autenticada, las tres mutaciones en ambos adaptadores y las tres
entradas de servicio antes de tocar dependencias, defaults OFF, producción/staging,
URLs fake, constructor fake directo y scripts. Node prueba el endpoint HTTP real
en un proceso hijo propio contra un backend sintético, con cero inbound bajo OFF.

CI R10 independiente deriva del aislamiento R0/R9: Python 3.12, PostgreSQL 16,
red interna, recursos efímeros del job, sin tokens en tests. Dos jobs sobre el SHA
exacto: suite y focal Alembic R1–R10 sin recrear metadata. Node solo se instala en
la imagen efímera de pruebas, no como dependencia de aplicación ni en este PC.
Ruff, colección, fases, integridad, aislamiento y limpieza siguen siendo gates.

El perfil histórico activa explícitamente ambos flags solo en ENVIRONMENT=testing
para conservar las 1410 pruebas R9, incluidas funcionalidades fuera del release.
No se modifica producto durante tests ni se inyecta autoridad a filas. R10 restablece
OFF mediante su fixture y prueba también la ausencia de flags. Esto distingue
compatibilidad histórica de permiso productivo. Adaptación histórica declarada:
test_production_rejects_blank_required_secrets fija ambos flags false para aislar
su condición original bajo ese perfil; mantiene la misma aserción de secretos.

## Límites y entrega

No activación, deploy, PR, merge ni tags. No ensayos contra recursos operativos.
Las instancias antiguas requieren detenerse en una activación futura autorizada;
R10 no revoca llamadas previamente iniciadas por binarios anteriores.
H05.agotamiento_fallback sigue abierto, sin modificación. No se asegura entrega
externa exactamente una vez ni se reescribe evidencia R1–R9.
Resultados y SHA final pertenecen al informe posterior al CI, separado de este
contrato previo. Solo se marcarán resueltos los gates demostrados.
