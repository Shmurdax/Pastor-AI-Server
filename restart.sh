#!/usr/bin/env bash
# Restart Pastor-AI services after a pod reboot (fast — no reinstall).
# Usage: bash restart.sh
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=paths.sh
source "$ROOT/paths.sh"

if [[ -f "$ROOT/config.env" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/config.env"
fi

CHRISTIANAI_HF_REPO="${CHRISTIANAI_HF_REPO:-apophaticai/qwen2.5-14b-christianai-v1}"
TUNNEL="${TUNNEL:-cloudflared}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log() { echo -e "${GREEN}[✔]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die() { echo -e "${RED}[✘]${NC} $*" >&2; exit 1; }

stop_screen() {
  local name="$1"
  screen -S "$name" -X quit 2>/dev/null || true
}

start_qdrant() {
  if curl -sf http://localhost:6333 >/dev/null 2>&1; then
    log "Qdrant already running"
    return
  fi
  if [[ ! -x "$QDRANT_DIR/qdrant" ]]; then
    die "Qdrant binary missing. Run: bash setup.sh"
  fi
  stop_screen qdrant
  screen -dmS qdrant bash -c "cd '$QDRANT_DIR' && ./qdrant >> '$LOG_DIR/qdrant.log' 2>&1"
  sleep 4
  curl -sf http://localhost:6333 >/dev/null || die "Qdrant failed to start. See $LOG_DIR/qdrant.log"
  log "Qdrant running on :6333"
}

start_django() {
  [[ -f "$APP_DIR/manage.py" ]] || die "App not found at $APP_DIR — run setup.sh first"
  stop_screen django
  screen -dmS django bash -c "
    cd '$APP_DIR' &&
    source '$VENV_DIR/bin/activate' &&
    export CHRISTIANAI_LORA_DIR='$LORA_DIR' HF_HOME='$HF_HOME' &&
    python manage.py runserver 0.0.0.0:8000 >> '$LOG_DIR/django.log' 2>&1
  "
  sleep 3
  log "Django running on :8000"
}

start_cloudflared() {
  if ! command -v cloudflared >/dev/null 2>&1; then
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
  fi
  stop_screen cloudflared
  : > "$LOG_DIR/cloudflared.log"
  screen -dmS cloudflared bash -c \
    "cloudflared tunnel --url http://127.0.0.1:8000 >> '$LOG_DIR/cloudflared.log' 2>&1"
  sleep 8
  local url
  url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" | head -1 || true)"
  if [[ -n "$url" ]]; then
    log "Public URL (Cloudflare): $url"
    echo "$url" > "$WORKSPACE_ROOT/public_url.txt"
  else
    warn "Cloudflare URL not ready yet — check: tail -f $LOG_DIR/cloudflared.log"
  fi
}

start_ngrok() {
  [[ -n "${NGROK_AUTH_TOKEN:-}" ]] || die "NGROK_AUTH_TOKEN missing in config.env"
  command -v ngrok >/dev/null || die "ngrok not installed — run setup.sh"
  ngrok config add-authtoken "$NGROK_AUTH_TOKEN" >/dev/null 2>&1 || true
  stop_screen ngrok
  local ngrok_cmd="ngrok http 8000"
  [[ -n "${NGROK_DOMAIN:-}" ]] && ngrok_cmd="ngrok http --url=$NGROK_DOMAIN 8000"
  screen -dmS ngrok bash -c "$ngrok_cmd >> '$LOG_DIR/ngrok.log' 2>&1"
  sleep 4
  log "Ngrok started (see dashboard or $LOG_DIR/ngrok.log)"
}

echo ""
echo "=== Pastor-AI restart ==="
echo "Workspace: $WORKSPACE_ROOT"
echo ""

start_qdrant
start_django

case "$TUNNEL" in
  ngrok) start_ngrok ;;
  *) start_cloudflared ;;
esac

echo ""
screen -list || true
echo ""
if [[ -f "$WORKSPACE_ROOT/public_url.txt" ]]; then
  echo "Open in browser: $(cat "$WORKSPACE_ROOT/public_url.txt")"
fi
echo "Local: http://localhost:8000"
echo "Logs:  $LOG_DIR/"
echo ""
warn "First chat request loads the 14B model (~1-3 min). Later requests are faster."
