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
# shellcheck source=/dev/null
source "$WS/scripts/load_env.sh"

if [[ -f "$WS/tokens.env" ]]; then
  log "Applying tokens.env → config.env"
  bash "$WS/apply-tokens.sh" || warn "apply-tokens.sh reported an issue"
fi

pastor_load_env_file "$CONFIG_ENV"

# Git channel: PASTOR_GIT_BRANCH / REPO_BRANCH override, else master.
# christian-ai-dev: PASTOR_GIT_BRANCH=development bash deploy_update.sh
# shellcheck source=/dev/null
source "$WS/scripts/git_channel.sh" 2>/dev/null || source "$(dirname "$0")/scripts/git_channel.sh"
# shellcheck source=/dev/null
source "$WS/scripts/git_safe_directory.sh" 2>/dev/null || source "$(dirname "$0")/scripts/git_safe_directory.sh"
# shellcheck source=/dev/null
source "$WS/scripts/sync_git_channel.sh" 2>/dev/null || source "$(dirname "$0")/scripts/sync_git_channel.sh"
pastor_allow_git_on_runpod_volume "$WS"
if [[ -n "${PASTOR_GIT_BRANCH:-}${REPO_BRANCH:-}" ]]; then
  CHANNEL="$(pastor_git_channel "$WS")"
else
  CHANNEL=master
fi
pastor_write_git_channel "$WS" "$CHANNEL"
if [[ -d "$WS/.git" ]]; then
  pastor_sync_git_channel "$WS" "$CHANNEL" \
    || die "git sync origin/$CHANNEL failed"
else
  die "No .git checkout at $WS — clone Pastor-AI before deploy_update"
fi

[[ -x "$VENV_DIR/bin/python" ]] || die "Python venv missing at $VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# shellcheck source=/dev/null
source "$WS/scripts/deploy_steps.sh" 2>/dev/null || source "$(dirname "$0")/scripts/deploy_steps.sh"

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  log "Installing Python requirements (Whisper, etc.)"
  deploy_pip "$APP_DIR" "$VENV_DIR"
fi

log "Running Django migrations"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"
export FRONTEND_BUILD_DIR="${FRONTEND_BUILD_DIR:-$FRONTEND_DIR/build/web}"
python manage.py migrate --noinput 2>&1 | tee -a "$LOG_DIR/deploy-migrate.log"
python manage.py reset_id_sequences 2>&1 | tee -a "$LOG_DIR/deploy-migrate.log" || true

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
  log "Using $WS/.flutter-sdk (git safe.directory already set for this volume)"
fi
log "Building Flutter web into a staging directory"
deploy_flutter_staging "$FRONTEND_DIR"
deploy_swap_web "$FRONTEND_DIR"

log "Restarting services"
deploy_start "$WS"
if declare -F pastor_record_running_git >/dev/null 2>&1; then
  pastor_record_running_git "$WS" || true
fi

log "Health checks (localhost)"
deploy_health_localhost "${DJANGO_PORT:-8000}"

log "Done. Public URL: $(cat "$WS/public_url.txt" 2>/dev/null || echo unknown)"
