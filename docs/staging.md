# A1 — preparación y operación de preproducción

**A1: ABIERTO.** Desarrollo/CI no acredita provisionamiento operativo.
Base auditada: `60805c1d84760fdaa6fb2bfbb4bafe81c1e422db`.
Entradas del operador: host `srv1899908.hstgr.cloud`, IP `2.25.104.213`, checkout
`/home/deploy/ceiba-staging`, DNS aprobado `staging.ceibaclubhouse.com`, Cloudflare.
No son observaciones de esta revisión ni se han recibido secretos operativos.

## Contrato y discrepancias

Gobierna la sección A1 del documento externo `SCOPE (1) (1).md`, facilitado por el
usuario el 2026-09-22. No está versionado como SCOPE.md y no se modifica.
Conservar esa fuente con la evidencia de cierre.

El runbook anterior aplazaba hooks/GPG, decía que A1 no requería secretos de
aplicación y solo generaba `target.staging.json`. **Eso no satisface SCOPE A1**:
exige los diez campos del target de deployment, todos sus secretos provisionados
y render de `compose.protected.yml`. Provisionar/revisar estos recursos pertenece
a A1; ejecutar hooks de PRE/despliegue o restaurar backups pertenece a otros pases.
No crear hooks dummy. La estructura válida tampoco demuestra que un hook sea correcto.

SCOPE exige Compose **v2**. El informe previo del operador citó 5.4.0, sin evidencia
actual. Verificar v2 en el destino o mantener el criterio pendiente; no sustituir
Docker/Compose compartido ni reinterpretar el contrato por compatibilidad funcional.

`scripts.staging target` sigue generando inventario **parcial observado**. No es
el target contractual. `validate_target` comprueba estructura de los diez campos,
no autenticidad del host, certificados, hooks ni custodia GPG. El procedimiento
final combina observaciones con cinco valores reales del operador; nunca defaults.

## Topología y auditoría previa a correcciones

El perfil independiente `compose.staging.yml` solo inicia db y tls. PostgreSQL16
con digest hereda `compose.postgres.yml`; volumen `ceiba-staging_postgres_data`,
red interna `ceiba-staging_database`, sin publicación de 5432. nginx solo usa
`ceiba-staging_edge`, TLS externo RO y `127.0.0.1:8443`. `/infra-health` responde
salud; otras rutas dan 503. No es todavía el panel administrativo.

| Componente | Implementado en 60805c1 | Validable en CI | Requiere operador | Requiere secreto | Requiere host real para cierre |
| --- | --- | --- | --- | --- | --- |
| PG16, proyecto, red, volumen y salud | Sí | Compose real | Sí | POSTGRES_PASSWORD | Sí |
| TLS RO y loopback | Sí | Certificado efímero CI | Sí | Clave TLS | Sí, CA real |
| DNS Cloudflare | No provisionado | Receta/contrato | Sí | CLOUDFLARE_API_TOKEN | DNS/canal real |
| system_identifier e inventario | Parcial | DB efímera | Sí | Contraseña DB | Sí |
| Target SCOPE completo | Faltaban cinco campos | Estructura | Sí | Custodia GPG | Sí |
| Rechazo NOT_PROVISIONED | No | Prueba negativa | No | No | No para probar rechazo |
| Secretos deployment | Inventariados | Nombres, no presencia | Sí | Véase inventario | Sí |
| Directorios persistentes | Documentados | Contrato | Sí | Custodia backup | Sí |
| VPN/IP e inaccesibilidad pública | No acreditadas | Binding diseñado | Sí | SSH | Sí y origen externo |

CI histórico: [34985000700](https://github.com/epr3202/CHAT_BOT_CEIBA/actions/runs/34985000700),
infra PASS, suite 1489/1489, regresiones 847/847, Node 11/11, Ruff PASS.
Evidencia conservada bajo `docs/remediation/a1-staging-2026-09-15/` del workspace
original. No atribuirla a cambios posteriores. CI usa DB y certificados efímeros,
recrea el contenedor para probar persistencia y verifica equivalencia con R11.

## Inventario por nombre

| Clase | Nombres | Uso en infraestructura A1 |
| --- | --- | --- |
| Configuración | ENVIRONMENT, POSTGRES_DB, POSTGRES_USER, STAGING_TLS_NAME, STAGING_TLS_CERT, STAGING_TLS_KEY | Sí; KEY es ruta, su contenido es secreto |
| Secreto infraestructura | POSTGRES_PASSWORD | Sí |
| Secretos contractuales deployment | DATABASE_URL, META_APP_SECRET, META_VERIFY_TOKEN, META_ACCESS_TOKEN, OPENROUTER_API_KEY | No consumidos; provisionarlos sí es criterio A1 |
| Configuración contractual | META_PHONE_NUMBER_ID, META_GRAPH_API_VERSION, CATALOG_HOST_DIR, EVIDENCE_HOST_DIR | Valores reales requeridos |
| Artefacto | API_IMAGE, FRONTEND_IMAGE | IDs reales del manifest aprobado para render protegido |
| Fijados por Compose protegido | DEPLOYED_RUNTIME, CALENDAR_ADAPTER, PAYMENT_EVIDENCE_AUTOMATION_ENABLED, CALENDAR_WRITES_ENABLED, CATALOG_STORAGE_DIR, PAYMENT_EVIDENCE_DIR | No inicia aplicación |
| Operación | CLOUDFLARE_API_TOKEN, acceso SSH, clave TLS, custodia GPG | Externos a Git |
| No requeridos por el release | GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_CALENDAR_ID, GOOGLE_FREEBUSY_CALENDAR_IDS | No |

`.env.staging.example` solo es inventario. No ejecutar `env`, `printenv`, `set -x`
ni Compose config sin `--quiet` en evidencia. No guardar inspect/logs completos:
pueden contener secretos. Los archivos operativos están ignorados; revisar el diff
antes de publicar. Un escaneo no prueba ausencia de todos los secretos posibles.

## A1 — Operator Handoff

### Ya validado

- Infraestructura de CI histórico asociada al SHA citado; no al host operativo.
- Pruebas de rechazo de placeholders, vacíos, producción, topología insegura,
  TLS dentro del checkout, permisos inseguros y errores de comando sanitizados.
- Separación explícita de inventario parcial y target contractual completo.

### Pendiente en entorno real

- DNS Cloudflare, propagación, TLS real y renovación/custodia.
- SSH, identidad del daemon/host, Compose v2 y aislamiento de proyectos existentes.
- PostgreSQL16, system_identifier, persistencia, mounts RO, binding y VPN/IP aprobada.
- POSTGRES_PASSWORD, DATABASE_URL, META_APP_SECRET, META_VERIFY_TOKEN,
  META_ACCESS_TOKEN, OPENROUTER_API_KEY; configuración real del inventario.
- Directorios persistentes, GPG y hooks reales revisados, artefacto para render
  protegido, target final y evidencia de los nueve criterios SCOPE A1.

### Credenciales necesarias

- CLOUDFLARE_API_TOKEN
- acceso SSH mediante alias ceiba-staging
- POSTGRES_PASSWORD
- DATABASE_URL
- META_APP_SECRET
- META_VERIFY_TOKEN
- META_ACCESS_TOKEN
- OPENROUTER_API_KEY
- STAGING_TLS_KEY
- custodia GPG de backup

### Comandos exactos

**1. Estación autorizada:** Bash, Python3, dig, Certbot y plugin Cloudflare instalados.
Token temporal limitado a zona, con lectura de zona y edición DNS. Crear registro
solo si falta; detenerse ante conflicto. La API admite TTL y `proxied=false`
([Cloudflare](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/)).

```bash
set -euo pipefail
set +x
umask 077
dig +short A staging.ceibaclubhouse.com
read -rsp 'CLOUDFLARE_API_TOKEN: ' CLOUDFLARE_API_TOKEN; printf '\n'
export CLOUDFLARE_API_TOKEN
python3 - <<'PY'
import json, os, urllib.request
def api(path, data=None):
    req = urllib.request.Request('https://api.cloudflare.com/client/v4/' + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['CLOUDFLARE_API_TOKEN'],
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except Exception:
        raise SystemExit('Cloudflare: fallo; revisar acceso sin imprimir token')
    if not result.get('success'):
        raise SystemExit('Cloudflare: respuesta no exitosa')
    return result['result']
zones = api('zones?name=ceibaclubhouse.com')
if len(zones) != 1:
    raise SystemExit('Se requiere una única zona autorizada')
path = 'zones/' + zones[0]['id'] + '/dns_records'
records = api(path + '?name=staging.ceibaclubhouse.com')
expected = dict(type='A', name='staging.ceibaclubhouse.com',
                content='2.25.104.213', proxied=False, ttl=300)
if not records:
    api(path, expected)
records = api(path + '?name=staging.ceibaclubhouse.com')
if len(records) != 1 or any(records[0].get(k) != v for k, v in expected.items()):
    raise SystemExit('Registro incompatible: revisar; no se sobrescribe')
print('DNS Cloudflare: configuración verificada')
PY
dig @1.1.1.1 +short A staging.ceibaclubhouse.com
dig @8.8.8.8 +short A staging.ceibaclubhouse.com
```

Ambos resolvers deben devolver 2.25.104.213; esperar propagación si difieren.

**2. TLS real por DNS-01:** no abrir puertos del host. El plugin usa credenciales
en archivo protegido ([Certbot Cloudflare](https://certbot-dns-cloudflare.readthedocs.io/en/stable/)).
Las rutas propuestas se crean por el operador; no son recursos acreditados.

```bash
ACME_DIR="$HOME/.local/share/ceiba-staging/acme"
mkdir -p "$ACME_DIR"
CF_CREDENTIALS=$(mktemp)
trap 'rm -f -- "$CF_CREDENTIALS"; unset CLOUDFLARE_API_TOKEN' EXIT
printf 'dns_cloudflare_api_token = %s\n' "$CLOUDFLARE_API_TOKEN" > "$CF_CREDENTIALS"
chmod 600 "$CF_CREDENTIALS"
certbot certonly --dns-cloudflare --dns-cloudflare-credentials "$CF_CREDENTIALS" \
  --config-dir "$ACME_DIR/config" --work-dir "$ACME_DIR/work" --logs-dir "$ACME_DIR/logs" \
  --cert-name staging.ceibaclubhouse.com -d staging.ceibaclubhouse.com
unset CLOUDFLARE_API_TOKEN
ssh ceiba-staging
```

Certbot solicita contacto/aceptación reales. Registrar emisor, SAN, vigencia y
responsable de renovar por DNS-01. No usar almacén Certbot de producción.

**3. Host, antes de arrancar:**

```bash
set -euo pipefail
set +x
umask 077
cd /home/deploy/ceiba-staging
hostname
pwd -P
git rev-parse HEAD
git status --short
docker info --format '{{.ID}} {{.Name}} {{.ServerVersion}}'
docker compose version
docker context inspect --format '{{.Endpoints.docker.Host}}'
docker ps --format '{{.Names}} {{.Label "com.docker.compose.project"}} {{.Ports}}'
docker volume ls --filter label=com.docker.compose.project=ceiba-staging
docker network ls --filter label=com.docker.compose.project=ceiba-staging
ss -lnt
```

Confirmar SHA aprobado, hostname, socket local, Compose v2 y aislamiento. No tocar
`/home/deploy/chat_bot_ceiba` ni `/home/deploy/ceiba-ci`. No mezclar perfiles Compose.
Si hay recursos A1 existentes, comprobar propiedad/continuidad antes de escribir.
Nunca ejecutar `scripts.quality.staging_ci` en host operativo: elimina volumen CI.
No ejecutar PRE, A2/A3, migraciones, restores ni iniciar aplicación en este runbook.

Crear rutas nuevas exclusivas; si existen, inspeccionar y usar procedimiento de
continuidad, sin sobrescribir archivos:

```bash
test ! -e /etc/ceiba-staging
sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" /etc/ceiba-staging
install -d -m 0700 /etc/ceiba-staging/tls
```

Desde otra terminal de la estación autorizada:

```bash
ACME_DIR="$HOME/.local/share/ceiba-staging/acme"
scp "$ACME_DIR/config/live/staging.ceibaclubhouse.com/fullchain.pem" \
  ceiba-staging:/etc/ceiba-staging/tls/fullchain.pem
scp "$ACME_DIR/config/live/staging.ceibaclubhouse.com/privkey.pem" \
  ceiba-staging:/etc/ceiba-staging/tls/privkey.pem
ssh ceiba-staging 'chmod 600 /etc/ceiba-staging/tls/privkey.pem'
```

**4. Variables en el host:** el bloque pide valores sin eco. No genera secretos ni
usa defaults. DATABASE_URL debe coincidir con db/5432, DB/user/password (URL encoded).
API_IMAGE/FRONTEND_IMAGE se toman del manifest aprobado, no se inventan ni construyen.

```bash
python3 - <<'PY'
import getpass, os, shlex
from pathlib import Path
from scripts.staging import clean_value
os.umask(0o077)
names = ('POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD', 'DATABASE_URL',
         'META_APP_SECRET', 'META_VERIFY_TOKEN', 'META_ACCESS_TOKEN', 'OPENROUTER_API_KEY',
         'META_PHONE_NUMBER_ID', 'META_GRAPH_API_VERSION', 'CATALOG_HOST_DIR',
         'EVIDENCE_HOST_DIR', 'API_IMAGE', 'FRONTEND_IMAGE')
values = {name: getpass.getpass(name + ': ') for name in names}
if not all(clean_value(value) for value in values.values()):
    raise SystemExit('Faltan valores externos reales; archivo no creado')
values.update(ENVIRONMENT='staging', STAGING_TLS_NAME='staging.ceibaclubhouse.com',
    STAGING_TLS_CERT='/etc/ceiba-staging/tls/fullchain.pem',
    STAGING_TLS_KEY='/etc/ceiba-staging/tls/privkey.pem')
with Path('/etc/ceiba-staging/staging.env').open('x') as handle:
    for name, value in values.items():
        handle.write(name + '=' + shlex.quote(value) + '\n')
PY
chmod 600 /etc/ceiba-staging/staging.env
test "$(stat -c %a /etc/ceiba-staging/staging.env)" = 600
set -a
. /etc/ceiba-staging/staging.env
set +a
test "$ENVIRONMENT" = staging
```

Provisionar directorios reales exclusivos elegidos en CATALOG_HOST_DIR y
EVIDENCE_HOST_DIR fuera del checkout y rutas ajenas. Para rutas nuevas ya revisadas:

```bash
test ! -e "$CATALOG_HOST_DIR"
test ! -e "$EVIDENCE_HOST_DIR"
sudo install -d -m 0750 -o 10001 -g 10001 -- "$CATALOG_HOST_DIR" "$EVIDENCE_HOST_DIR"
```

No copiar datos operativos. Registrar permisos/ACL sin PII.

**5. Render protegido e infraestructura:** `--quiet` evita imprimir secretos.

```bash
python3 -m scripts.staging config
docker compose --project-name ceiba-staging -f compose.protected.yml config --quiet
python3 -m scripts.staging up
python3 -m scripts.staging ps
python3 -m scripts.staging verify
python3 -m scripts.staging target
docker compose --project-name ceiba-staging -f compose.staging.yml exec -T db \
  sh -ec 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT system_identifier FROM pg_control_system()"'
docker volume inspect ceiba-staging_postgres_data --format '{{.Name}} {{.Mountpoint}}'
docker network inspect ceiba-staging_database --format '{{.Name}} {{.Internal}}'
ss -lnt '( sport = :8443 or sport = :5432 )'
curl --fail --silent --show-error --noproxy '*' \
  --resolve staging.ceibaclubhouse.com:8443:127.0.0.1 \
  https://staging.ceibaclubhouse.com:8443/infra-health
```

El curl usa confianza pública del sistema, sin `-k` ni `--cacert`. El verify interno
confía en el PEM suministrado y no reemplaza esta prueba. `target` aborta si existe
el inventario; custodiar el previo y comparar, no borrarlo para repetir. Solo A1
debe bindear 8443 loopback; investigar 5432 público sin detener servicios ajenos.

**6. Persistencia, DB A1 vacía y ventana autorizada:** solo recrear su contenedor.
Si hay datos/aplicación, acordar prueba de continuidad con responsable y parar aquí.

```bash
python3 - <<'PY'
from scripts import staging
staging.validate_inputs()
before = staging.verify()
if staging.sql("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')") != '0':
    raise SystemExit('DB no vacía: requiere procedimiento autorizado')
staging.run([*staging.COMPOSE, 'up', '-d', '--force-recreate', '--wait', 'db'])
if before != staging.verify():
    raise SystemExit('Identidad cambió: persistencia NO acreditada')
print('Persistencia de identidad del clúster A1 vacío: PASS')
PY
```

Registrar misma identidad y volumen antes/después. No acredita restore de datos ni
PRE-15. No crear tablas ni usar `down --volumes` en el destino.

**7. Canal administrativo, estación autorizada:**

```bash
ssh -N -L 127.0.0.1:8443:127.0.0.1:8443 ceiba-staging
```

En otra terminal repetir el curl de confianza pública del paso 5. Desde origen
fuera de VPN/IP autorizada, comprobar ausencia de exposición:

```bash
python3 - <<'PY'
import socket
for port in (5432, 8443):
    try:
        connection = socket.create_connection(('2.25.104.213', port), timeout=5)
    except OSError:
        print(f'{port}: no accesible desde este origen')
    else:
        connection.close()
        raise SystemExit(f'{port}: exposición detectada; A1 abierto')
PY
```

Conservar origen, hora y reglas VPN/IP/firewall/SSH aprobadas. Un timeout aislado no
demuestra política. Inventariar IPv6 y repetir contra direcciones públicas asignadas
si existen; una prueba IPv4 no acredita todos los accesos posibles.

**8. Target contractual:** provisionar/revisar backup_dir 0700 con custodia indicada
en deployment, destinatario GPG aprobado y tres hooks reales externos. Revisar sus
postcondiciones y SHA256 sin ejecutarlos. El smoke debe exigir las 18 evidencias
cuando se autorice A3; nunca un no-op. Si faltan, detenerse: A1 sigue abierto.

Crear `/etc/ceiba-staging/operations.json` modo 0600 con exactamente backup_dir,
backup_gpg_recipient, close_hook, smoke_hook, reopen_hook y sus valores reales.
No copiar placeholders de deployment. Una vez revisados:

```bash
python3 - <<'PY'
import json, os, stat
from pathlib import Path
from scripts import staging
os.umask(0o077)
staging.validate_inputs()
observed = staging.verify()
operations = json.loads(Path('/etc/ceiba-staging/operations.json').read_text())
keys = {'backup_dir', 'backup_gpg_recipient', 'close_hook', 'smoke_hook', 'reopen_hook'}
if set(operations) != keys:
    raise SystemExit('Se requieren exactamente cinco campos operativos')
target = {k: observed[k] for k in ('environment', 'hostname', 'checkout_path',
                                 'project', 'database_system_identifier')}
target.update(operations)
staging.validate_target(target)
checkout = Path.cwd().resolve()
for name in ('backup_dir', 'close_hook', 'smoke_hook', 'reopen_hook'):
    path = Path(target[name]).resolve(strict=True)
    if path == checkout or checkout in path.parents:
        raise SystemExit('Recurso operativo dentro del checkout')
    info = path.stat()
    if info.st_uid not in (0, os.getuid()):
        raise SystemExit('Propietario operativo no autorizado')
    if name == 'backup_dir':
        if not path.is_dir() or stat.S_IMODE(info.st_mode) != 0o700:
            raise SystemExit('backup_dir requiere directorio 0700')
    elif not path.is_file() or not os.access(path, os.X_OK) or info.st_mode & 0o022:
        raise SystemExit('Hook no ejecutable o modificable por grupo/otros')
staging.run(['gpg', '--batch', '--list-keys', target['backup_gpg_recipient']])
with Path('/etc/ceiba-staging/target.json').open('x') as handle:
    json.dump(target, handle, indent=2)
    handle.write('\n')
print('Target estructuralmente completo; revisar evidencia SCOPE')
PY
```

Revisar además ACL/directorios padres y custodia privada GPG. Listar la clave pública
no demuestra capacidad de restore; no ejecutarlo en A1. Guardar evidencia externa
0700 con UTC, SHA, versiones, operador y resultado/código de cada criterio, sin
secretos/PII. El target no autoriza despliegue. Cerrar A1 solo cuando los **nueve**
criterios SCOPE A1 tengan evidencia real y PASS; de otro modo **A1: ABIERTO**.
