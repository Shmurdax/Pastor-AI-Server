#!/usr/bin/env bash
# RunPod container start command — reconnects Django, vLLM, and the named
# Cloudflare tunnel after a stop/start or remigration:
#   bash /workspace/pastor-ai/onboot.sh
# A copy is also kept at /workspace/persistent/onboot.sh.
#
# Remigration wipes container packages (/usr/local/bin, apt pkgs, screen).
# Reinstall the tiny runtime deps, restore the tunnel token/binary from the
# network volume, then exec start.sh.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
START_SH="${START_SH:-$WS/start.sh}"

if ! command -v screen >/dev/null 2>&1 || ! command -v psql >/dev/null 2>&1; then
  apt-get update -qq || true
  apt-get install -y -qq screen postgresql postgresql-contrib || true
fi
pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 15 main start 2>/dev/null || service postgresql start 2>/dev/null || true

if [[ -f "$WS/persist_runtime.sh" ]]; then
  log()  { echo "[onboot] $*"; }
  warn() { echo "[onboot] $*" >&2; }
  APP_DIR="${APP_DIR:-$WS/backend/app}"
  # shellcheck disable=SC1091
  source "$WS/persist_runtime.sh"
  ensure_cloudflared_binary || true
  resolve_cloudflare_tunnel_token_file >/dev/null || true
fi

if [[ ! -f "$START_SH" ]]; then
  echo "Missing $START_SH — clone/install Pastor-AI before using onboot.sh" >&2
  exit 1
fi
exec bash "$START_SH"
