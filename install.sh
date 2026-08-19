#!/usr/bin/env bash
# =============================================================================
# Pastor-AI full install — matches the production RunPod network-volume stack
#
# One-liner (from a GPU machine with /workspace or set WORKSPACE_ROOT):
#   bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
#
# Or after cloning this repo:
#   git clone https://github.com/GavWrecker/Pastor-AI-Server.git
#   cd Pastor-AI-Server && bash install.sh
#
# Required:
#   HF_TOKEN  — Hugging Face token with access to private LoRA
#               apophaticai/qwen2.5-14b-christianai-v1
#
# Optional (tokens.env or env vars):
#   NGROK_AUTH_TOKEN, NGROK_DOMAIN, GITHUB_TOKEN, PUBLIC_API_KEY
#
# What this installs (native path — default, works on RunPod):
#   apt packages, Docker + NVIDIA Container Toolkit (best-effort),
#   PostgreSQL, Qdrant, Python venv, torch cu128, vLLM 0.8.5,
#   Qwen2.5-14B-Instruct-AWQ + Christian LoRA, Django, Cloudflare tunnel,
#   sermon RAG ingest into Qdrant collection sermon_brain
#
# After pod restart:
#   bash /workspace/pastor-ai/start.sh
# =============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

REPO_URL="${REPO_URL:-https://github.com/GavWrecker/Pastor-AI-Server.git}"
REPO_BRANCH="${REPO_BRANCH:-master}"

# Resolve script / repo root (supports curl|bash where BASH_SOURCE is missing)
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
else
  REPO_ROOT=""
fi

# If not running from a checkout that already has backend/, clone this repo first
if [[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT/backend/app" ]]; then
  BOOTSTRAP="${BOOTSTRAP_DIR:-/tmp/Pastor-AI-Server-bootstrap}"
  echo "[*] Cloning $REPO_URL ($REPO_BRANCH) → $BOOTSTRAP"
  rm -rf "$BOOTSTRAP"
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$BOOTSTRAP"
  exec bash "$BOOTSTRAP/install.sh" "$@"
fi

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
BACKEND_DIR="$WS/backend"
FRONTEND_DIR="$WS/frontend"

resolve_frontend_build_dir() {
  local root="${1:-$FRONTEND_DIR}"
  if [[ -f "$root/build/web/index.html" ]]; then
    echo "$root/build/web"
  elif [[ -f "$root/index.html" ]]; then
    echo "$root"
  else
    echo "$root"
  fi
}
APP_DIR="$BACKEND_DIR/app"
VENV_DIR="$WS/venv"
LOG_DIR="$WS/logs"
HF_CACHE="$WS/hf_cache"
QDRANT_BIN="${QDRANT_BIN:-/workspace/bin/qdrant}"
QDRANT_STORAGE="$WS/qdrant_storage"
LORA_DIR="${CHRISTIANAI_LORA_DIR:-$WS/christianai-lora}"
CONFIG_ENV="$WS/config.env"
TOKENS_ENV="$WS/tokens.env"
MARKER="$WS/.setup_complete"

# Model stack (current production)
CHRISTIANAI_HF_REPO="${CHRISTIANAI_HF_REPO:-apophaticai/qwen2.5-14b-christianai-v1}"
CHRISTIANAI_BASE_VLLM="${CHRISTIANAI_BASE_VLLM:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
VLLM_MODEL="${VLLM_MODEL:-christianai}"
VLLM_PORT="${VLLM_PORT:-8010}"
DJANGO_PORT="${DJANGO_PORT:-8000}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
TUNNEL="${TUNNEL:-cloudflared}"
SKIP_INGEST="${SKIP_INGEST:-0}"
FORCE_DOCKER="${FORCE_DOCKER:-0}"
USE_DOCKER="${USE_DOCKER:-auto}"  # auto | yes | no

mkdir -p "$WS" "$LOG_DIR" "$HF_CACHE" "$QDRANT_STORAGE" "$(dirname "$QDRANT_BIN")" /workspace/tmp /workspace/.cache/pip
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
export TMPDIR="${TMPDIR:-/workspace/tmp}"
export HF_HOME="$HF_CACHE"
export HF_HUB_ENABLE_HF_TRANSFER=0

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

section "Pastor-AI full install"
echo "Workspace: $WS"
echo "Repo root: $REPO_ROOT"
echo "Started:   $(date -Iseconds)"

# Load tokens.env / config if present
if [[ -f "$TOKENS_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$TOKENS_ENV"
  set +a
  log "Loaded $TOKENS_ENV"
elif [[ -f "$REPO_ROOT/tokens.env" ]]; then
  cp "$REPO_ROOT/tokens.env" "$TOKENS_ENV"
  set -a
  # shellcheck disable=SC1090
  source "$TOKENS_ENV"
  set +a
fi
if [[ -f "$CONFIG_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV"
  set +a
fi

[[ -n "${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}" ]] \
  || die "HF_TOKEN required (private LoRA). Create tokens.env from tokens.env.example or export HF_TOKEN=..."

export HF_TOKEN="${HF_TOKEN:-$HUGGING_FACE_HUB_TOKEN}"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

# ---------------------------------------------------------------------------
# System packages + NVIDIA / Docker (best-effort)
# ---------------------------------------------------------------------------
section "System packages"
apt-get update -qq
apt-get install -y -qq \
  git curl wget unzip ca-certificates gnupg lsb-release \
  build-essential screen jq ffmpeg \
  python3 python3-pip python3-venv python3-dev \
  libpq-dev postgresql postgresql-contrib \
  pciutils libreoffice-writer >/dev/null

# NVIDIA driver / toolkit — usually preinstalled on RunPod; install toolkit if missing
if ! command -v nvidia-smi >/dev/null 2>&1; then
  warn "nvidia-smi missing — attempting ubuntu nvidia-driver install (may require reboot)"
  apt-get install -y -qq nvidia-driver-570 || apt-get install -y -qq nvidia-driver-535 || warn "NVIDIA driver install failed"
else
  log "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
fi

# Docker + NVIDIA Container Toolkit (optional; native path used if daemon cannot start)
install_docker() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed: $(docker --version 2>/dev/null || true)"
    return 0
  fi
  log "Installing Docker Engine..."
  curl -fsSL https://get.docker.com | sh || {
    warn "get.docker.com failed — trying apt docker.io"
    apt-get install -y -qq docker.io docker-compose-v2 || return 1
  }
  systemctl enable --now docker 2>/dev/null || service docker start 2>/dev/null || true
}

install_nvidia_container_toolkit() {
  if dpkg -l nvidia-container-toolkit 2>/dev/null | grep -q ^ii; then
    log "nvidia-container-toolkit already installed"
    return 0
  fi
  log "Installing NVIDIA Container Toolkit..."
  distribution="$(. /etc/os-release; echo "${ID}${VERSION_ID}")"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null || true
  curl -fsSL "https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list" 2>/dev/null \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list 2>/dev/null || true
  apt-get update -qq || true
  apt-get install -y -qq nvidia-container-toolkit 2>/dev/null || warn "nvidia-container-toolkit apt install failed"
  nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
  systemctl restart docker 2>/dev/null || true
}

install_docker || warn "Docker install skipped/failed"
install_nvidia_container_toolkit || true

DOCKER_OK=0
if docker info >/dev/null 2>&1; then
  DOCKER_OK=1
  log "Docker daemon is usable"
else
  warn "Docker daemon not usable on this host (common on some RunPod images)"
  warn "Continuing with NATIVE install (matches current production)"
fi

if [[ "$USE_DOCKER" == "yes" || ( "$USE_DOCKER" == "auto" && "$FORCE_DOCKER" == "1" && "$DOCKER_OK" == "1" ) ]]; then
  if [[ "$DOCKER_OK" == "1" ]]; then
    section "Docker Compose path"
    warn "Docker path is experimental vs native production; prefer native on RunPod"
    # Fall through to native for fidelity to current production unless FORCE_DOCKER=1
    if [[ "$FORCE_DOCKER" != "1" ]]; then
      warn "Set FORCE_DOCKER=1 to force compose; using native stack"
      DOCKER_OK=0
    fi
  fi
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared
  chmod +x /usr/local/bin/cloudflared
  log "cloudflared installed"
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
# Sync backend + frontend from this repo into the workspace
# ---------------------------------------------------------------------------
section "Sync backend + frontend into $WS"
rsync -a --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='venv' --exclude='hf_cache' --exclude='qdrant_storage' \
  --exclude='app/uploads/' \
  "$REPO_ROOT/backend/" "$BACKEND_DIR/"
rsync -a --delete --exclude='.git' \
  "$REPO_ROOT/frontend/" "$FRONTEND_DIR/"
cp -a "$REPO_ROOT/start.sh" "$WS/start.sh"
cp -a "$REPO_ROOT/persist_runtime.sh" "$WS/persist_runtime.sh"
cp -a "$REPO_ROOT/apply-tokens.sh" "$WS/apply-tokens.sh"
cp -a "$REPO_ROOT/tokens.env.example" "$WS/tokens.env.example"
cp -a "$REPO_ROOT/install.sh" "$WS/install.sh"
[[ -f "$REPO_ROOT/ingest_sermons.sh" ]] && cp -a "$REPO_ROOT/ingest_sermons.sh" "$WS/ingest_sermons.sh"
[[ -f "$REPO_ROOT/crawl_websites.sh" ]] && cp -a "$REPO_ROOT/crawl_websites.sh" "$WS/crawl_websites.sh"
chmod +x "$WS"/*.sh
[[ -f "$APP_DIR/manage.py" ]] || die "manage.py missing after sync"
log "Code synced (backend + frontend + scripts)"

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
section "PostgreSQL"
if [[ -f "$CONFIG_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV"
  set +a
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/persist_runtime.sh"
ensure_persistent_postgres || service postgresql start 2>/dev/null || pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 15 main start 2>/dev/null || true
ensure_persistent_uploads
sleep 2

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
section "Config"
if [[ ! -f "$CONFIG_ENV" ]]; then
  DJANGO_SECRET_KEY="$(openssl rand -hex 32)"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -hex 12)}"
  cat > "$CONFIG_ENV" <<EOF
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=*
DJANGO_CORS_ALLOW_ALL_ORIGINS=true
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SUPERUSER_USERNAME=${DJANGO_SUPERUSER_USERNAME:-admin}
DJANGO_SUPERUSER_PASSWORD=${DJANGO_SUPERUSER_PASSWORD:-admin123}
DJANGO_SUPERUSER_EMAIL=${DJANGO_SUPERUSER_EMAIL:-admin@localhost}
POSTGRES_DB=${POSTGRES_DB:-ai_db}
POSTGRES_USER=${POSTGRES_USER:-pastor}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
HF_TOKEN=${HF_TOKEN}
HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
HF_HOME=${HF_CACHE}
HF_HUB_ENABLE_HF_TRANSFER=0
VLLM_URL=http://127.0.0.1:${VLLM_PORT}/v1
VLLM_MODEL=${VLLM_MODEL}
VLLM_PORT=${VLLM_PORT}
VLLM_MAX_MODEL_LEN=4096
VLLM_GPU_MEM_UTIL=0.90
CHRISTIANAI_HF_REPO=${CHRISTIANAI_HF_REPO}
CHRISTIANAI_LORA_DIR=${LORA_DIR}
CHRISTIANAI_BASE_VLLM=${CHRISTIANAI_BASE_VLLM}
CHRISTIANAI_SERVED_NAME=${VLLM_MODEL}
QDRANT_URL=http://127.0.0.1:${QDRANT_PORT}
QDRANT_BIN=${QDRANT_BIN}
QDRANT_STORAGE=${QDRANT_STORAGE}
QDRANT_COLLECTION=sermon_brain
INGESTION_UPLOAD_DIR=/workspace/persistent/uploads/admin_ingestion
VIDEO_INGESTION_UPLOAD_DIR=/workspace/persistent/uploads/admin_video_ingestion
FRONTEND_BUILD_DIR="$(resolve_frontend_build_dir "$FRONTEND_DIR")"
TUNNEL=${TUNNEL}
PUBLIC_API_KEY=
EOF
  log "Wrote $CONFIG_ENV"
else
  log "Keeping existing $CONFIG_ENV"
fi

# Ensure DB role exists
set -a
# shellcheck disable=SC1090
source "$CONFIG_ENV"
set +a
su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" | grep -q 1 \
  || su -s /bin/bash postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}' CREATEDB;\""
su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" | grep -q 1 \
  || su -s /bin/bash postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\""
su -s /bin/bash postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\"" >/dev/null

if [[ -f "$TOKENS_ENV" ]]; then
  bash "$WS/apply-tokens.sh" || true
fi

# ---------------------------------------------------------------------------
# Python venv + deps
# ---------------------------------------------------------------------------
section "Python environment"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
if [[ -f "$APP_DIR/requirements.txt" ]]; then
  pip install -q --cache-dir "$PIP_CACHE_DIR" -r "$APP_DIR/requirements.txt"
fi
pip install -q --cache-dir "$PIP_CACHE_DIR" torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip uninstall -y torchcodec torch_c_dlpack_ext 2>/dev/null || true
pip install -q --cache-dir "$PIP_CACHE_DIR" "transformers==4.51.3" "tokenizers==0.21.1" "huggingface_hub>=0.30.0,<1.0"
if ! python -c "import vllm" 2>/dev/null; then
  log "Installing vLLM 0.8.5 (CUDA 12.x)..."
  pip install -q --cache-dir "$PIP_CACHE_DIR" "vllm==0.8.5" \
    || pip install -q --cache-dir "$PIP_CACHE_DIR" "vllm==0.7.3" \
    || die "vLLM install failed"
fi
pip install -q --cache-dir "$PIP_CACHE_DIR" "transformers==4.51.3" "tokenizers==0.21.1"
pip uninstall -y torchcodec torch_c_dlpack_ext 2>/dev/null || true
pip install -q --cache-dir "$PIP_CACHE_DIR" hf_transfer 2>/dev/null || true
log "Python env ready: torch $(python -c 'import torch; print(torch.__version__)') vllm $(python -c 'import vllm; print(vllm.__version__)')"

# ---------------------------------------------------------------------------
# Download Christian LoRA
# ---------------------------------------------------------------------------
section "Download Christian LoRA ($CHRISTIANAI_HF_REPO)"
mkdir -p "$LORA_DIR"
export CHRISTIANAI_HF_REPO LORA_DIR HF_TOKEN
python - <<'PY'
import os
from huggingface_hub import snapshot_download
repo = os.environ["CHRISTIANAI_HF_REPO"]
dest = os.environ["LORA_DIR"]
token = os.environ.get("HF_TOKEN")
snapshot_download(repo_id=repo, local_dir=dest, token=token)
print("lora_ok", dest)
PY
[[ -f "$LORA_DIR/adapter_model.safetensors" ]] || die "LoRA download missing adapter_model.safetensors"

# ---------------------------------------------------------------------------
# Django migrate
# ---------------------------------------------------------------------------
section "Django migrate"
cd "$APP_DIR"
export FRONTEND_BUILD_DIR="$(resolve_frontend_build_dir "$FRONTEND_DIR")"
log "Serving Flutter from $FRONTEND_BUILD_DIR"
export QDRANT_URL="http://127.0.0.1:${QDRANT_PORT}"
export VLLM_URL="http://127.0.0.1:${VLLM_PORT}/v1"
export VLLM_MODEL
export POSTGRES_HOST=127.0.0.1
export DJANGO_DEBUG=true
export DJANGO_SECURE_SSL_REDIRECT=false
export DJANGO_SESSION_COOKIE_SECURE=false
export DJANGO_CSRF_COOKIE_SECURE=false
python manage.py migrate --noinput
python manage.py ensure_superuser
python manage.py collectstatic --noinput 2>/dev/null || true
log "Django ready (admin login: ${DJANGO_SUPERUSER_USERNAME:-admin} / ${DJANGO_SUPERUSER_PASSWORD:-admin123})"

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------
section "Start services"
bash "$WS/start.sh"

# ---------------------------------------------------------------------------
# RAG ingest
# ---------------------------------------------------------------------------
if [[ "$SKIP_INGEST" != "1" ]]; then
  section "Ingest sermon RAG → sermon_brain"
  bash "$WS/ingest_sermons.sh" || warn "Ingest failed — run later: bash $WS/ingest_sermons.sh"
else
  warn "SKIP_INGEST=1 — skipping RAG ingest"
fi

date -Iseconds > "$MARKER"
section "Install complete"
echo "Workspace: $WS"
echo "Public URL: $(cat "$WS/public_url.txt" 2>/dev/null || echo '(see start.sh / cloudflared)')"
echo "After restart: bash $WS/start.sh"
echo "Update tokens:  nano $WS/tokens.env && bash $WS/apply-tokens.sh --restart"
log "Done $(date -Iseconds)"
