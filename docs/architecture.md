# Arquitectura implementada

La descripción con transacciones, límites de confianza y seis recorridos está en la [auditoría de HEAD 8935687](audits/2026-09-07-8935687/report.md#arquitectura-efectiva-y-límites-de-confianza).

El webhook persiste inbox antes de aceptar; BackgroundTasks guarda mensajes, invoca clasificación fuera de transacción y llama al orquestador. Los mensajes salientes usan outbox con claim/send/settle. Las operaciones de agenda tienen transacciones propias e integración Google. No existe consumidor continuo de inbox ni envío operativo de recordatorios; H01/H07/H09 describen los límites comprobados.

La coordinación de IA desde canal está aceptada por D1 de [observabilidad IA](product/ai-execution-observability.md). Las propuestas de remediación no se consideran arquitectura implementada. Este archivo es un índice nuevo, no reemplaza documentación canónica.


## 2026-09-08 ? R1 H02.Outbox

R1 implementa en el candidato una identidad UUID por reclamacion de Outbox, snapshot inmutable y settlement con comprobacion de propiedad bajo el mismo bloqueo/transaccion que Outbox y Message. Reaper y finalizacion invalidan la identidad. MediaService compartido y payment quedan fuera.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

R2 agrega InboxJob separado de Message, consumo continuo en el worker y finalizacion atomica con efectos locales. API, worker y CLI comparten propiedad UUID por intento. Agenda se ejecuta fuera de locks y la incertidumbre externa queda REVIEW. La descripcion inicial de ausencia de consumidor corresponde al producto auditado 8935687, anterior a este candidato.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 candidato acota H04 en el cliente IA: transporte esperado normalizado, retries limitados y degradacion existente por tarea/estado. Inbox/Outbox, sus tokens y transacciones permanecen R2/R1. Sin nueva migracion.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 — R4 solicitud explícita de asesor

Reconocimiento textual puro al inicio de classify_message; decisión DETERMINISTIC aplicada por HUMAN_REQUEST dentro del settlement R2, después de guards. Sin llamadas IA en el turno reconocido ni escritura paralela.

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
