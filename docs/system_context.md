# Contexto del sistema

La Ceiba Club House dispone de una definición reproducible de infraestructura staging
A1; la existencia de un servidor operativo aún no está acreditada. Su propósito es
preparar PostgreSQL 16 persistente y terminación TLS privada para un despliegue posterior.
Docker Compose identifica el proyecto como `ceiba-staging`; solo ejecuta `db` y `tls`.
El acceso requiere host/túnel SSH autorizado. Producción y funcionalidades de negocio
permanecen fuera de A1. [Topología, variables y procedimiento](staging.md).
