#!/usr/bin/env bash
# Push development to GitHub master from the dev pod after a rehearsal marker.
# Does not SSH to the production pod and does not arm the 1:00am deploy.
#
#   bash scripts/promote_to_master.sh --yes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-origin}"
YES=0
[[ "${1:-}" == "--yes" ]] && YES=1

if [[ "$YES" != "1" ]]; then
  echo "promote: refusing without --yes. The live site is unchanged." >&2
  exit 1
fi

if [[ -f "$ROOT/tokens.promote.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/tokens.promote.env"
  set +a
fi

cd "$ROOT"
git fetch "$REMOTE" development master

dev_sha="$(git rev-parse "$REMOTE/development")"
master_sha="$(git rev-parse "$REMOTE/master")"
echo "development: $dev_sha"
echo "master:      $master_sha"

MARKER="${PROMOTE_MARKER:-$ROOT/.dev_pipeline_success}"
[[ -f "$MARKER" ]] || { echo "promote: missing rehearsal marker $MARKER" >&2; exit 1; }
# shellcheck disable=SC1090
source "$MARKER"
[[ "${SHA:-}" == "$dev_sha" ]] || { echo "promote: marker SHA ${SHA:-empty} != $dev_sha" >&2; exit 1; }
[[ "${HEALTH:-}" == "ok" && "${ISOLATION:-}" == "ok" ]] || {
  echo "promote: rehearsal marker is not healthy" >&2
  exit 1
}

if [[ "${ALLOW_DESTRUCTIVE_MIGRATIONS:-0}" != "1" ]]; then
  while IFS= read -r migration; do
    [[ -n "$migration" && -f "$migration" ]] || continue
    if grep -q -E 'migrations\.(RemoveField|DeleteModel)' "$migration"; then
      echo "promote: $migration drops schema; ship that in a later night" >&2
      exit 1
    fi
  done < <(git diff --name-only "$master_sha" "$dev_sha" -- 'backend/app/**/migrations/*.py' || true)
fi

mkdir -p "$ROOT/release"
MANIFEST="$ROOT/release/${dev_sha}.manifest"
{
  echo "SHA=${dev_sha}"
  echo "HEALTH=${HEALTH}"
  echo "ISOLATION=${ISOLATION}"
  echo "GPU_SMOKE=${GPU_SMOKE:-0}"
  echo "MIGRATIONS=$(git diff --name-only "$master_sha" "$dev_sha" -- 'backend/app/**/migrations/*.py' | tr '\n' ' ')"
  if [[ -f "$ROOT/release/required-keys.txt" ]]; then
    while read -r key; do
      [[ -n "$key" && "$key" != \#* ]] && echo "REQUIRED ${key}"
    done < "$ROOT/release/required-keys.txt"
  fi
} > "$MANIFEST"
chmod 600 "$MANIFEST"

if [[ "$dev_sha" == "$master_sha" ]]; then
  echo "master already matches development — nothing to promote"
  echo "Live site unchanged. Arm production only when you want the 1:00am window:"
  echo "  bash scripts/arm_prod_deploy.sh"
  exit 0
fi

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  ASKPASS="$(mktemp)"
  printf '#!/bin/sh\necho "$GITHUB_TOKEN"\n' > "$ASKPASS"
  chmod 700 "$ASKPASS"
  export GIT_ASKPASS="$ASKPASS" GITHUB_TOKEN
fi

echo "Promoting development → master"
git push "$REMOTE" "$REMOTE/development:master"

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  rm -f "${ASKPASS:-}"
fi

# Publish the manifest without changing the master SHA.
if git check-ref-format "refs/pastor/manifests/${dev_sha}" 2>/dev/null; then
  blob="$(git hash-object -w "$MANIFEST")"
  tree="$(printf '100644 blob %s\tmanifest\n' "$blob" | git mktree)"
  commit="$(git commit-tree "$tree" -m "release ${dev_sha}")"
  git update-ref "refs/pastor/manifests/${dev_sha}" "$commit"
  git push "$REMOTE" "refs/pastor/manifests/${dev_sha}" || echo "promote: manifest ref was not pushed"
fi

echo "Done. The production pod is unchanged."
echo "On the GPU pod, when you want the 1:00am Central window:"
echo "  bash scripts/arm_prod_deploy.sh"
