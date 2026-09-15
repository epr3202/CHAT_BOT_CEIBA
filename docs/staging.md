# A1 â€” infraestructura de staging

Estado: definiciÃ³n implementada; validaciÃ³n CI pendiente en el candidato. El servidor
real sigue sin identificarse/provisionarse. No se declara A1 terminado sin esa evidencia.
Base R11: cc18f66f297b09b6232588ae5d66b1ecfa205a5e.

## TopologÃ­a y lÃ­mites

`compose.staging.yml` es un perfil de infraestructura independiente. Reutiliza `db`
extra?do sin cambios a `compose.postgres.yml` mediante extends, con igualdad de configuraci?n renderizada del perfil protegido.
Proyecto fijo `ceiba-staging`, volumen `ceiba-staging_postgres_data`, red interna
`ceiba-staging_database`; PostgreSQL 16 con digest, healthcheck y puerto interno 5432,
sin publicaciÃ³n. TLS usa nginx 1.28.0-alpine y red `ceiba-staging_edge`, sin acceso a DB.
Solo publica 127.0.0.1:8443. No usar este proyecto ni su volumen para producciÃ³n.
Requiere host Linux dedicado a staging, Docker local y Compose v2 con extends y up --wait.

TLS sirve `/infra-health`; cualquier otra ruta devuelve 503. A1 prepara terminaciÃ³n
TLS, no configura rutas de aplicaciÃ³n ni inicia API, frontend o worker. El despliegue
posterior deberÃ¡ integrar las redes preservando este volumen e identidad, manteniendo
el cierre de ingreso hasta su certificaciÃ³n. No combinar directamente ambos perfiles.
No hay migraciones: DB nueva sin schema; head del cÃ³digo sigue 20260910_0027.

## Entradas externas

El operador aporta host staging, cuenta SSH, checkout Linux y nombre DNS cubierto por
un certificado real. Suministrar un archivo externo de variables de shell, propietario
del operador, modo 0600, fuera del checkout. `.env.staging.example` es inventario,
no una configuraciÃ³n ejecutable. Exportar antes de los comandos:

- `ENVIRONMENT=staging`.
- `POSTGRES_DB`, `POSTGRES_USER`: identidades reales exclusivas de staging.
- `POSTGRES_PASSWORD`: valor aleatorio >=24 caracteres, sin default; conservar en
  almacenamiento de secretos. Cambiarlo no rota automÃ¡ticamente una DB existente.
- `STAGING_TLS_CERT`: ruta absoluta al PEM con cadena del certificado.
- `STAGING_TLS_KEY`: ruta absoluta a clave PEM, propietario operador/root, modo 0600.
- `STAGING_TLS_NAME`: DNS presente en SAN del certificado.

No requiere secretos Meta/OpenRouter/Calendar ni imÃ¡genes de aplicaciÃ³n. Certificados
y clave fuera del checkout, montaje RO, sin creaciÃ³n automÃ¡tica de rutas faltantes.
El operador obtiene/renueva el certificado mediante su CA y reinicia solo `tls` tras
renovaciÃ³n; A1 no solicita dominios ni certificados a proveedores. Los autofirmados
solo se generan efÃ­meramente en CI. La verificaciÃ³n hace TLS con validaciÃ³n de nombre,
vigencia y confianza explÃ­cita en el PEM suministrado; no acredita la titularidad DNS.
El healthcheck interno solo comprueba liveness, y no reemplaza esa verificaciÃ³n TLS.

## OperaciÃ³n reproducible en el servidor staging

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

`config` valida Compose sin imprimir contraseÃ±as; `up` espera salud y verifica TLS/DB.
`target` escribe exclusivamente un nuevo `target.staging.json` ignorado por Git tras
verificar servicios. Incluye hostname real, checkout, system_identifier observado,
DB/user/host/puerto, proyecto y DNS TLS, nunca contraseÃ±a ni clave. Si ya existe, aborta.
Es el inventario **A1-infrastructure**, no un target autorizado para `release.py`:
los hooks PRE/ingreso y custodia de backup de R11 siguen pendientes de otro alcance.
No hay target real versionado porque no se conoce el host. CI genera su propio target
real efÃ­mero del runner; no representa el destino operativo.

AdministraciÃ³n solo mediante SSH autenticado al host. Desde la estaciÃ³n autorizada,
con `STAGING_SSH_DESTINATION` definido por el operador:

```sh
ssh -N -L 8443:127.0.0.1:8443 "$STAGING_SSH_DESTINATION"
```

Usar el nombre DNS del certificado para la conexiÃ³n TLS a travÃ©s del tÃºnel (resoluciÃ³n
local a loopback). No abrir 8443/5432/8000/5173 en interfaces pÃºblicas. Verificar desde
otra mÃ¡quina que 8443/5432 no aceptan conexiones; registrar firewall/SSH del host.
Los usuarios locales del host pueden alcanzar loopback; requiere host de confianza.

## VerificaciÃ³n y persistencia

CI existente aÃ±ade un job A1 en runner GitHub desechable: Compose real, arranque,
PG16/salud, tabla sintÃ©tica que sobrevive force-recreate, identidad DB estable,
red interna y ausencia de puertos DB, TLS con SAN verificado, target JSON sin
placeholders y cobertura gitignore/ausencia de claves versionadas. La suite Python,
Node y Ruff siguen en el job existente. Nunca usar `scripts.quality.staging_ci` en
un host operativo: exige runner GitHub-hosted y elimina Ãºnicamente su volumen efÃ­mero.
En staging, conservar evidencia de `verify` antes/despuÃ©s de una recreaciÃ³n autorizada
de `db`; no ejecutar pruebas destructivas ni crear tablas de prueba operativas.
`stop` conserva contenedores y volumen; nunca usar down --volumes en staging.

Pendiente externo: host/SSH, DNS/certificado y custodia de secretos, ejecuciÃ³n de los
comandos, evidencia de persistencia del destino y prueba de inaccesibilidad desde fuera.
PRE-01..18, restauraciÃ³n funcional, providers y aplicaciÃ³n no forman parte de A1.
