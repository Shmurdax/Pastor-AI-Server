#!/usr/bin/env bash
# Apply latest code, DB migrations, Flutter web rebuild, and restart Pastor-AI on RunPod.
# Usage (on the pod):
#   bash /workspace/pastor-ai/deploy_update.sh
set -euo pipefail

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
CONFIG_ENV="$WS/config.env"
APP_DIR="$WS/backend/app"
VENV_DIR="$WS/venv"
FRONTEND_DIR="$WS/frontend"
LOG_DIR="$WS/logs"

log()  { echo -e "\033[0;32m[deploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[deploy]\033[0m $*"; }
die()  { echo -e "\033[0;31m[deploy]\033[0m $*" >&2; exit 1; }

[[ -f "$CONFIG_ENV" ]] || die "Missing $CONFIG_ENV — run install.sh first"

if [[ -f "$WS/tokens.env" ]]; then
  log "Applying tokens.env → config.env"
  bash "$WS/apply-tokens.sh" || warn "apply-tokens.sh reported an issue"
fi

# shellcheck disable=SC1090
set -a
source "$CONFIG_ENV"
set +a

if [[ -d "$WS/.git" ]]; then
  log "Pulling latest master"
  git -C "$WS" fetch origin master 2>/dev/null || true
  git -C "$WS" pull --ff-only origin master 2>/dev/null || warn "git pull skipped or failed"
fi

[[ -x "$VENV_DIR/bin/python" ]] || die "Python venv missing at $VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  log "Installing Python requirements (Whisper, etc.)"
  pip install -q -r "$APP_DIR/requirements.txt" || warn "pip install requirements failed"
fi

log "Running Django migrations"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"
export FRONTEND_BUILD_DIR="${FRONTEND_BUILD_DIR:-$FRONTEND_DIR/build/web}"
python manage.py migrate --noinput 2>&1 | tee -a "$LOG_DIR/deploy-migrate.log"

if [[ -n "${VIMEO_ACCESS_TOKEN:-}" && -n "${VIMEO_FOLDER_ID:-${VIMEO_SHOWCASE_ID:-}}" ]]; then
  log "Syncing Vimeo Folder media"
  python manage.py sync_vimeo_media 2>&1 | tee -a "$LOG_DIR/deploy-vimeo-sync.log" \
    || warn "Vimeo media sync failed (continuing deploy)"
else
  warn "VIMEO_ACCESS_TOKEN / VIMEO_FOLDER_ID not set — skipping media sync"
fi

if [[ -z "${GOOGLE_CLIENT_ID:-}" ]]; then
  warn "GOOGLE_CLIENT_ID is empty in config.env — Google Sign-In will return 503"
  warn "Set it in tokens.env and run: bash $WS/apply-tokens.sh"
else
  log "GOOGLE_CLIENT_ID is configured for Django"
fi

if [[ -x "$WS/.flutter-sdk/bin/flutter" ]]; then
  export PATH="$WS/.flutter-sdk/bin:$PATH"
fi
if command -v flutter >/dev/null 2>&1; then
  log "Building Flutter web"
  cd "$FRONTEND_DIR"
  FLUTTER_ARGS=(build web --release --dart-define=API_BASE_URL=)
  if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
    FLUTTER_ARGS+=(--dart-define=GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID}")
  fi
  flutter "${FLUTTER_ARGS[@]}"
else
  warn "flutter not in PATH — skipping web rebuild (old UI may still be served)"
fi

log "Restarting services"
bash "$WS/start.sh"

log "Health checks (localhost)"
curl -sf -o /dev/null -w "  GET /api/auth/config/ → %{http_code}\n" \
  "http://127.0.0.1:${DJANGO_PORT:-8000}/api/auth/config/" || true
curl -sf -o /dev/null -w "  GET /api/church-events/ → %{http_code}\n" \
  "http://127.0.0.1:${DJANGO_PORT:-8000}/api/church-events/" || true
curl -sf -o /dev/null -w "  GET /api/media/ → %{http_code}\n" \
  "http://127.0.0.1:${DJANGO_PORT:-8000}/api/media/" || true
curl -sf -o /dev/null -w "  POST /api/auth/google/ → %{http_code}\n" \
  -X POST "http://127.0.0.1:${DJANGO_PORT:-8000}/api/auth/google/" \
  -H "Content-Type: application/json" \
  -d '{"id_token":"x"}' || true

log "Done. Public URL: $(cat "$WS/public_url.txt" 2>/dev/null || echo unknown)"
