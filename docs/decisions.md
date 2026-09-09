# Decisiones y propuestas

## Propuestas de auditoría — 2026-09-07

**Estado: PROPUESTAS, no aceptadas ni implementadas.** Base HEAD 8935687. [Plan completo](audits/2026-09-07-8935687/remediation_plan.md).

- Ratificar alcance candidato y calendario de SLA (H18/H26).
- Separar identidad del mensaje y finalización durable, con claims verificables (H01/H02).
- Unificar pausa humana y autorización de acciones sobre casos (H03/H11).
- Definir operación durable y reconciliación de agenda (H07/H08).
- Promover artefacto/SHA probado y contenido versionado explícitamente (H13/H16).
- Acordar retención/minimización efectiva y evidencia de recuperación (H19/H20).

Las decisiones aceptadas anteriores continúan en sus documentos canónicos, especialmente D1 y otras decisiones de [observabilidad IA](product/ai-execution-observability.md). No se acepta una reducción del MVP, una nueva infraestructura ni excepciones a append-only por crear este índice. AGENTS.md permanece sin modificaciones.


## 2026-09-08 ? R1 H02.Outbox

Decision R1 limitada: UUID nullable por adquisicion, sin backfill de propietarios antiguos; liquidacion exige token obligatorio. Expiracion efectiva por reaper. No es segura la convivencia con workers antiguos que liquidan por ID. El procedimiento de activacion propuesto exige detenerlos; no se despliega.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

Decision R2 limitada: control durable por Message, orden local por conversacion, reintentos acotados, finalizacion silenciosa explicita y separacion de operaciones de agenda. No hay backfill de exito ni convivencia segura con API/worker/CLI antiguos. No completa H06/H07 ni modifica las reglas de negocio.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 conserva AIUnavailable y HTTP_ERROR para llamada fallida con subtipo sanitizado, TIMEOUT separado. No captura indiscriminadamente TransportError/Exception; configuracion, cancelacion y programacion conservan propagacion. No se cambian prompts ni rutas comerciales.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 — R4 solicitud explícita de asesor

R4 separa H05.solicitud_explicita de H05.agotamiento_fallback. Coincidencia completa de catálogo estrecho; ambiguos/mezclas mantienen ruta anterior. Procedencia determinista explícita, sin probabilidad calibrada ni cambios de umbrales IA.

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