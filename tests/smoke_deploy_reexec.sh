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
git -C "$seed_repo" push --quiet

docker() {
  printf '%s|%s\n' "${DEPLOY_REEXEC:-unset}" "$*" >>"$SMOKE_DOCKER_LOG"
  if [[ "$*" == "compose config --services" ]]; then
    printf 'app\nworker\nadmin\n'
  fi
}

curl() {
  return 0
}

export -f docker curl
export SMOKE_DOCKER_LOG="$docker_log"

(
  cd "$deploy_repo"
  ./deploy.sh >/dev/null
)

expected_docker_calls=(
  "1|compose build app worker"
  "1|compose run --rm app alembic upgrade head"
  "1|compose run --rm app python scripts/load_knowledge.py"
  "1|compose up -d app worker"
  "1|compose config --services"
  "1|compose up -d --force-recreate admin"
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
