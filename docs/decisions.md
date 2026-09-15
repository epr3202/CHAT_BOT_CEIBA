# Decisiones y propuestas

## Propuestas de auditorÃ­a â€” 2026-09-07

**Estado: PROPUESTAS, no aceptadas ni implementadas.** Base HEAD 8935687. [Plan completo](audits/2026-09-07-8935687/remediation_plan.md).

- Ratificar alcance candidato y calendario de SLA (H18/H26).
- Separar identidad del mensaje y finalizaciÃ³n durable, con claims verificables (H01/H02).
- Unificar pausa humana y autorizaciÃ³n de acciones sobre casos (H03/H11).
- Definir operaciÃ³n durable y reconciliaciÃ³n de agenda (H07/H08).
- Promover artefacto/SHA probado y contenido versionado explÃ­citamente (H13/H16).
- Acordar retenciÃ³n/minimizaciÃ³n efectiva y evidencia de recuperaciÃ³n (H19/H20).

Las decisiones aceptadas anteriores continÃºan en sus documentos canÃ³nicos, especialmente D1 y otras decisiones de [observabilidad IA](product/ai-execution-observability.md). No se acepta una reducciÃ³n del MVP, una nueva infraestructura ni excepciones a append-only por crear este Ã­ndice. AGENTS.md permanece sin modificaciones.


## 2026-09-08 ? R1 H02.Outbox

Decision R1 limitada: UUID nullable por adquisicion, sin backfill de propietarios antiguos; liquidacion exige token obligatorio. Expiracion efectiva por reaper. No es segura la convivencia con workers antiguos que liquidan por ID. El procedimiento de activacion propuesto exige detenerlos; no se despliega.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

Decision R2 limitada: control durable por Message, orden local por conversacion, reintentos acotados, finalizacion silenciosa explicita y separacion de operaciones de agenda. No hay backfill de exito ni convivencia segura con API/worker/CLI antiguos. No completa H06/H07 ni modifica las reglas de negocio.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 conserva AIUnavailable y HTTP_ERROR para llamada fallida con subtipo sanitizado, TIMEOUT separado. No captura indiscriminadamente TransportError/Exception; configuracion, cancelacion y programacion conservan propagacion. No se cambian prompts ni rutas comerciales.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 â€” R4 solicitud explÃ­cita de asesor

R4 separa H05.solicitud_explicita de H05.agotamiento_fallback. Coincidencia completa de catÃ¡logo estrecho; ambiguos/mezclas mantienen ruta anterior. Procedencia determinista explÃ­cita, sin probabilidad calibrada ni cambios de umbrales IA.

[Contrato y validaciÃ³n R4](remediation/r4-h05-explicit-human-2026-09-08/README.md).


## R5 en validacion: H03.entrada_multimedia / U12a

Guard de medios pausados y captura pasiva en inbox R2; candidato pendiente de CI.
Sin cambios al worker de comprobantes ni invalidacion de Outbox previo (U12c).
Contrato y evidencia: [R5](remediation/r5-h03-media-2026-09-09/README.md).

## R6 en validaciÃ³n â€” H17.contrato_y_consumo_de_pendientes / U03

BASE R5 aprobada d237ad7/run 34364403706. R6 distingue propuestas de clasificaciÃ³n y
nombre de resoluciones inertes, valida contexto legacy y retira autoridad al negar o
reemplazar. Consumo y descarte permanecen bajo R2; sin migraciÃ³n ni activaciÃ³n.
[Contrato, RED y lÃ­mites R6](remediation/r6-h17-confirmations-2026-09-09/README.md).

## R7 en validacion â€” H29 / U04

BASE R6 aprobada cfdc09b/run 34381466698. Contrato semantico de nueve entidades antes
de aplicarlas, sin migraciones ni activacion. RED sobre producto BASE intacto.
[Contrato y evidencia R7](remediation/r7-h29-entities-2026-09-09/README.md).

R7 candidato: frontera pura para las nueve entidades, revalidaciÃ³n en consumidores,
correcciones rechazadas con aclaraciÃ³n y conservaciÃ³n del valor previo. RED3:
962957346a93ce0fc177bee377af7ac9332983d8 / run 34397740618.
Seis expectativas R6 de propuesta de nombre se adaptan conforme al contrato documentado;
se conservan sus nodos. ValidaciÃ³n remota pendiente. Cero migraciones; H29 agregado abierto.

## R8 â€” H11.propiedad_mutaciones_humanas / U12b (2026-09-10)

Contrato previo y reproduccion de propiedad en respuesta/retorno. BASE R7 `9af02027672049c1d73f998e9be1fe8c070e791f`; producto BASE intacto durante RED. ADMIN sin override automatico; reasignacion explicita pendiente. [Contrato R8](remediation/r8-h11-ownership-2026-09-10/README.md). H11 agregado permanece abierto; no activacion.

R8 candidato: propiedad por ID dentro de la transaccion y locks Conversation -> Handoff;
sin override ADMIN. Toma pendiente conserva WAITING_FOR_HUMAN; respuesta/retorno exigen
HUMAN_ACTIVE con bot pausado. Una fixture historica usa ahora la sesion de su propietario.
Resultado definitivo, SHA y evidencias quedan en el informe local post-CI; H11 agregado
y U12c siguen abiertos. Sin migraciones ni activacion.


## R9 â€” H03.outbox_previo / U12c (2026-09-10)

Contrato previo y RED sobre BASE R8 `068815555a266b784bafc8dd521ca618eabbf30a`: origen, invalidaciÃ³n durable y admisiÃ³n local del Outbox ante pausa. [DiseÃ±o R9](remediation/r9-u12c-outbox-pause-2026-09-10/README.md). ValidaciÃ³n remota pendiente; H03/H11 agregados permanecen abiertos. Sin activaciÃ³n.

R9 candidato implementa procedencia de servidor, perÃ­odo durable y admisiÃ³n por intento; migraciÃ³n aditiva 20260910_0027. La validaciÃ³n remota y el informe final post-CI siguen separados; sin activaciÃ³n ni cierre de H03/H11 agregados.

## R10 â€” Release scope enforcement (2026-09-14)

BASE R9 a9ce7f34342f19022ae608ab48bad4b0654b52d2. Candidato incremental: PaymentEvidence
automation OFF, Calendar writes OFF, Reminders OFF; simuladores y fake adapters
prohibidos en production/staging. Captura pasiva multimedia e Inbox/Outbox siguen ON.
Flags seguros y validaciÃ³n temprana; guards antes de DB/HTTP. RevisiÃ³n humana conservada.
Sin migraciÃ³n: head 20260910_0027. Pruebas R10 y regresiÃ³n remota pendientes de CI.
No cerrar H05 ni declarar pagos, agenda o recordatorios completos; se restringen para
este release. [Contrato, tests y lÃ­mites](remediation/r10-release-scope-2026-09-14/README.md).

## R10.1 â€” Contrato temporal existente explicitado (2026-09-14)

Para una fecha de evento con dÃ­a/mes sin aÃ±o, la interpretaciÃ³n existente usa la
prÃ³xima ocurrencia no pasada respecto de la fecha de America/Bogota. Por ejemplo,
el 13 de septiembre se resuelve a 2027-09-13 si hoy es 2026-09-14. El aÃ±o pasado
propuesto por el LLM no reemplaza el texto sin aÃ±o del cliente. No es una nueva
regla de producto: entities.md Â§8.1 exige validar el pasado e inferir con contexto;
el detalle estÃ¡ implementado desde 36efa72 y probado en
`test_date_parser_resolves_yearless_exact_dates_to_next_future_occurrence` y
`test_date_parser_never_resolves_yearless_date_to_past`. R10.1 fija el reloj de
una regresiÃ³n histÃ³rica, sin alterar esa semÃ¡ntica ni las barreras R10.

## R11 ? explicit deployed environment and immutable operational identity

A deployed image must declare ENVIRONMENT=staging/production; only the explicitly local
Compose profile or local Python may retain development ergonomics. Protected entrypoints
force DEPLOYED_RUNTIME=true. Deployment requires full SHA/tree and image IDs, builds once
from Git archive, and promotes unchanged images. No mutable branch selection or automatic
SSH deployment. Consumers stop before encrypted/verifiable backup and exact0027 migration.
Rollback requires a reviewed safe artifact descended from R10.1 and compatible0027; no R9
fallback or schema downgrade. Payment automation, Calendar writes and reminders remain OFF;
fake adapters and simulation remain forbidden. See deployment.md for target and restore gates.


## A1 ? aislamiento y terminaci?n TLS privada

Reutilizar db mediante Compose extends con igualdad de configuraci?n renderizada del perfil protegido. Proyecto
fijo ceiba-staging y volumen propio; nginx con certificado externo y loopback evita
exponer administraci?n. A1 genera inventario observado tras verificar el destino;
no inventa host, hooks ni certificados. No autoriza despliegue de aplicaci?n.
