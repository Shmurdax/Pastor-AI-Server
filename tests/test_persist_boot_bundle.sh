#!/usr/bin/env bash
# Remigration: boot scripts + secrets restore from /workspace/persistent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log()  { :; }
warn() { :; }

export PERSIST_ROOT="$TMP/persistent"
export WS="$TMP/pastor-ai"
mkdir -p "$WS" "$PERSIST_ROOT"

# shellcheck disable=SC1091
source "$ROOT/persist_runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1) Live tree is mirrored onto the persistent boot bundle.
printf 'start-live\n' > "$WS/start.sh"
printf 'onboot-live\n' > "$WS/onboot.sh"
printf 'persist-live\n' > "$WS/persist_runtime.sh"
printf 'gpu-live\n' > "$WS/gpu_runtime.sh"
printf 'vllm-live\n' > "$WS/vllm_runtime.sh"
printf 'secret-config\n' > "$WS/config.env"
printf 'secret-tokens\n' > "$WS/tokens.env"
mkdir -p "$WS/scripts" "$WS/secrets"
printf 'load-env-live\n' > "$WS/scripts/load_env.sh"
printf '{}\n' > "$WS/secrets/gmail-sender.json"
chmod +x "$WS/start.sh" "$WS/onboot.sh"
ensure_persistent_boot_bundle
[[ -s "$PERSIST_BOOT/start.sh" ]] || fail "boot bundle missing start.sh"
[[ "$(cat "$PERSIST_ROOT/onboot.sh")" == "onboot-live" ]] || fail "persistent onboot.sh not mirrored"
[[ "$(cat "$PERSIST_CONFIG")" == "secret-config" ]] || fail "config.env not mirrored"
[[ "$(cat "$PERSIST_GMAIL_JSON")" == "{}" ]] || fail "gmail-sender.json not mirrored"
[[ "$(cat "$PERSIST_BOOT/scripts/load_env.sh")" == "load-env-live" ]] || fail "load_env.sh not mirrored"
[[ "$(stat -c %a "$PERSIST_CONFIG" 2>/dev/null || stat -f %OLp "$PERSIST_CONFIG")" == "600" ]] \
  || fail "persist config.env should be mode 600"

# 2) Remigration: pastor-ai scripts/secrets wiped; persist restores them.
rm -rf "$WS"
mkdir -p "$WS"
restore_workspace_from_persist
[[ "$(cat "$WS/start.sh")" == "start-live" ]] || fail "start.sh not restored"
[[ "$(cat "$WS/onboot.sh")" == "onboot-live" ]] || fail "onboot.sh not restored"
[[ "$(cat "$WS/gpu_runtime.sh")" == "gpu-live" ]] || fail "gpu_runtime.sh not restored"
[[ "$(cat "$WS/vllm_runtime.sh")" == "vllm-live" ]] || fail "vllm_runtime.sh not restored"
[[ "$(cat "$WS/config.env")" == "secret-config" ]] || fail "config.env not restored"
[[ "$(cat "$WS/tokens.env")" == "secret-tokens" ]] || fail "tokens.env not restored"
[[ "$(cat "$WS/secrets/gmail-sender.json")" == "{}" ]] || fail "gmail-sender.json not restored"
[[ "$(cat "$WS/scripts/load_env.sh")" == "load-env-live" ]] || fail "load_env.sh not restored"

# 3) Restore does not overwrite a live tree that already has files.
printf 'start-newer\n' > "$WS/start.sh"
restore_workspace_from_persist
[[ "$(cat "$WS/start.sh")" == "start-newer" ]] || fail "restore overwrote live start.sh"

# 4) Seed restore is a no-op when the live catalog already has rows.
_pg_ready() { return 0; }
_pg_doc_count() { echo 930; }
_reset_postgres_id_sequences() { :; }
mkdir -p "$(dirname "$SEED_INGEST_DUMP")"
printf 'PGDMP-fake\n' > "$TMP/seed.dump"
SEED_INGEST_DUMP="$TMP/seed.dump"
restore_seed_ingested_catalog || fail "seed restore should succeed as no-op"
[[ -s "$PERSIST_PG_ROOT/ingested_catalog.dump" ]] || fail "seed dump should be copied to persist"

# 5) Wiping documents must not reload seed jobs (that rewinds ingestionjob_id_seq).
_pg_doc_count() { echo 0; }
_pg_table_count() { echo 12; }
pg_restore() { echo "pg_restore-should-not-run" >&2; return 1; }
restore_seed_ingested_catalog || fail "seed restore should skip when ingestion jobs exist"

echo "OK persist boot bundle remigration"
