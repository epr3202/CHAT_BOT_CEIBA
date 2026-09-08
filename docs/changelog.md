# Registro de cambios

## 2026-09-07 — Auditoría técnica documental

Se auditó main / 89356876a04bc836ea9b2c223ff8aba2b424ffde. [Informe](audits/2026-09-07-8935687/report.md), matrices de 19 dimensiones/24 escenarios, 28 hallazgos y plan incremental sin implementación.

Se inventariaron 224 archivos; se recolectaron 627 pruebas y se ejecutó una selección aislada de 231, todas aprobadas tras corregir el arnés temporal. Se documentaron reproducciones de fallos y limitaciones de entorno/proveedores. Ruff y sintaxis JavaScript pasaron.

Se crean índices de contexto/arquitectura/seguimiento/decisiones y una nota README. No se corrigió ningún problema; no cambian código, prompts, reglas comerciales, pruebas versionadas, dependencias, configuración ni migraciones. Sin commit, push o despliegue. El detalle de cobertura parcial está en el informe.


## 2026-09-08 ? R1 H02.Outbox

Se agrega candidato R1: propiedad y settlement de Outbox texto/documento, migracion aditiva 0025 y regresiones reales en PostgreSQL. Reproduccion roja: 4 controles pasan y 15 carreras fallan por persistencia. Validacion verde y evidencia final en el paquete R1; sin modificar producto de otros dominios ni evidencia historica.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).
