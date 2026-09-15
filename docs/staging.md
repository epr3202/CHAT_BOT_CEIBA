# A1 — infraestructura de staging

Estado: definición implementada; validación CI pendiente en el candidato. El servidor
real sigue sin identificarse/provisionarse. No se declara A1 terminado sin esa evidencia.
Base R11: cc18f66f297b09b6232588ae5d66b1ecfa205a5e.

## Topología y límites

`compose.staging.yml` es un perfil de infraestructura independiente. Reutiliza `db`
de `compose.protected.yml` mediante extends, sin modificar el perfil protegido.
Proyecto fijo `ceiba-staging`, volumen `ceiba-staging_postgres_data`, red interna
`ceiba-staging_database`; PostgreSQL 16 con digest, healthcheck y puerto interno 5432,
sin publicación. TLS usa nginx 1.28.0-alpine y red `ceiba-staging_edge`, sin acceso a DB.
Solo publica 127.0.0.1:8443. No usar este proyecto ni su volumen para producción.
Requiere host Linux dedicado a staging, Docker local y Compose v2 con extends y up --wait.

TLS sirve `/infra-health`; cualquier otra ruta devuelve 503. A1 prepara terminación
TLS, no configura rutas de aplicación ni inicia API, frontend o worker. El despliegue
posterior deberá integrar las redes preservando este volumen e identidad, manteniendo
el cierre de ingreso hasta su certificación. No combinar directamente ambos perfiles.
No hay migraciones: DB nueva sin schema; head del código sigue 20260910_0027.

## Entradas externas

El operador aporta host staging, cuenta SSH, checkout Linux y nombre DNS cubierto por
un certificado real. Suministrar un archivo externo de variables de shell, propietario
del operador, modo 0600, fuera del checkout. `.env.staging.example` es inventario,
no una configuración ejecutable. Exportar antes de los comandos:

- `ENVIRONMENT=staging`.
- `POSTGRES_DB`, `POSTGRES_USER`: identidades reales exclusivas de staging.
- `POSTGRES_PASSWORD`: valor aleatorio >=24 caracteres, sin default; conservar en
  almacenamiento de secretos. Cambiarlo no rota automáticamente una DB existente.
- `STAGING_TLS_CERT`: ruta absoluta al PEM con cadena del certificado.
- `STAGING_TLS_KEY`: ruta absoluta a clave PEM, propietario operador/root, modo 0600.
- `STAGING_TLS_NAME`: DNS presente en SAN del certificado.

No requiere secretos Meta/OpenRouter/Calendar ni imágenes de aplicación. Certificados
y clave fuera del checkout, montaje RO, sin creación automática de rutas faltantes.
El operador obtiene/renueva el certificado mediante su CA y reinicia solo `tls` tras
renovación; A1 no solicita dominios ni certificados a proveedores. Los autofirmados
solo se generan efímeramente en CI. La verificación hace TLS con validación de nombre,
vigencia y confianza explícita en el PEM suministrado; no acredita la titularidad DNS.
El healthcheck interno solo comprueba liveness, y no reemplaza esa verificación TLS.

## Operación reproducible en el servidor staging

Desde el checkout, con las variables anteriores exportadas y permisos Docker:

```sh
python3 -m scripts.staging config
python3 -m scripts.staging up
python3 -m scripts.staging ps
python3 -m scripts.staging logs
python3 -m scripts.staging verify
python3 -m scripts.staging target
python3 -m scripts.staging stop
```

`config` valida Compose sin imprimir contraseñas; `up` espera salud y verifica TLS/DB.
`target` escribe exclusivamente un nuevo `target.staging.json` ignorado por Git tras
verificar servicios. Incluye hostname real, checkout, system_identifier observado,
DB/user/host/puerto, proyecto y DNS TLS, nunca contraseña ni clave. Si ya existe, aborta.
Es el inventario **A1-infrastructure**, no un target autorizado para `release.py`:
los hooks PRE/ingreso y custodia de backup de R11 siguen pendientes de otro alcance.
No hay target real versionado porque no se conoce el host. CI genera su propio target
real efímero del runner; no representa el destino operativo.

Administración solo mediante SSH autenticado al host. Desde la estación autorizada,
con `STAGING_SSH_DESTINATION` definido por el operador:

```sh
ssh -N -L 8443:127.0.0.1:8443 "$STAGING_SSH_DESTINATION"
```

Usar el nombre DNS del certificado para la conexión TLS a través del túnel (resolución
local a loopback). No abrir 8443/5432/8000/5173 en interfaces públicas. Verificar desde
otra máquina que 8443/5432 no aceptan conexiones; registrar firewall/SSH del host.
Los usuarios locales del host pueden alcanzar loopback; requiere host de confianza.

## Verificación y persistencia

CI existente añade un job A1 en runner GitHub desechable: Compose real, arranque,
PG16/salud, tabla sintética que sobrevive force-recreate, identidad DB estable,
red interna y ausencia de puertos DB, TLS con SAN verificado, target JSON sin
placeholders y cobertura gitignore/ausencia de claves versionadas. La suite Python,
Node y Ruff siguen en el job existente. Nunca usar `scripts.quality.staging_ci` en
un host operativo: exige runner GitHub-hosted y elimina únicamente su volumen efímero.
En staging, conservar evidencia de `verify` antes/después de una recreación autorizada
de `db`; no ejecutar pruebas destructivas ni crear tablas de prueba operativas.
`stop` conserva contenedores y volumen; nunca usar down --volumes en staging.

Pendiente externo: host/SSH, DNS/certificado y custodia de secretos, ejecución de los
comandos, evidencia de persistencia del destino y prueba de inaccesibilidad desde fuera.
PRE-01..18, restauración funcional, providers y aplicación no forman parte de A1.
