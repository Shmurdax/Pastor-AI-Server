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

# Fetch origin/$CHANNEL and hard-reset before start.sh. Recreate/remigration
# used to boot whatever SHA was left on the volume, which is how production
# silently ran an old master (and leftover file overlays).
_ONBOOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$WS/scripts/git_channel.sh" 2>/dev/null \
  || source "$_ONBOOT_DIR/scripts/git_channel.sh" 2>/dev/null \
  || true
# shellcheck source=/dev/null
source "$WS/scripts/git_safe_directory.sh" 2>/dev/null \
  || source "$_ONBOOT_DIR/scripts/git_safe_directory.sh" 2>/dev/null \
  || true
# shellcheck source=/dev/null
source "$WS/scripts/sync_git_channel.sh" 2>/dev/null \
  || source "$_ONBOOT_DIR/scripts/sync_git_channel.sh" 2>/dev/null \
  || true

GIT_CHANGED=0
if declare -F pastor_sync_git_channel >/dev/null 2>&1; then
  CHANNEL="$(pastor_resolve_git_channel "$WS")"
  pastor_write_git_channel "$WS" "$CHANNEL" || true
  if pastor_sync_git_channel "$WS" "$CHANNEL"; then
    GIT_CHANGED="${PASTOR_GIT_CHANGED:-0}"
  else
    warn "git sync failed — starting the existing checkout (see $WS/DEPLOYED_SYNC_ERROR)"
  fi
else
  warn "sync_git_channel.sh missing — boot will not fetch GitHub"
fi

# start.sh launches services in screen and returns. Keep this process so the
# container does not exit (RunPod treats that as a crash and restarts).
# Do not export PASTOR_KEEP_ALIVE before deploy_update: that script calls
# start.sh, which would exec sleep infinity and skip its health checks.
STARTED=0
set +e
if [[ "$GIT_CHANGED" == "1" && -x "$WS/deploy_update.sh" ]]; then
  log "Checkout moved or discarded overlays — running deploy_update.sh"
  PASTOR_SKIP_GIT_SYNC=1 PASTOR_KEEP_ALIVE=0 bash "$WS/deploy_update.sh"
  if [[ $? -eq 0 ]]; then
    STARTED=1
  else
    warn "deploy_update.sh failed after git sync — falling back to start.sh"
  fi
fi
if [[ "$STARTED" -eq 0 ]]; then
  bash "$START_SH"
  start_rc=$?
else
  start_rc=0
fi
set -e
if [[ "$start_rc" -ne 0 ]]; then
  warn "start.sh exited $start_rc — keeping container alive"
else
  log "start.sh finished; keeping container alive"
fi
exec sleep infinity
