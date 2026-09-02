#!/usr/bin/env bash
# Local Pastor-AI without chat stack (no vLLM, Qdrant, Whisper, tunnel).
# Serves Flutter web + auth + billing from Django on :8000.
#
# Usage:
#   bash scripts/start-minimal.sh
#   bash scripts/start-minimal.sh --validate-stripe   # verify Stripe keys first
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$WS/backend/app"
VENV="${VENV_DIR:-$WS/venv}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
PORT="${DJANGO_PORT:-8000}"
VALIDATE_STRIPE=0

for arg in "$@"; do
  case "$arg" in
    --validate-stripe) VALIDATE_STRIPE=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: bash scripts/start-minimal.sh [--validate-stripe]" >&2
      exit 1
      ;;
  esac
done

log()  { echo -e "\033[0;32m[minimal]\033[0m $*"; }
warn() { echo -e "\033[1;33m[minimal]\033[0m $*"; }
die()  { echo -e "\033[0;31m[minimal]\033[0m $*" >&2; exit 1; }

_has_stripe_env_secrets() {
  local key val
  for key in STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY; do
    val="$(printenv "$key" 2>/dev/null || true)"
    [[ -n "$val" ]] || return 1
  done
}

[[ -x "$VENV/bin/python" ]] || die "Missing venv at $VENV — run install.sh or create venv first."

if [[ -f "$WS/tokens.env" || _has_stripe_env_secrets ]]; then
  APPLY_ARGS=()
  [[ "$VALIDATE_STRIPE" -eq 1 ]] && APPLY_ARGS+=(--validate-stripe)
  bash "$WS/apply-tokens.sh" "${APPLY_ARGS[@]}" || true
fi

if [[ -f "$CONFIG" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$CONFIG"
  set +a
fi

export DJANGO_USE_SQLITE=1
unset POSTGRES_HOST

export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-dev-local-change-me}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-*}"
export DJANGO_CORS_ALLOW_ALL_ORIGINS="${DJANGO_CORS_ALLOW_ALL_ORIGINS:-true}"
export DJANGO_SECURE_SSL_REDIRECT=false
export DJANGO_SESSION_COOKIE_SECURE=false
export DJANGO_CSRF_COOKIE_SECURE=false
export FRONTEND_BUILD_DIR="${FRONTEND_BUILD_DIR:-$WS/frontend}"
export PUBLIC_APP_URL="${PUBLIC_APP_URL:-http://127.0.0.1:${PORT}}"

# Merge Cursor/cloud secrets (not written to config.env on disk).
declare -A ENV_SECRET_OVERRIDE=()
for key in STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET BILLING_MOCK_CHECKOUT GOOGLE_CLIENT_ID; do
  val="$(printenv "$key" 2>/dev/null || true)"
  [[ -n "$val" ]] && ENV_SECRET_OVERRIDE[$key]="$val"
done
for key in "${!ENV_SECRET_OVERRIDE[@]}"; do
  export "$key=${ENV_SECRET_OVERRIDE[$key]}"
done

# If Stripe keys are missing, fall back to mock checkout for local billing tests.
case "${STRIPE_SECRET_KEY:-}${STRIPE_PUBLISHABLE_KEY:-}" in
  ""|*paste_here*) export BILLING_MOCK_CHECKOUT=true ;;
esac

# Chat stack intentionally unset — /api/chat/ will fail if called.
unset VLLM_URL QDRANT_URL QDRANT_COLLECTION 2>/dev/null || true

log "Installing minimal Python deps (Django, DRF, Stripe)…"
"$VENV/bin/pip" install -q \
  'django>=4.2,<5.0' djangorestframework django-cors-headers \
  gunicorn 'whitenoise[brotli]' stripe google-auth requests 2>/dev/null || true

cd "$APP_DIR"
log "Running migrations (SQLite)…"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py ensure_superuser 2>/dev/null || true

# Stop any prior minimal server on this port.
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi

log "Starting Django on http://127.0.0.1:${PORT}/"
log "  Auth + billing only — chat/RAG endpoints are not backed by vLLM/Qdrant."
log "  Admin: http://127.0.0.1:${PORT}/admin/ (default admin / admin123)"
echo ""

exec "$VENV/bin/python" manage.py runserver "0.0.0.0:${PORT}"
