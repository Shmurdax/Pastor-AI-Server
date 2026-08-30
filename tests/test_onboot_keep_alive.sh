#!/usr/bin/env bash
# onboot.sh must run start.sh then stay alive (RunPod restarts if PID 1 exits).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'exec bash "$START_SH"' "$ROOT/onboot.sh" \
  && fail "onboot.sh must not exec start.sh (that exits the container)"
grep -q 'sleep infinity' "$ROOT/onboot.sh" \
  || fail "onboot.sh must sleep infinity after start.sh"
grep -q 'PASTOR_KEEP_ALIVE' "$ROOT/start.sh" \
  || fail "start.sh must honor PASTOR_KEEP_ALIVE"

mkdir -p "$TMP/bin" "$TMP/pastor-ai" "$TMP/persistent"
printf '%s\n' '#!/bin/bash' 'echo started > "'"$TMP"'/started"' 'exit 0' > "$TMP/start.sh"
chmod +x "$TMP/start.sh"
for cmd in screen psql ffmpeg soffice pg_ctlcluster service; do
  printf '%s\n' '#!/bin/bash' 'exit 0' > "$TMP/bin/$cmd"
  chmod +x "$TMP/bin/$cmd"
done

export PATH="$TMP/bin:$PATH"
export WORKSPACE_ROOT="$TMP/pastor-ai"
export PERSIST_ROOT="$TMP/persistent"
export START_SH="$TMP/start.sh"
# Do not inherit a keep-alive from the test runner.
unset PASTOR_KEEP_ALIVE || true

set +e
timeout 2 bash "$ROOT/onboot.sh" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 124 ]] || fail "onboot should block in sleep infinity (timeout 124), got $rc"
[[ -f "$TMP/started" ]] || fail "start.sh did not run"

echo "OK onboot keep-alive"
