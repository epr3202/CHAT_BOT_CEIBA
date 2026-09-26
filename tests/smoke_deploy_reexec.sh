#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_root="$(mktemp -d)"
trap 'rm -rf "$temp_root"' EXIT

remote_repo="$temp_root/remote.git"
seed_repo="$temp_root/seed"
deploy_repo="$temp_root/deploy"
docker_log="$temp_root/docker.log"

git init --bare --quiet "$remote_repo"
git init --quiet --initial-branch=main "$seed_repo"
git -C "$seed_repo" config user.name "Deploy Smoke Test"
git -C "$seed_repo" config user.email "deploy-smoke@example.invalid"
cp "$repo_root/deploy.sh" "$seed_repo/deploy.sh"
git -C "$seed_repo" add deploy.sh
git -C "$seed_repo" commit --quiet -m "old deploy script"
git -C "$seed_repo" remote add origin "$remote_repo"
git -C "$seed_repo" push --quiet --set-upstream origin main

git clone --quiet --branch main "$remote_repo" "$deploy_repo"

printf '\n# simulated updated deploy script\n' >>"$seed_repo/deploy.sh"
git -C "$seed_repo" add deploy.sh
git -C "$seed_repo" commit --quiet -m "updated deploy script"
target_sha="$(git -C "$seed_repo" rev-parse HEAD)"

# The tested SHA must survive re-exec even when main has advanced past it.
printf 'future main content\n' >"$seed_repo/future.txt"
git -C "$seed_repo" add future.txt
git -C "$seed_repo" commit --quiet -m "advance main beyond tested SHA"
git -C "$seed_repo" push --quiet

docker() {
  printf '%s|%s\n' "${DEPLOY_REEXEC:-unset}" "$*" >>"$SMOKE_DOCKER_LOG"
  if [[ "$*" == "compose config --services" ]]; then
    printf 'app\nworker\nadmin\n'
  elif [[ "$*" == "compose exec -T db pg_dump -U ceiba -d ceiba -Fc" ]]; then
    printf 'x'
  fi
}

curl() {
  return 0
}

export -f docker curl
export SMOKE_DOCKER_LOG="$docker_log"
export DEPLOY_BACKUP_DIR="$temp_root/backups"

(
  cd "$deploy_repo"
  ./deploy.sh "$target_sha" >/dev/null
)

expected_docker_calls=(
  "1|compose build app worker"
  "1|compose stop app worker"
  "1|compose exec -T db pg_dump -U ceiba -d ceiba -Fc"
  "1|compose run --rm --no-deps app alembic upgrade head"
  "1|compose run --rm --no-deps app python scripts/load_knowledge.py"
  "1|compose up -d --no-deps app worker"
  "1|compose config --services"
  "1|compose up -d --no-deps --force-recreate admin"
)
mapfile -t actual_docker_calls <"$docker_log"

if [[ "${#actual_docker_calls[@]}" -ne "${#expected_docker_calls[@]}" ]]; then
  echo "Unexpected Docker call count" >&2
  printf 'Actual: %s\n' "${actual_docker_calls[*]}" >&2
  exit 1
fi

for index in "${!expected_docker_calls[@]}"; do
  if [[ "${actual_docker_calls[$index]}" != "${expected_docker_calls[$index]}" ]]; then
    echo "Unexpected Docker call at index $index" >&2
    echo "Expected: ${expected_docker_calls[$index]}" >&2
    echo "Actual: ${actual_docker_calls[$index]}" >&2
    exit 1
  fi
done

if [[ "$(git -C "$deploy_repo" rev-parse HEAD)" != "$target_sha" ]]; then
  echo "Deploy did not preserve the tested SHA through re-exec" >&2
  exit 1
fi

if git -C "$deploy_repo" symbolic-ref --quiet HEAD >/dev/null; then
  echo "Deploy did not leave a detached HEAD" >&2
  exit 1
fi

backup_files=("$DEPLOY_BACKUP_DIR"/pre-deploy-*-"${target_sha:0:7}".dump)
if [[ "${#backup_files[@]}" -ne 1 || ! -s "${backup_files[0]}" ]]; then
  echo "Expected one nonempty backup for the tested SHA" >&2
  exit 1
fi

echo "PASS: re-exec preserved the tested SHA with detached HEAD, a nonempty backup, and 8 expected Docker calls."
