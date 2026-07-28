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

postgres_ready() {
  local host="${POSTGRES_HOST:-127.0.0.1}"
  local port="${POSTGRES_PORT:-5432}"
  local user="${POSTGRES_USER:-pastor}"
  local db="${POSTGRES_DB:-ai_db}"
  PGPASSWORD="${POSTGRES_PASSWORD:-}" psql -h "$host" -p "$port" -U "$user" -d "$db" -c 'SELECT 1' >/dev/null 2>&1
}

# RunPod network volumes often cannot chown(). Postgres requires a local data dir
# owned by user postgres, so we keep the cluster on the ephemeral disk and
# persist the app database with pg_dump ↔ pg_restore on the volume.
postgres_dump_path() {
  echo "${POSTGRES_DUMP_PATH:-$WS/postgres_data/${POSTGRES_DB:-ai_db}.dump}"
}

persist_postgres_dump() {
  local dump tmp
  dump="$(postgres_dump_path)"
  tmp="${dump}.tmp"
  mkdir -p "$(dirname "$dump")"
  if ! postgres_ready; then
    warn "Skip Postgres dump — DB not ready"
    return 0
  fi
  if PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
      -h "${POSTGRES_HOST:-127.0.0.1}" \
      -p "${POSTGRES_PORT:-5432}" \
      -U "${POSTGRES_USER:-pastor}" \
      -Fc \
      --no-owner \
      "${POSTGRES_DB:-ai_db}" \
      -f "$tmp" 2>>"${LOG_DIR}/postgres_dump.log"; then
    mv -f "$tmp" "$dump"
    log "Postgres dump saved → ${dump}"
  else
    rm -f "$tmp"
    warn "Postgres dump failed — see ${LOG_DIR}/postgres_dump.log"
  fi
}

restore_postgres_dump_if_needed() {
  local dump
  dump="$(postgres_dump_path)"
  [[ -f "$dump" ]] || return 0
  postgres_ready || return 0
  # If core tables already exist, keep live DB (dump is for migrate recovery).
  if PGPASSWORD="${POSTGRES_PASSWORD:-}" psql \
      -h "${POSTGRES_HOST:-127.0.0.1}" \
      -p "${POSTGRES_PORT:-5432}" \
      -U "${POSTGRES_USER:-pastor}" \
      -d "${POSTGRES_DB:-ai_db}" \
      -tc "SELECT 1 FROM information_schema.tables WHERE table_name='core_chatmessage'" 2>/dev/null \
      | grep -q 1; then
    log "Postgres app tables present — leaving DB as-is"
    return 0
  fi
  log "Restoring Postgres from volume dump ${dump}"
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_restore \
    -h "${POSTGRES_HOST:-127.0.0.1}" \
    -p "${POSTGRES_PORT:-5432}" \
    -U "${POSTGRES_USER:-pastor}" \
    -d "${POSTGRES_DB:-ai_db}" \
    --no-owner \
    --exit-on-error \
    "$dump" >>"${LOG_DIR}/postgres_restore.log" 2>&1 \
    || warn "pg_restore reported errors — see ${LOG_DIR}/postgres_restore.log (migrate may still fix schema)"
}

ensure_postgres() {
  local pg_ver cluster_data
  pg_ver="$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1 || true)"
  [[ -n "$pg_ver" ]] || pg_ver="16"
  cluster_data="/var/lib/postgresql/${pg_ver}/main"

  # Undo any prior symlink-to-volume attempt (breaks ownership on RunPod volumes).
  if [[ -L "$cluster_data" ]]; then
    warn "Removing Postgres symlink to network volume (unsupported on RunPod)"
    service postgresql stop 2>/dev/null || pg_ctlcluster "$pg_ver" main stop 2>/dev/null || true
    rm -f "$cluster_data"
    if [[ -d "${cluster_data}.ephemeral-bak/base" ]]; then
      mv "${cluster_data}.ephemeral-bak" "$cluster_data"
    fi
  fi

  # Ensure a real local data directory with correct ownership.
  if [[ ! -d "${cluster_data}/base" ]]; then
    service postgresql start 2>/dev/null || pg_ctlcluster "$pg_ver" main start 2>/dev/null || true
    sleep 2
  fi
  if [[ -d "$cluster_data" ]]; then
    chown -R postgres:postgres "$cluster_data" 2>/dev/null || true
    chmod 700 "$cluster_data" 2>/dev/null || true
  fi

  service postgresql start 2>/dev/null || pg_ctlcluster "$pg_ver" main start 2>/dev/null || true
  local i
  for i in $(seq 1 30); do
    if su -s /bin/bash postgres -c "psql -c 'SELECT 1'" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
}

gpu_looks_ghosted() {
  # Classic RunPod ghost VRAM: high util / tiny used memory / no compute PIDs.
  local used util procs
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo 0)"
  util="$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo 0)"
  procs="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sed '/^\s*$/d' | wc -l | tr -d ' ')"
  used="${used:-0}"
  util="${util:-0}"
  procs="${procs:-0}"
  if [[ "$procs" -eq 0 && "$used" -lt 500 && "$util" -ge 80 ]]; then
    return 0
  fi
  return 1
}

echo ""
echo "=== Pastor-AI start ==="
echo "Workspace: $WS"
echo ""

# Postgres (packages are ephemeral; DB contents are dumped to the network volume)
if ! command -v psql >/dev/null 2>&1; then
  warn "PostgreSQL missing — installing..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq postgresql postgresql-contrib >/dev/null || warn "postgres apt install failed"
fi
ensure_postgres
# Ensure app role/db exist (idempotent)
if command -v psql >/dev/null 2>&1 && [[ -n "${POSTGRES_USER:-}" && -n "${POSTGRES_DB:-}" ]]; then
  su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" 2>/dev/null | grep -q 1 \
    || su -s /bin/bash postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}' CREATEDB;\"" 2>/dev/null || true
  su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" 2>/dev/null | grep -q 1 \
    || su -s /bin/bash postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\"" 2>/dev/null || true
  su -s /bin/bash postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\"" >/dev/null 2>&1 || true
fi
restore_postgres_dump_if_needed
if postgres_ready; then
  log "Postgres ready (${POSTGRES_DB}; dump=$(postgres_dump_path))"
else
  warn "Postgres not accepting app connections yet — Django migrate may retry"
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
  if gpu_looks_ghosted; then
    warn "GPU looks ghosted (high util, ~0 MiB used, no processes)."
    warn "Fully Stop the pod in RunPod → wait 30s → Start (onboot/start.sh will resume)."
  elif [[ "${FREE_MIB:-0}" -lt 8000 ]]; then
    warn "GPU has only ${FREE_MIB:-?} MiB free (need ~8GB+)."
    warn "If util is high with no processes: Stop pod fully → wait 30s → Start again."
  fi
  stop_screen vllm
  pkill -9 -f 'vllm.entrypoints.openai.api_server' 2>/dev/null || true
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
# Kill screen + any orphaned gunicorn from prior boots (common after migrate)
stop_screen django
pkill -9 -f 'gunicorn pastor_ai.wsgi' 2>/dev/null || true
fuser -k "${DJANGO_PORT}/tcp" 2>/dev/null || true
sleep 1
screen -dmS django bash -c "
  source '${VENV_DIR}/bin/activate' &&
  cd '${APP_DIR}' &&
  export FRONTEND_BUILD_DIR='$(resolve_frontend_build_dir "$FRONTEND_DIR")' &&
  export QDRANT_URL='${QDRANT_URL:-http://127.0.0.1:$QDRANT_PORT}' &&
  export QDRANT_COLLECTION='${QDRANT_COLLECTION:-sermon_brain}' &&
  export VLLM_URL='${VLLM_URL:-http://127.0.0.1:$VLLM_PORT/v1}' &&
  export EMBEDDING_DEVICE='${EMBEDDING_DEVICE:-cpu}' &&
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
  export GOOGLE_CLIENT_ID='${GOOGLE_CLIENT_ID:-}' &&
  export SESSION_SCOPE_SALT='${SESSION_SCOPE_SALT:-}' &&
  export HUGGING_FACE_HUB_TOKEN='${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}' &&
  export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
  export DJANGO_SUPERUSER_USERNAME='${DJANGO_SUPERUSER_USERNAME:-admin}' &&
  export DJANGO_SUPERUSER_PASSWORD='${DJANGO_SUPERUSER_PASSWORD:-admin123}' &&
  export DJANGO_SUPERUSER_EMAIL='${DJANGO_SUPERUSER_EMAIL:-admin@localhost}' &&
  for i in \$(seq 1 60); do
    PGPASSWORD=\"\${POSTGRES_PASSWORD}\" psql -h \"\${POSTGRES_HOST}\" -p \"\${POSTGRES_PORT}\" -U \"\${POSTGRES_USER}\" -d \"\${POSTGRES_DB}\" -c 'SELECT 1' >/dev/null 2>&1 && break
    sleep 1
  done &&
  python manage.py migrate --noinput &&
  python manage.py ensure_superuser &&
  exec gunicorn pastor_ai.wsgi:application --bind 0.0.0.0:${DJANGO_PORT} --workers 2 --timeout 1800 \
    >> '${LOG_DIR}/django.log' 2>&1
"
# Give migrate + gunicorn time on cold boot
for i in $(seq 1 40); do
  if curl -sf -o /dev/null "http://127.0.0.1:${DJANGO_PORT}/"; then
    log "Django on :${DJANGO_PORT} (migrations applied)"
    break
  fi
  sleep 2
  if [[ "$i" -eq 40 ]]; then
    warn "Django not responding yet — see ${LOG_DIR}/django.log"
  fi
done

# Persist DB to network volume + refresh dump every 5 minutes (survives migrate)
persist_postgres_dump
stop_screen pgdump
screen -dmS pgdump bash -c "
  while true; do
    sleep 300
    # shellcheck disable=SC1090
    source '${CONFIG_ENV}'
    export PGPASSWORD=\"\${POSTGRES_PASSWORD}\"
    DUMP='${WS}/postgres_data/\${POSTGRES_DB:-ai_db}.dump'
    mkdir -p '${WS}/postgres_data'
    pg_dump -h \"\${POSTGRES_HOST:-127.0.0.1}\" -p \"\${POSTGRES_PORT:-5432}\" \
      -U \"\${POSTGRES_USER:-pastor}\" -Fc --no-owner \"\${POSTGRES_DB:-ai_db}\" \
      -f \"\${DUMP}.tmp\" 2>>'${LOG_DIR}/postgres_dump.log' && mv -f \"\${DUMP}.tmp\" \"\${DUMP}\"
  done
"
log "Postgres auto-dump every 5m → $(postgres_dump_path)"

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
    # Kill any leftover quick/named tunnel process so we don't keep an old URL.
    pkill -f 'cloudflared tunnel' 2>/dev/null || true
    : > "$LOG_DIR/cloudflared.log"
    TOKEN_FILE="${CLOUDFLARE_TUNNEL_TOKEN_FILE:-$WS/.cloudflared/tunnel.token}"
    PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-christianaiapophatictestdomain.com}"
    if [[ -f "$TOKEN_FILE" ]]; then
      # Named Cloudflare tunnel (custom domain) — preferred over quick tunnels.
      screen -dmS cloudflared bash -c \
        "cloudflared tunnel --no-autoupdate run --token \"\$(cat '${TOKEN_FILE}')\" >> '${LOG_DIR}/cloudflared.log' 2>&1"
      echo "https://${PUBLIC_DOMAIN}" > "$WS/public_url.txt"
      sleep 5
      if pgrep -f 'cloudflared tunnel' >/dev/null 2>&1; then
        log "Public URL (Cloudflare named tunnel): https://${PUBLIC_DOMAIN}"
      else
        warn "Named tunnel failed to start — see ${LOG_DIR}/cloudflared.log"
      fi
    else
      screen -dmS cloudflared bash -c \
        "cloudflared tunnel --url http://127.0.0.1:${DJANGO_PORT} >> '${LOG_DIR}/cloudflared.log' 2>&1"
      sleep 8
      URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" | head -1 || true)"
      if [[ -n "$URL" ]]; then
        echo "$URL" > "$WS/public_url.txt"
        log "Public URL (Cloudflare quick tunnel): $URL"
      else
        warn "Cloudflare URL not ready — check ${LOG_DIR}/cloudflared.log"
      fi
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
if vllm_healthy; then
  log "vLLM healthy on :${VLLM_PORT}"
else
  warn "First chat may take several minutes while the LLM loads into GPU memory."
  warn "Watch: tail -f ${LOG_DIR}/vllm.log"
fi
if [[ -f "$WS/runpod-docker-command.txt" ]]; then
  echo ""
  echo "Migrate tip: Pod Container Start Command must launch onboot (see $WS/runpod-docker-command.txt)"
fi
