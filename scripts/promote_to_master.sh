#!/usr/bin/env bash
# Fast-forward GitHub `master` to match `development`.
# Run from a clone with push access after development is tested on christian-ai-dev.
#
#   bash scripts/promote_to_master.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-origin}"

cd "$ROOT"
git fetch "$REMOTE" development master

dev_sha="$(git rev-parse "$REMOTE/development")"
master_sha="$(git rev-parse "$REMOTE/master")"
echo "development: $dev_sha"
echo "master:      $master_sha"

if [[ "$dev_sha" == "$master_sha" ]]; then
  echo "master already matches development — nothing to promote"
  exit 0
fi

echo "Promoting development → master"
git push "$REMOTE" "$REMOTE/development:master"
echo "Done. Production (christian-ai-prd) can now: bash deploy_update.sh"
