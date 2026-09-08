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
