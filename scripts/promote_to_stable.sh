#!/usr/bin/env bash
# Fast-forward GitHub `stable` (and `master`) to match `latest`.
# Run from a clone with push access after latest has been tested on christian-ai-dev.
#
#   bash scripts/promote_to_stable.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-origin}"

cd "$ROOT"
git fetch "$REMOTE" latest stable master

latest_sha="$(git rev-parse "$REMOTE/latest")"
stable_sha="$(git rev-parse "$REMOTE/stable")"
echo "latest: $latest_sha"
echo "stable: $stable_sha"

if [[ "$latest_sha" == "$stable_sha" ]]; then
  echo "stable already matches latest — nothing to promote"
  exit 0
fi

echo "Promoting latest → stable (and master, for older install URLs)"
git push "$REMOTE" "$REMOTE/latest:stable"
git push "$REMOTE" "$REMOTE/latest:master"
echo "Done. Production (christian-ai-prd) can now: bash deploy_update.sh"
