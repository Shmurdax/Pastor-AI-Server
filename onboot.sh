#!/usr/bin/env bash
# RunPod container start command — reconnects Django, Qdrant, optional local
# vLLM (skipped on a CPU web pod that calls RunPod Serverless), Whisper
# ingest, and the named Cloudflare tunnel after a stop/start or remigration:
#   bash /workspace/pastor-ai/onboot.sh
# Fallback if pastor-ai/onboot.sh is missing:
#   bash /workspace/persistent/onboot.sh
#
# Remigration wipes container packages (/usr/local/bin, apt pkgs, screen).
# Restore boot scripts + secrets from the network volume, reinstall runtime
# deps, restore the tunnel token/binary, then run start.sh and stay alive.
# Do not `exec start.sh`: that script returns after launching screens, and
# exiting the container start command makes RunPod restart-loop.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
PERSIST_ROOT="${PERSIST_ROOT:-/workspace/persistent}"
START_SH="${START_SH:-$WS/start.sh}"
APP_DIR="${APP_DIR:-$WS/backend/app}"

log()  { echo "[onboot] $*"; }
warn() { echo "[onboot] $*" >&2; }

_source_persist_runtime() {
  local candidate
  for candidate in \
    "$WS/persist_runtime.sh" \
    "$PERSIST_ROOT/boot/persist_runtime.sh" \
    "$PERSIST_ROOT/persist_runtime.sh"
  do
    if [[ -f "$candidate" ]]; then
      # shellcheck disable=SC1090
      source "$candidate"
      return 0
    fi
  done
  return 1
}

if _source_persist_runtime; then
  restore_workspace_from_persist || true
  # Re-source from pastor-ai after restore so start.sh helpers match the live tree.
  if [[ -f "$WS/persist_runtime.sh" ]]; then
    # shellcheck disable=SC1091
    source "$WS/persist_runtime.sh"
  fi
fi

if ! command -v screen >/dev/null 2>&1 \
   || ! command -v psql >/dev/null 2>&1 \
   || ! command -v ffmpeg >/dev/null 2>&1 \
   || ! command -v soffice >/dev/null 2>&1; then
  apt-get update -qq || true
  apt-get install -y -qq \
    screen postgresql postgresql-contrib ffmpeg libreoffice-writer \
    python3 python3-venv python3-pip curl ca-certificates || true
fi
pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 15 main start 2>/dev/null || service postgresql start 2>/dev/null || true

if declare -F ensure_cloudflared_binary >/dev/null 2>&1; then
  ensure_cloudflared_binary || true
  resolve_cloudflare_tunnel_token_file >/dev/null || true
  ensure_qdrant_binary || true
  ensure_persistent_boot_bundle || true
fi

if [[ ! -f "$START_SH" ]]; then
  echo "Missing $START_SH — clone/install Pastor-AI or restore from $PERSIST_ROOT/boot" >&2
  exit 1
fi

# start.sh launches services in screen and returns. Keep this process so the
# container does not exit (RunPod treats that as a crash and restarts).
export PASTOR_KEEP_ALIVE="${PASTOR_KEEP_ALIVE:-1}"
set +e
bash "$START_SH"
start_rc=$?
set -e
if [[ "$start_rc" -ne 0 ]]; then
  warn "start.sh exited $start_rc — keeping container alive"
else
  log "start.sh finished; keeping container alive"
fi
exec sleep infinity
