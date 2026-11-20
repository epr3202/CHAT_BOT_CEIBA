#!/usr/bin/env bash
set -euo pipefail

# Keep these functions in the invoking shell while checkout replaces versioned files.
release() {
  if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Usage: ./deploy.sh <full-tested-commit-sha>' >&2
    return 2
  fi
  umask 077
  backup_dir=$(realpath -m -- "${DEPLOY_BACKUP_DIR:-$HOME/backups}")
  mkdir -p -- "$backup_dir"
  exec 9>"$(git rev-parse --git-path ceiba-deploy.lock)"
  flock -n 9 || { echo 'Another deployment is running' >&2; return 1; }
  git diff --quiet HEAD || { echo 'Tracked deployment files have local changes' >&2; return 1; }
  git fetch origin main
  target=$(git rev-parse --verify "$1^{commit}")
  previous=$(git rev-parse HEAD)
  if [[ ${DEPLOY_REEXEC:-0} == 1 && $previous == "$target" ]]; then
    # The legacy launcher checked out its target before handing over.
    previous=$(git rev-parse 'HEAD@{1}')
  fi
  running_services=()
  for service in app worker admin; do
    if [[ -n $(docker compose ps --status running -q "$service") ]]; then
      running_services+=("$service")
    fi
  done
  restore_required=0
  released=0
  backup_file=
  trap recover EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  docker compose stop app worker admin
  git checkout --quiet --detach "$target"
  docker compose build app worker
  backup_file=$(mktemp "$backup_dir/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)-${previous:0:12}-XXXXXXXX.dump")
  docker compose exec -T db pg_dump -U ceiba -d ceiba -Fc > "$backup_file"
  docker compose exec -T db pg_restore --list < "$backup_file" >/dev/null
  restore_required=1
  docker compose run --rm --no-deps app alembic upgrade head
  docker compose run --rm --no-deps app python scripts/load_knowledge.py
  docker compose run --rm --no-deps app python scripts/load_plans.py
  # Validate startup and schema before a public listener or delivery worker can write.
  docker compose run --rm --no-deps app python -c '
import asyncio
from app.main import app, ready
async def check():
    async with app.router.lifespan_context(app):
        response = await ready()
        assert response == {"status": "ready"}, response
asyncio.run(check())'
  released=1
  docker compose up -d --no-deps app worker
  docker compose up -d --no-deps --force-recreate admin
  check_services
  trap - EXIT
  # Retain the seven newest completed deployments, including pre-existing archives.
  mapfile -t archives < <(find "$backup_dir" -maxdepth 1 -type f -name 'pre-deploy-*.dump' -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
  if (( ${#archives[@]} > 7 )); then rm -- "${archives[@]:7}"; fi
  echo "Deployed $target. Backup $backup_file"
}

check_services() {
  local deadline=$((SECONDS + 60)) worker
  until docker compose exec -T app python -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3).close()' >/dev/null 2>&1 &&
    docker compose exec -T admin node -e \
    'fetch("http://127.0.0.1:5173", {signal:AbortSignal.timeout(3000)}).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))' >/dev/null 2>&1 &&
    worker=$(docker compose ps -q --status running worker) && [[ -n $worker ]]; do
    (( SECONDS < deadline )) || { echo 'App, worker or panel not ready' >&2; return 1; }
    sleep 2
  done
}

recover() {
  local status=$? restore_db failed_db
  trap - EXIT INT TERM
  (( status != 0 )) || return 0
  if (( released )); then
    echo "Release activated before failure. Preserve new writes; inspect $target and $backup_file." >&2
    return "$status"
  fi
  if (( restore_required )); then
    # Restore into a fresh DB. Objects introduced by a partially committed migration/seed
    # must not survive. Retain the failed DB for inspection. Rename atomically while quiescent.
    restore_db="ceiba_restore_$(date -u +%s)_$$"
    failed_db="ceiba_failed_$(date -u +%s)_$$"
    docker compose exec -T db createdb -U ceiba -T template0 "$restore_db"
    docker compose exec -T db pg_restore --exit-on-error --single-transaction -U ceiba -d "$restore_db" < "$backup_file"
    docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -U ceiba -d postgres \
      -c "BEGIN; ALTER DATABASE ceiba RENAME TO $failed_db; ALTER DATABASE $restore_db RENAME TO ceiba; COMMIT;"
  fi
  git checkout --quiet --detach "$previous"
  if (( ${#running_services[@]} )); then
    # start reuses the stopped containers and their exact image IDs.
    docker compose start "${running_services[@]}"
    if (( ${#running_services[@]} == 3 )); then check_services; fi
  fi
  echo "Recovered $previous after failure at $target. Backup $backup_file" >&2
  return "$status"
}

release "$@"
