# Contexto del sistema

Actualización A1 2026-09-22: DNS aprobado `staging.ceibaclubhouse.com` en Cloudflare;
checkout previsto `/home/deploy/ceiba-staging`. No hay nueva evidencia del host.
SCOPE A1 exige target completo, secretos de deployment y render protegido, incluso
si infraestructura no consume esos secretos. A1 permanece ABIERTO; el
[handoff actualizado](staging.md#a1--operator-handoff) distingue CI y operación real.

La Ceiba Club House dispone de una definición reproducible de infraestructura staging
A1; la existencia de un servidor operativo aún no está acreditada. Su propósito es
preparar PostgreSQL 16 persistente y terminación TLS privada para un despliegue posterior.
Docker Compose identifica el proyecto como `ceiba-staging`; solo ejecuta `db` y `tls`.
El acceso requiere host/túnel SSH autorizado. Producción y funcionalidades de negocio
permanecen fuera de A1. [Topología, variables y procedimiento](staging.md).

Destino informado por el operador: srv1899908.hstgr.cloud (2.25.104.213),
Ubuntu24.04 x86_64, Docker29.7.2/Compose5.4.0, cuatro contenedores activos.
No equivale a staging certificado: falta inventario/aislamiento, SSH accesible
(desde Codex puerto22 agota el tiempo), DNS TLS y rutas de certificado/clave.
