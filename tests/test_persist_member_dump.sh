#!/usr/bin/env bash
# Persist dumps must keep member accounts even when the sermon catalog is empty.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log()  { :; }
warn() { :; }

export PERSIST_ROOT="$TMP/persistent"
export PERSIST_PG_DUMP="$TMP/persistent/postgres/ai_db.dump"
export PERSIST_RESTORE_MARKER="$TMP/restored.marker"

# shellcheck disable=SC1091
source "$ROOT/persist_runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$(dirname "$PERSIST_PG_DUMP")"
printf 'existing-catalog\n' > "$PERSIST_PG_DUMP"

_should_skip_empty_live_dump 0 \
  || fail "should skip dump when catalog dump exists, live docs=0, and restore has not completed"

_should_skip_empty_live_dump 12 \
  && fail "should dump when live catalog has documents"

touch "$PERSIST_RESTORE_MARKER"
_should_skip_empty_live_dump 0 \
  && fail "should dump after restore so new member accounts persist with an empty sermon catalog"

rm -f "$PERSIST_PG_DUMP"
_should_skip_empty_live_dump 0 \
  && fail "should dump when no persist dump exists yet"

echo "OK persist member dump skip rules"
