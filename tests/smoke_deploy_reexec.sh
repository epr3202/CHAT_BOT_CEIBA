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
  printf '%s\n' "${DEPLOY_REEXEC:-unset}" >>"$SMOKE_DOCKER_LOG"
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

docker_call_count="$(wc -l <"$docker_log")"
if [[ "$docker_call_count" -ne 4 ]]; then
  echo "Expected 4 docker calls, got $docker_call_count" >&2
  exit 1
fi

if grep --invert-match --line-regexp --quiet '1' "$docker_log"; then
  echo "Deploy steps ran without DEPLOY_REEXEC=1" >&2
  exit 1
fi
