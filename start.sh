#!/usr/bin/env bash
# Fast restart of Pastor-AI services on RunPod (no reinstall).
# Usage: bash /workspace/pastor-ai/start.sh
set -euo pipefail

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
CONFIG_ENV="$WS/config.env"
LOG_DIR="$WS/logs"
APP_DIR="$WS/backend/app"
VENV_DIR="$WS/venv"
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

[[ -f "$CONFIG_ENV" ]] || { echo "Missing $CONFIG_ENV — run install.sh first"; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG_ENV"

mkdir -p "$LOG_DIR" "${QDRANT_STORAGE:-$WS/qdrant_storage}" "${HF_HOME:-$WS/hf_cache}"

QDRANT_BIN="${QDRANT_BIN:-/workspace/bin/qdrant}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
# Avoid 8001 — RunPod's host nginx often binds it and fools health checks.
VLLM_PORT="${VLLM_PORT:-8010}"
DJANGO_PORT="${DJANGO_PORT:-8000}"
VLLM_MODEL="${VLLM_MODEL:-RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16}"
TUNNEL="${TUNNEL:-cloudflared}"

log()  { echo -e "\033[0;32m[✔]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
die()  { echo -e "\033[0;31m[✘]\033[0m $*" >&2; exit 1; }

stop_screen() { screen -S "$1" -X quit 2>/dev/null || true; }

vllm_healthy() {
  local body
  body="$(curl -sf --max-time 3 "http://127.0.0.1:${VLLM_PORT}/v1/models" 2>/dev/null || true)"
  [[ "$body" == *'"object"'* ]] || [[ "$body" == *'"data"'* ]]
}

echo ""
echo "=== Pastor-AI start ==="
echo "Workspace: $WS"
echo ""

# Postgres (container restarts wipe apt packages — reinstall if needed)
if ! command -v psql >/dev/null 2>&1; then
  warn "PostgreSQL missing — installing..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq postgresql postgresql-contrib >/dev/null || warn "postgres apt install failed"
fi
service postgresql start 2>/dev/null || pg_ctlcluster 16 main start 2>/dev/null || true
# Ensure app role/db exist (idempotent)
if command -v psql >/dev/null 2>&1 && [[ -n "${POSTGRES_USER:-}" && -n "${POSTGRES_DB:-}" ]]; then
  su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" 2>/dev/null | grep -q 1 \
    || su -s /bin/bash postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}' CREATEDB;\"" 2>/dev/null || true
  su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" 2>/dev/null | grep -q 1 \
    || su -s /bin/bash postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\"" 2>/dev/null || true
fi

# Qdrant
if ! curl -sf "http://127.0.0.1:${QDRANT_PORT}/readyz" >/dev/null 2>&1 \
   && ! curl -sf "http://127.0.0.1:${QDRANT_PORT}/" >/dev/null 2>&1; then
  [[ -x "$QDRANT_BIN" ]] || die "Qdrant binary missing at $QDRANT_BIN"
  stop_screen qdrant
  # Qdrant uses ./storage relative to cwd — point it at persistent volume
  mkdir -p "${QDRANT_STORAGE}"
  # Prefer config via env if supported; else run from storage parent with symlink
  STORAGE_PARENT="$(dirname "${QDRANT_STORAGE}")"
  if [[ ! -e "$STORAGE_PARENT/storage" ]]; then
    ln -sfn "${QDRANT_STORAGE}" "$STORAGE_PARENT/storage" 2>/dev/null || true
  fi
  screen -dmS qdrant bash -c "
    cd '${QDRANT_STORAGE}/..' &&
    mkdir -p storage &&
    export QDRANT__SERVICE__HTTP_PORT=${QDRANT_PORT} &&
    '${QDRANT_BIN}' --storage-path '${QDRANT_STORAGE}' >> '${LOG_DIR}/qdrant.log' 2>&1 ||
    (cd '${QDRANT_STORAGE}' && '${QDRANT_BIN}' >> '${LOG_DIR}/qdrant.log' 2>&1)
  "
  sleep 4
  curl -sf "http://127.0.0.1:${QDRANT_PORT}/" >/dev/null \
    || curl -sf "http://127.0.0.1:${QDRANT_PORT}/readyz" >/dev/null \
    || warn "Qdrant may still be starting — see ${LOG_DIR}/qdrant.log"
  log "Qdrant on :${QDRANT_PORT}"
else
  log "Qdrant already running"
fi

# vLLM
if ! vllm_healthy; then
  [[ -x "$VENV_DIR/bin/python" ]] || die "venv missing — run install.sh"
  FREE_MIB="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo 0)"
  if [[ "${FREE_MIB:-0}" -lt 8000 ]]; then
    warn "GPU has only ${FREE_MIB:-?} MiB free (need ~8GB+). Ghost VRAM from dead host processes?"
    warn "In RunPod: Stop this pod fully → wait 30s → Start again, then re-run start.sh"
  fi
  stop_screen vllm
  : > "${LOG_DIR}/vllm.log"
  HF_TOK="${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}"
  if [[ -z "$HF_TOK" || "$HF_TOK" == *paste* ]]; then
    warn "HF_TOKEN empty — gated model download will fail. Edit tokens.env && bash apply-tokens.sh"
  fi
  # Fine-tuned Qwen Christian LoRA (default) or plain VLLM_MODEL path
  LORA_DIR="${CHRISTIANAI_LORA_DIR:-$WS/christianai-lora}"
  BASE_MODEL="${CHRISTIANAI_BASE_VLLM:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
  SERVED_NAME="${VLLM_MODEL:-christianai}"
  MAX_LEN="${VLLM_MAX_MODEL_LEN:-4096}"
  GPU_UTIL="${VLLM_GPU_MEM_UTIL:-0.90}"
  LORA_ARGS=""
  if [[ -f "$LORA_DIR/adapter_model.safetensors" ]]; then
    LORA_ARGS="--enable-lora --lora-modules ${SERVED_NAME}=${LORA_DIR} --max-lora-rank 16"
    log "vLLM using base ${BASE_MODEL} + LoRA ${LORA_DIR} as '${SERVED_NAME}'"
  else
    BASE_MODEL="${SERVED_NAME}"
    warn "LoRA missing at $LORA_DIR — starting base/model id only: $BASE_MODEL"
  fi
  screen -dmS vllm bash -c "
    source '${VENV_DIR}/bin/activate' &&
    export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
    export HUGGING_FACE_HUB_TOKEN='${HF_TOK}' &&
    export HF_TOKEN='${HF_TOK}' &&
    export HF_HUB_ENABLE_HF_TRANSFER=0 &&
    python -m vllm.entrypoints.openai.api_server \
      --model '${BASE_MODEL}' \
      --served-model-name '${SERVED_NAME}' \
      ${LORA_ARGS} \
      --host 127.0.0.1 \
      --port ${VLLM_PORT} \
      --max-model-len ${MAX_LEN} \
      --gpu-memory-utilization ${GPU_UTIL} \
      --trust-remote-code \
      >> '${LOG_DIR}/vllm.log' 2>&1
  "
  log "vLLM starting on :${VLLM_PORT} (first load downloads model — check ${LOG_DIR}/vllm.log)"
else
  log "vLLM already running on :${VLLM_PORT}"
fi

# Django
[[ -f "$APP_DIR/manage.py" ]] || die "App missing at $APP_DIR"
FRONTEND_BUILD_DIR="$(resolve_frontend_build_dir "$FRONTEND_DIR")"
log "Flutter build dir: $FRONTEND_BUILD_DIR"
stop_screen django
screen -dmS django bash -c "
  source '${VENV_DIR}/bin/activate' &&
  cd '${APP_DIR}' &&
  export FRONTEND_BUILD_DIR='$(resolve_frontend_build_dir "$FRONTEND_DIR")' &&
  export QDRANT_URL='${QDRANT_URL:-http://127.0.0.1:$QDRANT_PORT}' &&
  export VLLM_URL='${VLLM_URL:-http://127.0.0.1:$VLLM_PORT/v1}' &&
  export DJANGO_DEBUG='${DJANGO_DEBUG:-true}' &&
  export DJANGO_SECRET_KEY='${DJANGO_SECRET_KEY}' &&
  export DJANGO_ALLOWED_HOSTS='${DJANGO_ALLOWED_HOSTS:-*}' &&
  export DJANGO_CSRF_TRUSTED_ORIGINS='${DJANGO_CSRF_TRUSTED_ORIGINS:-}' &&
  export DJANGO_CORS_ALLOW_ALL_ORIGINS='${DJANGO_CORS_ALLOW_ALL_ORIGINS:-true}' &&
  export DJANGO_SECURE_SSL_REDIRECT=false &&
  export DJANGO_SESSION_COOKIE_SECURE=false &&
  export DJANGO_CSRF_COOKIE_SECURE=false &&
  export DJANGO_SECURE_HSTS_SECONDS=0 &&
  export POSTGRES_DB='${POSTGRES_DB}' &&
  export POSTGRES_USER='${POSTGRES_USER}' &&
  export POSTGRES_PASSWORD='${POSTGRES_PASSWORD}' &&
  export POSTGRES_HOST='${POSTGRES_HOST:-127.0.0.1}' &&
  export POSTGRES_PORT='${POSTGRES_PORT:-5432}' &&
  export PUBLIC_API_KEY='${PUBLIC_API_KEY:-}' &&
  export SESSION_SCOPE_SALT='${SESSION_SCOPE_SALT:-}' &&
  export HUGGING_FACE_HUB_TOKEN='${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}' &&
  export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
  exec gunicorn pastor_ai.wsgi:application --bind 0.0.0.0:${DJANGO_PORT} --workers 2 --timeout 1800 \
    >> '${LOG_DIR}/django.log' 2>&1
"
sleep 3
curl -sf -o /dev/null "http://127.0.0.1:${DJANGO_PORT}/" && log "Django on :${DJANGO_PORT}" \
  || warn "Django not responding yet — see ${LOG_DIR}/django.log"

# Tunnel
case "$TUNNEL" in
  ngrok)
    [[ -n "${NGROK_AUTH_TOKEN:-}" ]] || die "NGROK_AUTH_TOKEN missing in config.env"
    command -v ngrok >/dev/null || die "ngrok not installed"
    ngrok config add-authtoken "$NGROK_AUTH_TOKEN" >/dev/null 2>&1 || true
    stop_screen ngrok
    if [[ -n "${NGROK_DOMAIN:-}" ]]; then
      screen -dmS ngrok bash -c "ngrok http --url=${NGROK_DOMAIN} ${DJANGO_PORT} >> '${LOG_DIR}/ngrok.log' 2>&1"
    else
      screen -dmS ngrok bash -c "ngrok http ${DJANGO_PORT} >> '${LOG_DIR}/ngrok.log' 2>&1"
    fi
    sleep 5
    URL="$(curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -oE 'https://[^"]+' | head -1 || true)"
    if [[ -n "$URL" ]]; then
      echo "$URL" > "$WS/public_url.txt"
      log "Public URL (ngrok): $URL"
    else
      warn "ngrok URL not ready — check ${LOG_DIR}/ngrok.log"
      [[ -n "${NGROK_DOMAIN:-}" ]] && echo "https://${NGROK_DOMAIN}" > "$WS/public_url.txt"
    fi
    ;;
  *)
    command -v cloudflared >/dev/null || die "cloudflared not installed"
    stop_screen cloudflared
    : > "$LOG_DIR/cloudflared.log"
    screen -dmS cloudflared bash -c \
      "cloudflared tunnel --url http://127.0.0.1:${DJANGO_PORT} >> '${LOG_DIR}/cloudflared.log' 2>&1"
    sleep 8
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" | head -1 || true)"
    if [[ -n "$URL" ]]; then
      echo "$URL" > "$WS/public_url.txt"
      log "Public URL (Cloudflare): $URL"
    else
      warn "Cloudflare URL not ready — check ${LOG_DIR}/cloudflared.log"
    fi
    ;;
esac

echo ""
screen -list || true
echo ""
if [[ -f "$WS/public_url.txt" ]]; then
  echo "Open: $(cat "$WS/public_url.txt")"
fi
echo "Local: http://127.0.0.1:${DJANGO_PORT}"
echo "RunPod proxy: https://${RUNPOD_POD_ID:-PODID}-${DJANGO_PORT}.proxy.runpod.net"
echo "Logs: $LOG_DIR/"
echo ""
warn "First chat may take several minutes while the LLM loads into GPU memory."
