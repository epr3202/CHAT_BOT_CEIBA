# Seguimiento pendiente

## Auditoría 2026-09-07 — HEAD 8935687

[Informe y 28 hallazgos](audits/2026-09-07-8935687/report.md) · [Registro CSV](audits/2026-09-07-8935687/findings.csv) · [Plan de PR propuestos](audits/2026-09-07-8935687/remediation_plan.md).

- Ratificar alcance candidato y SLA: H18/H26, PR-00; ninguna reducción se da por aprobada.
- Corregir capacidad de recuperar entradas y continuidad conversacional: H01/H04/H05/H06/H17.
- Asegurar pausa/propiedad humana y entrega: H02/H03/H11/H24.
- Resolver agenda/recordatorios: H07/H08/H09; distinguir visita de reserva comercial.
- Revisar configuración/build/deploy/contenido y seguridad de herramientas: H10/H13/H14/H15/H16/H21.
- Aportar evidencia operativa y suite completa en entorno desechable: H19/H23/H28, VAL-01.
- Planificar deuda con mitigación explícita: H12/H20/H22/H25/H27.

Estado: **propuestas pendientes**, sin fixes, commits, push ni despliegue en la auditoría. Responsables y aprobación de negocio/operación aún por asignar; no se inventan fechas. La retención W2-b está explícitamente diferida en scope, pero necesita seguimiento operativo.


## 2026-09-08 ? R1 H02.Outbox

H02.Outbox: RESUELTO_EN_CANDIDATO en 66a398124c007bdc54895fe891601e470910ce8e, run 34235830150. Suite 672 PASS (635 R0 + 37 nuevas); focalizados 37 PASS sobre Alembic, subconjunto de la suite. H02.payment, orden y comandos humanos siguen pendientes. H02 agregado, H01 y otros hallazgos no se cierran. Sin autorizacion de produccion.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

H01: implementacion R2 candidata y validacion en curso; consultar el informe final antes de atribuir cierre. Pendientes operativos: revision de legacy ambiguo, reconciliacion externa y activacion coordinada no ejecutada. Continuan abiertos H02.payment, orden de salidas, comandos humanos, H03/H04/H05/H06/H07/H17/H29 y los demas hallazgos fuera de R2.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

H04 en validacion R3; el informe final delimita el veredicto por frontera. H01 local/H02.Outbox conservan cierre candidato. H05, H03, H17, H29, H02.payment y demas hallazgos siguen abiertos. Activacion/reconciliacion operativa R1/R2 no ejecutadas.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 — R4 solicitud explícita de asesor

H05.solicitud_explicita en validación R4; H05.agotamiento_fallback sigue abierto. H03/H17/H29/H02.payment, orden de salida y autorizaciones no cambian. Activación/reconciliación R1/R2 pendiente.

[Contrato y validación R4](remediation/r4-h05-explicit-human-2026-09-08/README.md).


## R5 en validacion: H03.entrada_multimedia / U12a

Guard de medios pausados y captura pasiva en inbox R2; candidato pendiente de CI.
Sin cambios al worker de comprobantes ni invalidacion de Outbox previo (U12c).
Contrato y evidencia: [R5](remediation/r5-h03-media-2026-09-09/README.md).

## R6 en validación — H17.contrato_y_consumo_de_pendientes / U03

BASE R5 aprobada d237ad7/run 34364403706. R6 distingue propuestas de clasificación y
nombre de resoluciones inertes, valida contexto legacy y retira autoridad al negar o
reemplazar. Consumo y descarte permanecen bajo R2; sin migración ni activación.
[Contrato, RED y límites R6](remediation/r6-h17-confirmations-2026-09-09/README.md).

## R7 en validacion — H29 / U04

BASE R6 aprobada cfdc09b/run 34381466698. Contrato semantico de nueve entidades antes
de aplicarlas, sin migraciones ni activacion. RED sobre producto BASE intacto.
[Contrato y evidencia R7](remediation/r7-h29-entities-2026-09-09/README.md).

R7 candidato: frontera pura para las nueve entidades, revalidación en consumidores,
correcciones rechazadas con aclaración y conservación del valor previo. RED3:
962957346a93ce0fc177bee377af7ac9332983d8 / run 34397740618.
Seis expectativas R6 de propuesta de nombre se adaptan conforme al contrato documentado;
se conservan sus nodos. Validación remota pendiente. Cero migraciones; H29 agregado abierto.

## R8 — H11.propiedad_mutaciones_humanas / U12b (2026-09-10)

Contrato previo y reproduccion de propiedad en respuesta/retorno. BASE R7 `9af02027672049c1d73f998e9be1fe8c070e791f`; producto BASE intacto durante RED. ADMIN sin override automatico; reasignacion explicita pendiente. [Contrato R8](remediation/r8-h11-ownership-2026-09-10/README.md). H11 agregado permanece abierto; no activacion.

R8 candidato: propiedad por ID dentro de la transaccion y locks Conversation -> Handoff;
sin override ADMIN. Toma pendiente conserva WAITING_FOR_HUMAN; respuesta/retorno exigen
HUMAN_ACTIVE con bot pausado. Una fixture historica usa ahora la sesion de su propietario.
Resultado definitivo, SHA y evidencias quedan en el informe local post-CI; H11 agregado
y U12c siguen abiertos. Sin migraciones ni activacion.


## R9 — H03.outbox_previo / U12c (2026-09-10)

Contrato previo y RED sobre BASE R8 `068815555a266b784bafc8dd521ca618eabbf30a`: origen, invalidación durable y admisión local del Outbox ante pausa. [Diseño R9](remediation/r9-u12c-outbox-pause-2026-09-10/README.md). Validación remota pendiente; H03/H11 agregados permanecen abiertos. Sin activación.

R9 candidato implementa procedencia de servidor, período durable y admisión por intento; migración aditiva 20260910_0027. La validación remota y el informe final post-CI siguen separados; sin activación ni cierre de H03/H11 agregados.

## R10 — Release scope enforcement (2026-09-14)

BASE R9 a9ce7f34342f19022ae608ab48bad4b0654b52d2. Candidato incremental: PaymentEvidence
automation OFF, Calendar writes OFF, Reminders OFF; simuladores y fake adapters
prohibidos en production/staging. Captura pasiva multimedia e Inbox/Outbox siguen ON.
Flags seguros y validación temprana; guards antes de DB/HTTP. Revisión humana conservada.
Sin migración: head 20260910_0027. Pruebas R10 y regresión remota pendientes de CI.
No cerrar H05 ni declarar pagos, agenda o recordatorios completos; se restringen para
este release. [Contrato, tests y límites](remediation/r10-release-scope-2026-09-14/README.md).

### R10.1 — Riesgo temporal vecino no corregido (2026-09-14)

En tests/conversational/test_slice3_quote_capture.py, los casos
`test_tc_collect_001_multiple_fields_persist_in_one_turn` y
`test_tc_collect_002_approximate_date_triplet` esperan diciembre de 2026 con
expresiones sin año y sin ancla explícita. Otros casos reutilizan complete_entities
con fechas de 2026. Riesgo de futuros fallos del gate al envejecer esas fechas;
hallazgo estático, sin afirmar que hoy fallen. Quedan pendientes de una tarea
separada; R10.1 modifica exclusivamente la regresión de septiembre. H05 y las
funcionalidades OFF de R10 permanecen fuera del alcance de esta corrección.

## R11 operational follow-up

### PREPROD BLOCKERS
- PREPROD_TARGET=NOT_PROVISIONED: confirm host/daemon/project, DB system identity, TLS and
  restricted admin ingress; provision secret names from deployment.md without exposing values.
- Preserve the certified images/manifest and encrypted checkpoint; demonstrate restore into
  a disposable DB with revision/count/integrity checks; review ingress/smoke hooks.
- Verify Meta account Graph version and real provider credentials in the authorized next pass;
  execute frozen PRE-01..18 certification before reopening traffic.

### PRODUCTION HARDENING
- Distributed login throttling and public admin exposure review; staging requires restricted
  VPN/IP ingress. Separate DB roles/least privilege, alerting for unhealthy live workers,
  retention/PII operational controls and immutable Node base input on future dependency refresh.
- Compose detects unhealthy processes but restarts only exits; operations owns investigation.

### LATER FEATURES
H05, Calendar writes, PaymentEvidence automation and reminders remain outside this release.
Do not make their activation a prerequisite for readiness.


## A1 ? dependencias de infraestructura

Implementados perfil Compose, TLS loopback, validaci?n e inventario generable;
validaci?n remota pendiente en candidato. Falta host/SSH staging, DNS/certificados
externos y custodia de variables; ejecutar staging.md y conservar target observado,
evidencia de persistencia y rechazo de acceso externo. No cerrar A1 sin ello.
PRE-01..18, despliegue app, bootstrap de schema, restore funcional y proveedores
permanecen separados. No se modifica producci?n ni barreras R10.

Destino informado por el operador: srv1899908.hstgr.cloud (2.25.104.213),
Ubuntu24.04 x86_64, Docker29.7.2/Compose5.4.0, cuatro contenedores activos.
No equivale a staging certificado: falta inventario/aislamiento, SSH accesible
(desde Codex puerto22 agota el tiempo), DNS TLS y rutas de certificado/clave.
