# Arquitectura implementada

La descripciÃ³n con transacciones, lÃ­mites de confianza y seis recorridos estÃ¡ en la [auditorÃ­a de HEAD 8935687](audits/2026-09-07-8935687/report.md#arquitectura-efectiva-y-lÃ­mites-de-confianza).

El webhook persiste inbox antes de aceptar; BackgroundTasks guarda mensajes, invoca clasificaciÃ³n fuera de transacciÃ³n y llama al orquestador. Los mensajes salientes usan outbox con claim/send/settle. Las operaciones de agenda tienen transacciones propias e integraciÃ³n Google. No existe consumidor continuo de inbox ni envÃ­o operativo de recordatorios; H01/H07/H09 describen los lÃ­mites comprobados.

La coordinaciÃ³n de IA desde canal estÃ¡ aceptada por D1 de [observabilidad IA](product/ai-execution-observability.md). Las propuestas de remediaciÃ³n no se consideran arquitectura implementada. Este archivo es un Ã­ndice nuevo, no reemplaza documentaciÃ³n canÃ³nica.


## 2026-09-08 ? R1 H02.Outbox

R1 implementa en el candidato una identidad UUID por reclamacion de Outbox, snapshot inmutable y settlement con comprobacion de propiedad bajo el mismo bloqueo/transaccion que Outbox y Message. Reaper y finalizacion invalidan la identidad. MediaService compartido y payment quedan fuera.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

R2 agrega InboxJob separado de Message, consumo continuo en el worker y finalizacion atomica con efectos locales. API, worker y CLI comparten propiedad UUID por intento. Agenda se ejecuta fuera de locks y la incertidumbre externa queda REVIEW. La descripcion inicial de ausencia de consumidor corresponde al producto auditado 8935687, anterior a este candidato.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 candidato acota H04 en el cliente IA: transporte esperado normalizado, retries limitados y degradacion existente por tarea/estado. Inbox/Outbox, sus tokens y transacciones permanecen R2/R1. Sin nueva migracion.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 â€” R4 solicitud explÃ­cita de asesor

Reconocimiento textual puro al inicio de classify_message; decisiÃ³n DETERMINISTIC aplicada por HUMAN_REQUEST dentro del settlement R2, despuÃ©s de guards. Sin llamadas IA en el turno reconocido ni escritura paralela.

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

## R11 ? protected operational boundary

Protected images force an explicit staging/production environment across API, worker,
frontend and one-shot entrypoints. Compose provides three supervised application processes
and a private Postgres16 service. Startup validates critical config/storage and schema;
/live is independent of providers, /ready validates DB0027, and worker heartbeat observes
completed Inbox/Outbox polls without changing domain/claim semantics. Deployment consumes
immutable images, stops old consumers before checkpoint/migration and never downgrades.
See [deployment contract](deployment.md). Business scope and all R10 OFF guards remain frozen.


## A1 ? topolog?a staging

Perfil infra Compose ceiba-staging: PostgreSQL16 heredado del perfil protegido,
volumen persistente postgres_data, red database interna sin puerto p?blico; nginx TLS
en red edge separada con binding loopback8443. Certificados/secretos externos, admin
por SSH. No inicia aplicaci?n. Destino real pendiente. Ver [runbook](staging.md).
