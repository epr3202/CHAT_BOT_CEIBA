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
