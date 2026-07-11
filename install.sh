#!/usr/bin/env bash
# =============================================================================
# Pastor-AI one-command install for RunPod (no Docker required)
#
# Usage (from a fresh RunPod with /workspace volume):
#   curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh | bash
#   # or locally:
#   bash /workspace/pastor-ai/install.sh
#
# Optional env before running:
#   HF_TOKEN=hf_... NGROK_AUTH_TOKEN=... bash install.sh
# =============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
BACKEND_DIR="$WS/backend"
FRONTEND_DIR="$WS/frontend"
APP_DIR="$BACKEND_DIR/app"
VENV_DIR="$WS/venv"
LOG_DIR="$WS/logs"
HF_CACHE="$WS/hf_cache"
QDRANT_BIN="${QDRANT_BIN:-/workspace/bin/qdrant}"
QDRANT_STORAGE="$WS/qdrant_storage"
CONFIG_ENV="$WS/config.env"
MARKER="$WS/.setup_complete"

BACKEND_REPO="${BACKEND_REPO:-https://github.com/Shmurdax/Pastor-AI-Server.git}"
BACKEND_BRANCH="${BACKEND_BRANCH:-server-dev}"
FRONTEND_REPO="${FRONTEND_REPO:-https://github.com/Shmurdax/Pastor-AI-Server.git}"
FRONTEND_BRANCH="${FRONTEND_BRANCH:-front_end_backup}"

VLLM_MODEL="${VLLM_MODEL:-RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16}"
VLLM_PORT="${VLLM_PORT:-8010}"
DJANGO_PORT="${DJANGO_PORT:-8000}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
TUNNEL="${TUNNEL:-cloudflared}"

mkdir -p "$WS" "$LOG_DIR" "$HF_CACHE" "$QDRANT_STORAGE" "$(dirname "$QDRANT_BIN")"
exec > >(tee -a "$LOG_DIR/install.log") 2>&1

log()  { echo -e "\033[0;32m[✔]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
die()  { echo -e "\033[0;31m[✘]\033[0m $*" >&2; exit 1; }
section() {
  echo ""
  echo "═══════════════════════════════════════"
  echo "  $*"
  echo "═══════════════════════════════════════"
}

section "Pastor-AI one-command install"
echo "Workspace: $WS"
echo "Started:   $(date -Iseconds)"

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
section "System packages"
apt-get update -qq
apt-get install -y -qq \
  git curl wget unzip ca-certificates gnupg \
  build-essential screen \
  python3 python3-pip python3-venv python3-dev \
  libpq-dev postgresql postgresql-contrib \
  jq >/dev/null

if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared
  chmod +x /usr/local/bin/cloudflared
fi

if [[ ! -x "$QDRANT_BIN" ]]; then
  log "Downloading Qdrant binary..."
  cd /tmp
  wget -q https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz -O qdrant.tgz
  tar -xzf qdrant.tgz
  mv -f qdrant "$QDRANT_BIN"
  chmod +x "$QDRANT_BIN"
  rm -f qdrant.tgz
fi
log "System packages ready"

# ---------------------------------------------------------------------------
# Clone branches
# ---------------------------------------------------------------------------
section "Clone backend ($BACKEND_BRANCH) + frontend ($FRONTEND_BRANCH)"
if [[ ! -d "$BACKEND_DIR/.git" ]]; then
  git clone --branch "$BACKEND_BRANCH" --single-branch "$BACKEND_REPO" "$BACKEND_DIR"
else
  git -C "$BACKEND_DIR" fetch origin "$BACKEND_BRANCH" || true
  git -C "$BACKEND_DIR" checkout "$BACKEND_BRANCH" || true
  git -C "$BACKEND_DIR" pull --ff-only origin "$BACKEND_BRANCH" || warn "backend pull skipped"
fi

if [[ ! -d "$FRONTEND_DIR/.git" ]]; then
  git clone --branch "$FRONTEND_BRANCH" --single-branch "$FRONTEND_REPO" "$FRONTEND_DIR"
else
  git -C "$FRONTEND_DIR" fetch origin "$FRONTEND_BRANCH" || true
  git -C "$FRONTEND_DIR" checkout "$FRONTEND_BRANCH" || true
  git -C "$FRONTEND_DIR" pull --ff-only origin "$FRONTEND_BRANCH" || warn "frontend pull skipped"
fi
[[ -f "$APP_DIR/manage.py" ]] || die "backend manage.py missing"
[[ -f "$FRONTEND_DIR/index.html" ]] || die "frontend index.html missing"
log "Repos ready"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
section "Configuration"
# Discover HF token without printing it
if [[ -z "${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}" ]]; then
  for t in \
    "${HF_HOME:-}/token" \
    /workspace/.huggingface/token \
    /root/.cache/huggingface/token \
    "$WS/.huggingface/token"
  do
    if [[ -f "$t" ]]; then
      HF_TOKEN="$(tr -d ' \n' < "$t")"
      break
    fi
  done
fi
HF_TOKEN="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"

DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')}"
PUBLIC_API_KEY="${PUBLIC_API_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"

if [[ ! -f "$CONFIG_ENV" ]]; then
  cat > "$CONFIG_ENV" <<EOF
# Pastor-AI RunPod config (generated by install.sh)
WORKSPACE_ROOT=$WS
TUNNEL=$TUNNEL
NGROK_AUTH_TOKEN=${NGROK_AUTH_TOKEN:-}
NGROK_DOMAIN=${NGROK_DOMAIN:-intimiste-qualified-emeline.ngrok-free.dev}

HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
HF_TOKEN=${HF_TOKEN}
HF_HOME=$HF_CACHE
VLLM_URL=http://127.0.0.1:${VLLM_PORT}/v1
VLLM_MODEL=$VLLM_MODEL
VLLM_PORT=$VLLM_PORT

QDRANT_URL=http://127.0.0.1:${QDRANT_PORT}
QDRANT_BIN=$QDRANT_BIN
QDRANT_STORAGE=$QDRANT_STORAGE

FRONTEND_BUILD_DIR=$FRONTEND_DIR
DJANGO_PORT=$DJANGO_PORT
DJANGO_DEBUG=true
DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS=*
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com,https://*.ngrok-free.dev,https://*.proxy.runpod.net,http://localhost,http://127.0.0.1
DJANGO_CORS_ALLOW_ALL_ORIGINS=true
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SECURE_HSTS_SECONDS=0

POSTGRES_DB=ai_db
POSTGRES_USER=pastor
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432

PUBLIC_API_KEY=$PUBLIC_API_KEY
SESSION_SCOPE_SALT=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
EOF
  log "Wrote $CONFIG_ENV"
else
  log "Using existing $CONFIG_ENV"
fi
# shellcheck disable=SC1090
source "$CONFIG_ENV"

if [[ -z "${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}" ]]; then
  warn "No HF_TOKEN set — vLLM model download may fail for gated models."
  warn "Add HUGGING_FACE_HUB_TOKEN to $CONFIG_ENV and re-run."
fi

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
section "PostgreSQL"
service postgresql start 2>/dev/null || pg_ctlcluster 16 main start 2>/dev/null || true
# Wait for postgres
for i in $(seq 1 20); do
  su -s /bin/bash postgres -c "psql -c 'SELECT 1'" >/dev/null 2>&1 && break
  sleep 1
done
su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" | grep -q 1 \
  || su -s /bin/bash postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}' CREATEDB;\""
su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" | grep -q 1 \
  || su -s /bin/bash postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\""
su -s /bin/bash postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\"" >/dev/null
log "Postgres ready (${POSTGRES_DB})"

# ---------------------------------------------------------------------------
# Python venv + deps
# ---------------------------------------------------------------------------
section "Python environment"
export TMPDIR="${TMPDIR:-/workspace/tmp}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q --cache-dir "$PIP_CACHE_DIR" -r "$APP_DIR/requirements.txt"

# CUDA-matched PyTorch first (RunPod L4/4090 images are typically CUDA 12.8)
pip install -q --cache-dir "$PIP_CACHE_DIR" torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# vLLM (GPU inference) — pin a CUDA 12.x-compatible release (0.25+ needs cudart 13)
if ! python -c "import vllm" 2>/dev/null; then
  log "Installing vLLM 0.8.5 (CUDA 12.x compatible)..."
  pip install -q --cache-dir "$PIP_CACHE_DIR" "vllm==0.8.5" \
    || pip install -q --cache-dir "$PIP_CACHE_DIR" "vllm==0.7.3" \
    || warn "vLLM pip install failed"
fi
log "Python env ready"

# ---------------------------------------------------------------------------
# Django migrate / static
# ---------------------------------------------------------------------------
section "Django setup"
cd "$APP_DIR"
export FRONTEND_BUILD_DIR="$FRONTEND_DIR"
export QDRANT_URL="http://127.0.0.1:${QDRANT_PORT}"
export VLLM_URL="http://127.0.0.1:${VLLM_PORT}/v1"
export DJANGO_DEBUG="${DJANGO_DEBUG:-true}"
export DJANGO_SECRET_KEY
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-*}"
export DJANGO_CSRF_TRUSTED_ORIGINS
export DJANGO_CORS_ALLOW_ALL_ORIGINS="${DJANGO_CORS_ALLOW_ALL_ORIGINS:-true}"
export DJANGO_SECURE_SSL_REDIRECT=false
export DJANGO_SESSION_COOKIE_SECURE=false
export DJANGO_CSRF_COOKIE_SECURE=false
export DJANGO_SECURE_HSTS_SECONDS=0
export POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}"
export HF_HOME="$HF_CACHE"
export PUBLIC_API_KEY SESSION_SCOPE_SALT

python manage.py migrate --noinput
python manage.py collectstatic --noinput || warn "collectstatic had warnings"
log "Django migrated"

date -Iseconds > "$MARKER"
log "Setup marker: $MARKER"

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------
section "Starting services"
bash "$WS/start.sh"

section "Install complete"
echo ""
echo "  Workspace: $WS"
echo "  Config:    $CONFIG_ENV"
echo "  After pod restart:  bash $WS/start.sh"
echo "  Reinstall:          FORCE_SETUP=1 bash $WS/install.sh"
if [[ -f "$WS/public_url.txt" ]]; then
  echo "  Public URL: $(cat "$WS/public_url.txt")"
fi
echo ""
