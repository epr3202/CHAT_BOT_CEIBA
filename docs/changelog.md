# Registro de cambios

## 2026-09-07 — Auditoría técnica documental

Se auditó main / 89356876a04bc836ea9b2c223ff8aba2b424ffde. [Informe](audits/2026-09-07-8935687/report.md), matrices de 19 dimensiones/24 escenarios, 28 hallazgos y plan incremental sin implementación.

Se inventariaron 224 archivos; se recolectaron 627 pruebas y se ejecutó una selección aislada de 231, todas aprobadas tras corregir el arnés temporal. Se documentaron reproducciones de fallos y limitaciones de entorno/proveedores. Ruff y sintaxis JavaScript pasaron.

Se crean índices de contexto/arquitectura/seguimiento/decisiones y una nota README. No se corrigió ningún problema; no cambian código, prompts, reglas comerciales, pruebas versionadas, dependencias, configuración ni migraciones. Sin commit, push o despliegue. El detalle de cobertura parcial está en el informe.


## 2026-09-08 ? R1 H02.Outbox

Se agrega candidato R1: propiedad y settlement de Outbox texto/documento, migracion aditiva 0025 y regresiones reales en PostgreSQL. Reproduccion roja: 4 controles pasan y 15 carreras fallan por persistencia. Validacion verde y evidencia final en el paquete R1; sin modificar producto de otros dominios ni evidencia historica.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).

Cierre local R1: candidato 66a398124c007bdc54895fe891601e470910ce8e, run 34235830150 aprobado. 672 PASS; 37 focalizados incluidos, migracion/paridad/rollback y Ruff aprobados; cero intentos de red inesperados. [Informe final](remediation/r1-h02-outbox-2026-09-08/report.md). Este cierre documental local es posterior al SHA probado; el producto coincide byte a byte tras normalizar finales de linea.


## 2026-09-08 - R2 H01 inbox

Candidato R2: migracion 0026 sobre 0025, recuperacion automatica de inbox, CLI coordinado y 34 pruebas nuevas. Se conserva RED real y el primer intento fallido; el cierre con SHAs y hashes se documenta en el informe de validacion. Compatibilidad puntual: prueba de migracion R1 fija upgrade a 0025; inventario estricto de modelos agrega inbox_job.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 candidato: normalizacion de NetworkError, RemoteProtocolError y ProxyError; detalles tecnicos sanitizados y telemetria best-effort. RED real sobre R2, 65 controles nuevos y workflow aislado. Sin cambios de esquema/dependencias ni pruebas historicas.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).


## 2026-09-08 — R4 solicitud explícita de asesor

Candidato R4: ruta previa para solicitud inequívoca de asesor, pruebas por frases/estado/propiedad/commit y bandeja real. Dos adaptaciones históricas acotadas de llamadas IA se documentan. Sin migraciones.

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
