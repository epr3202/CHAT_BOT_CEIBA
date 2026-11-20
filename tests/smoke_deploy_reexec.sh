#!/usr/bin/env bash
# Run the deployment entry point against a private Compose network and disposable volume.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
sandbox=$(mktemp -d)
export COMPOSE_PROJECT_NAME="ceiba-recovery-$(date +%s)-$$"
export DEPLOY_BACKUP_DIR="$sandbox/backups"
export COMPOSE_FILE="$sandbox/compose.yml"
repo="$sandbox/source"
mkdir "$repo"
cleanup() {
  (cd "$repo" && docker compose down --volumes --remove-orphans) >/dev/null 2>&1 || true
  rm -rf -- "$sandbox"
}
trap cleanup EXIT
cd "$root"
git ls-files --cached --others --exclude-standard -z -- \
  'app/*' 'alembic/*' 'scripts/*' 'docs/conversation/*' 'data/*' 'frontend/*' \
  alembic.ini deploy.sh Dockerfile pyproject.toml requirements.lock .dockerignore |
  tar --null -T - -cf - | tar -xf - -C "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.name "Prueba local"
git -C "$repo" config user.email "test@example.invalid"
cat > "$COMPOSE_FILE" <<YAML
name: $COMPOSE_PROJECT_NAME
x-env: &env
  DATABASE_URL: postgresql+asyncpg://ceiba:synthetic@db:5432/ceiba
  ENVIRONMENT: testing
  META_VERIFY_TOKEN: synthetic
  META_ACCESS_TOKEN: synthetic
  META_APP_SECRET: synthetic
  OPENROUTER_API_KEY: synthetic
services:
  db:
    image: postgres:16
    environment: {POSTGRES_USER: ceiba, POSTGRES_PASSWORD: synthetic, POSTGRES_DB: ceiba}
    volumes: [dbdata:/var/lib/postgresql/data]
  app:
    build: "$repo"
    environment: *env
  worker:
    build: "$repo"
    environment: *env
    command: [python, -m, app.channel.worker]
  admin:
    image: node:22-alpine
    working_dir: /srv/frontend
    volumes: ["$repo/frontend:/srv/frontend:ro"]
    command: [node, server.mjs]
    environment: {FRONTEND_PORT: '5173', API_BASE_URL: 'http://app:8000'}
volumes: {dbdata: {}}
networks: {default: {internal: true}}
YAML
cd "$repo"
git add .
git commit -qm 'healthy initial release'
original=$(git rev-parse HEAD)
git commit -qm 'compatible rollback target' --allow-empty
compatible=$(git rev-parse HEAD)
cat > scripts/load_plans.py <<'PY'
import asyncio
import asyncpg

async def fail_after_commit():
    db = await asyncpg.connect("postgresql://ceiba:synthetic@db/ceiba")
    await db.execute("CREATE TABLE interrupted_seed (value int)")
    await db.execute("UPDATE plan SET price_cop=1")
    await db.close()
    raise SystemExit(63)

asyncio.run(fail_after_commit())
PY
git commit -qam 'deliberately interrupted seed'
broken=$(git rev-parse HEAD)
git clone -q --bare "$repo" "$sandbox/origin.git"
git remote add origin "$sandbox/origin.git"
git checkout -q --detach "$original"
docker compose up -d db
for attempt in $(seq 1 45); do
  if docker compose exec -T db pg_isready -U ceiba >/dev/null; then break; fi
  sleep 1
done
docker compose build app worker
docker compose run --rm --no-deps app alembic upgrade head
docker compose run --rm --no-deps app python scripts/load_plans.py
docker compose up -d --no-deps app worker admin
sql() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U ceiba -d ceiba -Atqc "$1"; }
price=$(sql "SELECT price_cop FROM plan WHERE code='ROMANCE_COPAS'")
rev=$(sql 'SELECT version_num FROM alembic_version')
if ./deploy.sh "$broken"; then echo 'The faulty release succeeded' >&2; exit 1; fi
[[ "$(git rev-parse HEAD)" == "$original" ]]
[[ "$(sql "SELECT to_regclass('interrupted_seed') IS NULL")" == t ]]
[[ "$(sql "SELECT price_cop FROM plan WHERE code='ROMANCE_COPAS'")" == "$price" ]]
[[ "$(sql 'SELECT version_num FROM alembic_version')" == "$rev" ]]
for service in app worker admin; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$(docker compose ps -q "$service")")" == true ]]
done
docker compose exec -T app python -c "import urllib.request; print('recovered /ready', urllib.request.urlopen('http://localhost:8000/ready').status)"
docker compose exec -T admin node -e "fetch('http://127.0.0.1:5173').then(r=>{console.log('recovered panel',r.status);process.exit(r.ok?0:1)})"
archive=$(find "$DEPLOY_BACKUP_DIR" -type f -name '*.dump' -print -quit)
[[ -s "$archive" && "$(stat -c %a "$archive")" == 600 ]]
./deploy.sh "$compatible"
[[ "$(git rev-parse HEAD)" == "$compatible" ]]
echo "PASS previous=$original failed=$broken explicit_target=$compatible schema=$rev price=$price backup_mode=600"

# Activation after app/worker startup must NEVER restore a snapshot that predates
# writes performed by the new release. Inject one transient admin start failure.
sql 'CREATE TABLE activation_write_marker (id integer PRIMARY KEY)' >/dev/null
git commit -qm 'synthetic activation target' --allow-empty
activated=$(git rev-parse HEAD)
real_docker=$(command -v docker)
mkdir -p "$sandbox/test-bin"
cat > "$sandbox/test-bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "compose up -d --no-deps --force-recreate admin" &&
      -f "${ACTIVATION_FAIL_ONCE:-/dev/null}" ]]; then
  rm -f -- "$ACTIVATION_FAIL_ONCE"
  "$REAL_DOCKER" compose exec -T db psql -X -v ON_ERROR_STOP=1 -U ceiba -d ceiba \
    -c 'INSERT INTO activation_write_marker (id) VALUES (1)' >/dev/null
  echo 'Synthetic admin activation failure after a committed write' >&2
  exit 72
fi
exec "$REAL_DOCKER" "$@"
SH
chmod 0700 "$sandbox/test-bin/docker"
touch "$sandbox/activation-fail-once"
if REAL_DOCKER="$real_docker" ACTIVATION_FAIL_ONCE="$sandbox/activation-fail-once" \
   PATH="$sandbox/test-bin:$PATH" ./deploy.sh "$activated"; then
  echo 'The interrupted activation unexpectedly reported success' >&2
  exit 1
fi
[[ ! -e "$sandbox/activation-fail-once" ]]
[[ "$(git rev-parse HEAD)" == "$activated" ]]
[[ "$(sql 'SELECT COUNT(*) FROM activation_write_marker')" == 1 ]]
[[ "$(sql 'SELECT version_num FROM alembic_version')" == "$rev" ]]
[[ "$(sql "SELECT price_cop FROM plan WHERE code='ROMANCE_COPAS'")" == "$price" ]]
for service in app worker admin; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$(docker compose ps -q "$service")")" == true ]]
done
docker compose exec -T app python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/ready').status == 200"
docker compose exec -T admin node -e "fetch('http://127.0.0.1:5173').then(r=>process.exit(r.ok?0:1))"
echo "PASS activation_failure_retains_committed_write=1 checkout=$activated schema=$rev services=running"
