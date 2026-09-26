#!/usr/bin/env bash
set -euo pipefail
target="${1:-origin/main}"
running_script_sha="$(git hash-object "$0")"
git fetch origin main
git checkout --quiet --detach "$target"
updated_script_sha="$(git hash-object "$0")"
if [[ "${DEPLOY_REEXEC:-0}" != "1" && "$running_script_sha" != "$updated_script_sha" ]]; then
  DEPLOY_REEXEC=1 exec "$0" "$@"
fi
deployed_sha="$(git rev-parse HEAD)"
backup_dir="${DEPLOY_BACKUP_DIR:-$HOME/backups}"
mkdir -p "$backup_dir"
docker compose build app worker
docker compose stop app worker
backup_file="$backup_dir/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)-${deployed_sha:0:7}.dump"
docker compose exec -T db pg_dump -U ceiba -d ceiba -Fc > "$backup_file"
test -s "$backup_file"
docker compose run --rm --no-deps app alembic upgrade head
docker compose run --rm --no-deps app python scripts/load_knowledge.py
docker compose up -d --no-deps app worker
if docker compose config --services | grep -qx admin; then
  docker compose up -d --no-deps --force-recreate admin
fi
deadline=$((SECONDS + 60))
until curl -sf http://localhost:8000/health >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Health check failed after 60 seconds; backup at $backup_file" >&2
    exit 1
  fi
  sleep 2
done
ls -t "$backup_dir"/pre-deploy-*.dump 2>/dev/null | tail -n +8 | xargs -r rm -f
echo "Deployed ${deployed_sha} at $(date -u +"%Y-%m-%dT%H:%M:%SZ") (backup: $backup_file)"
