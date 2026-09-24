#!/usr/bin/env bash
# Arm the next 1:00am Central production deploy for the current origin/master SHA.
# Run on the GPU pod. Deleting the arm file before 1:00am cancels the update.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_channel.sh"

WS="${WORKSPACE_ROOT:-$ROOT}"
ARM="${DEPLOY_ARM_FILE:-${PERSIST_ROOT:-/workspace/persistent}/deploy/armed}"
CHANNEL="$(pastor_git_channel "$WS")"
[[ "$CHANNEL" == "master" ]] || {
  echo "arm: refusing because git channel is $CHANNEL" >&2
  exit 1
}

if [[ "${ARM_SKIP_FETCH:-0}" != "1" && -d "$WS/.git" ]]; then
  git -C "$WS" fetch origin master
  SHA="$(git -C "$WS" rev-parse origin/master)"
else
  SHA="${ARM_SHA:-}"
fi
[[ -n "$SHA" ]] || { echo "arm: no master SHA" >&2; exit 1; }

MANIFEST="$WS/release/${SHA}.manifest"
if [[ ! -f "$MANIFEST" && "${ARM_SKIP_FETCH:-0}" != "1" && -d "$WS/.git" ]]; then
  if git -C "$WS" fetch origin "refs/pastor/manifests/${SHA}" >/dev/null 2>&1; then
    mkdir -p "$WS/release"
    git -C "$WS" show FETCH_HEAD:manifest > "$MANIFEST"
  fi
fi
[[ -f "$MANIFEST" ]] || { echo "arm: missing release manifest for $SHA" >&2; exit 1; }
grep -q '^HEALTH=ok$' "$MANIFEST" || { echo "arm: rehearsal health marker missing" >&2; exit 1; }
grep -q "^SHA=${SHA}$" "$MANIFEST" || { echo "arm: manifest SHA does not match $SHA" >&2; exit 1; }

mkdir -p "$(dirname "$ARM")"
printf '%s\n' "$SHA" > "$ARM"
chmod 600 "$ARM"
echo "Armed $SHA for the next 02:00 ${PROD_DEPLOY_TZ:-America/Chicago} window."
echo "Cancel with: rm -f $ARM"
