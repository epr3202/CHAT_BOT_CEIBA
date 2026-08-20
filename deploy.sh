#!/usr/bin/env bash
set -euo pipefail

running_script_sha="$(git hash-object "$0")"
git fetch origin main
git reset --hard origin/main
updated_script_sha="$(git hash-object "$0")"

if [[ "${DEPLOY_REEXEC:-0}" != "1" && "$running_script_sha" != "$updated_script_sha" ]]; then
  DEPLOY_REEXEC=1 exec "$0" "$@"
fi

docker compose build app worker
docker compose run --rm app alembic upgrade head
docker compose run --rm app python scripts/load_knowledge.py
docker compose up -d app worker

if docker compose config --services | grep -qx admin; then
  docker compose up -d --force-recreate admin
fi

deadline=$((SECONDS + 30))
until curl -sf http://localhost:8000/health >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Health check failed after 30 seconds" >&2
    exit 1
  fi
  sleep 2
done

deployed_sha="$(git rev-parse HEAD)"
deployed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "Deployed ${deployed_sha} at ${deployed_at}"
