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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/scripts/load_env.sh"

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
pastor_load_env_file "$CONFIG_ENV"

mkdir -p "$LOG_DIR" "${QDRANT_STORAGE:-$WS/qdrant_storage}" "${HF_HOME:-$WS/hf_cache}"

QDRANT_BIN="${QDRANT_BIN:-/workspace/bin/qdrant}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
# Avoid 8001 — RunPod's host nginx often binds it and fools health checks.
VLLM_PORT="${VLLM_PORT:-8010}"
SEARCH_SIDECAR_PORT="${SEARCH_SIDECAR_PORT:-8012}"
DJANGO_PORT="${DJANGO_PORT:-8000}"
VLLM_MODEL="${VLLM_MODEL:-RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16}"
TUNNEL="${TUNNEL:-cloudflared}"

log()  { echo -e "\033[0;32m[✔]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
die()  { echo -e "\033[0;31m[✘]\033[0m $*" >&2; exit 1; }

# shellcheck disable=SC1091
source "$SCRIPT_DIR/persist_runtime.sh"
restore_workspace_from_persist || true
ensure_persistent_boot_bundle || true
# shellcheck source=/dev/null
source "$SCRIPT_DIR/scripts/git_channel.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "$SCRIPT_DIR/scripts/git_safe_directory.sh" 2>/dev/null || true
# shellcheck source=/dev/null
source "$SCRIPT_DIR/scripts/sync_git_channel.sh" 2>/dev/null || true
if declare -F pastor_record_running_git >/dev/null 2>&1; then
  pastor_record_running_git "$WS" || true
  pastor_warn_if_git_drift "$WS" || true
fi
ensure_django_admin_url "$CONFIG_ENV"
pastor_load_env_file "$CONFIG_ENV"
ensure_qdrant_binary || warn "Qdrant binary missing — collections will not load until it is restored"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/gpu_runtime.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/vllm_runtime.sh"
chat_apply_config "$CONFIG_ENV"
pastor_load_env_file "$CONFIG_ENV"
gpu_detect
VLLM_URL="$(vllm_resolved_url)"
VLLM_API_KEY="$(vllm_resolved_api_key)"
if whisper_is_remote; then
  WHISPER_URL="$(whisper_runsync_url)"
fi
if [[ "${GPU_IS_BLACKWELL:-0}" == "1" ]]; then
  log "GPU: ${GPU_NAME:-unknown} compute_cap=${GPU_COMPUTE_CAP:-?} MIG=${GPU_MIG_UUID:-none} ${GPU_MIG_GB:+${GPU_MIG_GB}GB}"
fi
if [[ "${CPU_ONLY:-0}" == "1" ]] || [[ "${WHISPER_FORCE_CPU:-0}" == "1" ]]; then
  WHISPER_DEVICE=cpu
elif [[ -n "${GPU_CUDA_VISIBLE:-}" ]]; then
  case "${WHISPER_DEVICE:-auto}" in
    cpu|auto|gpu|"") WHISPER_DEVICE=cuda ;;
  esac
else
  WHISPER_DEVICE="${WHISPER_DEVICE:-cpu}"
fi

stop_screen() { screen -S "$1" -X quit 2>/dev/null || true; }

vllm_healthy() {
  local body
  body="$(curl -sf --max-time 3 "http://127.0.0.1:${VLLM_PORT}/v1/models" 2>/dev/null || true)"
  [[ "$body" == *'"object"'* ]] || [[ "$body" == *'"data"'* ]]
}

vllm_running_util() {
  local pid args
  for pid in $(ps -eo pid,args | awk '/vllm.entrypoints.openai.api_server/ && $0 !~ /awk/ {print $1}'); do
    args="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
    if [[ "$args" == *"--gpu-memory-utilization"* ]]; then
      printf '%s\n' "$args" | sed -n 's/.*--gpu-memory-utilization[ =]\([0-9.][0-9.]*\).*/\1/p' | head -1
      return 0
    fi
  done
}

stop_vllm_process() {
  local pid
  stop_screen vllm
  for pid in $(ps -eo pid,args | awk '/vllm.entrypoints.openai.api_server/ && $0 !~ /awk/ {print $1}'); do
    kill "$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in $(ps -eo pid,args | awk '/vllm.entrypoints.openai.api_server/ && $0 !~ /awk/ {print $1}'); do
    kill -9 "$pid" 2>/dev/null || true
  done
}

wait_vllm_ready() {
  local i
  for i in $(seq 1 120); do
    if vllm_healthy; then
      return 0
    fi
    sleep 5
  done
  return 1
}

echo ""
echo "=== Pastor-AI start ==="
echo "Workspace: $WS"
echo ""

# Postgres lives on local disk; dump/restore onto the network volume (PGDATA chown fails there).
if ! command -v psql >/dev/null 2>&1; then
  warn "PostgreSQL missing — installing..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq postgresql postgresql-contrib >/dev/null || warn "postgres apt install failed"
fi
if ! command -v soffice >/dev/null 2>&1; then
  warn "LibreOffice missing — installing (needed for DOCX ingestion)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq libreoffice-writer >/dev/null || warn "LibreOffice apt install failed; DOCX ingest will use text fallback"
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg missing — installing (needed for Whisper video ingestion)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq ffmpeg >/dev/null || warn "ffmpeg apt install failed; video ingestion will not transcribe"
fi
ensure_persistent_postgres || service postgresql start 2>/dev/null || true
# Schema must exist before the git seed dump (data-only) can load on a new volume.
if [[ -x "${VENV_DIR}/bin/python" && -f "${APP_DIR}/manage.py" ]]; then
  ( source "${VENV_DIR}/bin/activate" && cd "${APP_DIR}" && python manage.py migrate --noinput ) \
    >/dev/null 2>&1 || true
fi
restore_seed_ingested_catalog || true
_reset_postgres_id_sequences || true
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

# vLLM — local GPU process, or skip when Django calls RunPod Serverless.
# Full GPUs also run one sermon-search process, so vLLM keeps about 8GB free.
GPU_SEARCH_LOCAL=0
if vllm_use_local_server; then
  GPU_SEARCH_LOCAL=1
fi
GPU_SEARCH_SIDECAR=0
if gpu_search_sidecar_wanted; then
  GPU_SEARCH_SIDECAR=1
fi
SEARCH_SIDECAR_URL=""

if ! vllm_use_local_server; then
  stop_screen vllm
  log "Skipping local vLLM — using ${VLLM_URL}"
  if [[ -z "${VLLM_API_KEY}" ]]; then
    warn "VLLM_API_KEY / RUNPOD_API_KEY missing — serverless chat will 401 until you set it in tokens.env"
  fi
  if vllm_url_is_local "$VLLM_URL"; then
    warn "Serverless/CPU mode but VLLM_URL is still local (${VLLM_URL}). Set RUNPOD_VLLM_ENDPOINT_ID or VLLM_URL in tokens.env"
  fi
else
  GPU_UTIL="${VLLM_GPU_MEM_UTIL:-}"
  DEFAULT_UTIL="$(gpu_default_vllm_mem_util)"
  if [[ -z "$GPU_UTIL" ]]; then
    GPU_UTIL="$DEFAULT_UTIL"
  elif [[ "${GPU_IS_24GB_MIG:-0}" == "1" ]] && awk "BEGIN{exit !($GPU_UTIL > $DEFAULT_UTIL)}"; then
    log "Capping vLLM gpu-memory-utilization at ${DEFAULT_UTIL} for 24GB MIG (Whisper headroom)"
    GPU_UTIL="$DEFAULT_UTIL"
  fi
  if [[ "$GPU_SEARCH_SIDECAR" == "1" ]] && awk "BEGIN{exit !(${GPU_UTIL} > 0.80)}"; then
    log "Capping vLLM gpu-memory-utilization at 0.80 (was ${GPU_UTIL}) so sermon search can use the GPU"
    GPU_UTIL="0.80"
  fi
  RUNNING_UTIL="$(vllm_running_util || true)"
  NEED_VLLM_START=0
  if ! vllm_healthy; then
    NEED_VLLM_START=1
  elif [[ -z "$RUNNING_UTIL" ]] || ! awk -v a="$RUNNING_UTIL" -v b="$GPU_UTIL" 'BEGIN{exit !(a+0 == b+0)}'; then
    log "Restarting vLLM so gpu-memory-utilization=${GPU_UTIL} (running ${RUNNING_UTIL:-unknown})"
    NEED_VLLM_START=1
  else
    log "vLLM already running on :${VLLM_PORT} at util ${RUNNING_UTIL}"
  fi
fi
if [[ "${NEED_VLLM_START:-0}" == "1" ]]; then
  [[ -x "$VENV_DIR/bin/python" ]] || die "venv missing — run install.sh"
  gpu_ensure_vllm_stack
  # Stop the old engine before measuring free memory. A running 0.90 util
  # looks like a full card even when this restart is what frees the headroom.
  stop_vllm_process
  FREE_MIB=""
  for _free_try in 1 2 3 4 5 6 7 8 9 10; do
    FREE_MIB="$(gpu_free_mib || true)"
    if [[ -z "${FREE_MIB}" || "${FREE_MIB}" -ge 8000 ]]; then
      break
    fi
    sleep 2
  done
  if [[ -n "${FREE_MIB}" && "${FREE_MIB}" -lt 8000 ]]; then
    warn "GPU has only ${FREE_MIB:-?} MiB free (need ~8GB+). Ghost VRAM from dead host processes?"
    warn "In RunPod: Stop this pod fully → wait 30s → Start again, then re-run start.sh"
  fi
  : > "${LOG_DIR}/vllm.log"
  HF_TOK="${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}"
  if [[ -z "$HF_TOK" || "$HF_TOK" == *paste* ]]; then
    warn "HF_TOKEN empty — gated model download will fail. Edit tokens.env && bash apply-tokens.sh"
  fi
  # Fine-tuned Qwen Christian LoRA (default) or plain VLLM_MODEL path
  LORA_DIR="${CHRISTIANAI_LORA_DIR:-$WS/christianai-lora}"
  BASE_MODEL="${CHRISTIANAI_BASE_VLLM:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
  SERVED_NAME="${VLLM_MODEL:-christianai}"
  MAX_LEN="${VLLM_MAX_MODEL_LEN:-32768}"
  CUDA_DEV_EXPORT=""
  if [[ -n "${GPU_CUDA_VISIBLE:-}" ]]; then
    CUDA_DEV_EXPORT="export CUDA_VISIBLE_DEVICES='${GPU_CUDA_VISIBLE}' &&"
  fi
  gpu_export_cuda_libs
  CUDA_LD_EXPORT=""
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    CUDA_LD_EXPORT="export LD_LIBRARY_PATH='${LD_LIBRARY_PATH}' &&"
  fi
  ENFORCE_EAGER=""
  ATTN_EXPORT=""
  if [[ "${GPU_IS_BLACKWELL:-0}" == "1" ]]; then
    # FlashInfer 0.6.x treats sm_120 as below sm75 and aborts graph capture.
    # FlashInfer 0.6.x JIT uses TORCH_CUDA_ARCH_LIST; empty/old lists fail sm_120 as "< sm75".
    ATTN_EXPORT="export VLLM_ATTENTION_BACKEND='${VLLM_ATTENTION_BACKEND:-TRITON_ATTN}' && export TORCH_CUDA_ARCH_LIST='${TORCH_CUDA_ARCH_LIST:-12.0}' && export VLLM_USE_FLASHINFER_SAMPLER=0 &&"
    if [[ "${VLLM_ENFORCE_EAGER:-1}" != "0" ]]; then
      ENFORCE_EAGER="--enforce-eager"
    fi
  elif [[ "${VLLM_ENFORCE_EAGER:-0}" == "1" ]]; then
    ENFORCE_EAGER="--enforce-eager"
  fi
  LORA_ARGS=""
  if [[ -f "$LORA_DIR/adapter_model.safetensors" ]]; then
    LORA_ARGS="--enable-lora --lora-modules ${SERVED_NAME}=${LORA_DIR} --max-lora-rank 16"
    log "vLLM using base ${BASE_MODEL} + LoRA ${LORA_DIR} as '${SERVED_NAME}' util=${GPU_UTIL}"
  else
    BASE_MODEL="${SERVED_NAME}"
    warn "LoRA missing at $LORA_DIR — starting base/model id only: $BASE_MODEL"
  fi
  screen -dmS vllm bash -c "
    source '${VENV_DIR}/bin/activate' &&
    ${CUDA_DEV_EXPORT}
    ${CUDA_LD_EXPORT}
    ${ATTN_EXPORT}
    export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
    export HUGGING_FACE_HUB_TOKEN='${HF_TOK}' &&
    export HF_TOKEN='${HF_TOK}' &&
    export HF_HUB_ENABLE_HF_TRANSFER=0 &&
    export FLASHINFER_DISABLE_VERSION_CHECK=1 &&
    python -m vllm.entrypoints.openai.api_server \
      --model '${BASE_MODEL}' \
      --served-model-name '${SERVED_NAME}' \
      ${LORA_ARGS} \
      --host 127.0.0.1 \
      --port ${VLLM_PORT} \
      --max-model-len ${MAX_LEN} \
      --gpu-memory-utilization ${GPU_UTIL} \
      --trust-remote-code \
      ${ENFORCE_EAGER} \
      >> '${LOG_DIR}/vllm.log' 2>&1
  "
  log "vLLM starting on :${VLLM_PORT} (first load downloads model — check ${LOG_DIR}/vllm.log)"
  if [[ "$GPU_SEARCH_SIDECAR" == "1" ]]; then
    if ! wait_vllm_ready; then
      warn "vLLM did not become ready — sermon search stays on CPU"
      GPU_SEARCH_SIDECAR=0
    fi
  fi
fi

# One GPU process for the same BGE embedder and reranker. Gunicorn stays on CPU.
if [[ "$GPU_SEARCH_SIDECAR" == "1" ]]; then
  if ! vllm_healthy; then
    warn "vLLM is not healthy — sermon search stays on CPU"
  else
    gpu_export_cuda_libs
    stop_screen search-sidecar
    for pid in $(ps -eo pid,args | awk '/run_search_sidecar/ && $0 !~ /awk/ {print $1}'); do
      kill "$pid" 2>/dev/null || true
    done
    sleep 1
    screen -dmS search-sidecar bash -c "
      source '${VENV_DIR}/bin/activate' &&
      cd '${APP_DIR}' &&
      export PASTOR_AI_ALLOW_GPU=1 &&
      export CUDA_VISIBLE_DEVICES='${GPU_CUDA_VISIBLE}' &&
      export LD_LIBRARY_PATH='${LD_LIBRARY_PATH:-}' &&
      export EMBEDDING_DEVICE=cuda &&
      export RERANK_DEVICE=cuda &&
      export SEARCH_TORCH_DTYPE='${SEARCH_TORCH_DTYPE:-float16}' &&
      export EMBEDDING_MODEL_NAME='${EMBEDDING_MODEL_NAME:-BAAI/bge-base-en-v1.5}' &&
      export RERANK_MODEL='${RERANK_MODEL:-BAAI/bge-reranker-v2-m3}' &&
      export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
      export HUGGING_FACE_HUB_TOKEN='${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}' &&
      export HF_TOKEN='${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}' &&
      export PYTHONUNBUFFERED=1 &&
      exec python -u manage.py run_search_sidecar --host 127.0.0.1 --port ${SEARCH_SIDECAR_PORT} \
        >> '${LOG_DIR}/search_sidecar.log' 2>&1
    "
    log "Sermon search sidecar starting on :${SEARCH_SIDECAR_PORT}"
    search_ready=0
    for _search_try in $(seq 1 60); do
      if curl -sf --max-time 2 "http://127.0.0.1:${SEARCH_SIDECAR_PORT}/health" | grep -q '"ok"'; then
        search_ready=1
        break
      fi
      sleep 5
    done
    if [[ "$search_ready" == "1" ]]; then
      SEARCH_SIDECAR_URL="http://127.0.0.1:${SEARCH_SIDECAR_PORT}"
      log "Sermon search on GPU at ${SEARCH_SIDECAR_URL}"
    else
      warn "GPU sermon search did not become healthy — chat will search on CPU. See ${LOG_DIR}/search_sidecar.log"
      stop_screen search-sidecar
    fi
  fi
else
  stop_screen search-sidecar
fi

# Gunicorn re-execs with an empty environment and reloads config.env.
# The shell export above is not enough for the chat workers to see the sidecar.
if [[ -n "${SEARCH_SIDECAR_URL}" ]]; then
  vllm_upsert_config "$CONFIG_ENV" SEARCH_SIDECAR_URL "$SEARCH_SIDECAR_URL"
  if [[ -n "${PERSIST_CONFIG:-}" && -f "${PERSIST_CONFIG}" ]]; then
    vllm_upsert_config "$PERSIST_CONFIG" SEARCH_SIDECAR_URL "$SEARCH_SIDECAR_URL"
  fi
elif [[ -f "$CONFIG_ENV" ]]; then
  grep -v '^SEARCH_SIDECAR_URL=' "$CONFIG_ENV" > "${CONFIG_ENV}.searchtmp" || true
  mv "${CONFIG_ENV}.searchtmp" "$CONFIG_ENV"
  if [[ -n "${PERSIST_CONFIG:-}" && -f "${PERSIST_CONFIG}" ]]; then
    grep -v '^SEARCH_SIDECAR_URL=' "$PERSIST_CONFIG" > "${PERSIST_CONFIG}.searchtmp" || true
    mv "${PERSIST_CONFIG}.searchtmp" "$PERSIST_CONFIG"
  fi
fi

# Development pods rewrite live keys to test values before Django listens.
if declare -F pastor_git_channel >/dev/null 2>&1 && [[ "$(pastor_git_channel "$WS")" == "development" ]]; then
  bash "$SCRIPT_DIR/scripts/isolate_dev_env.sh"
fi

# Django
[[ -f "$APP_DIR/manage.py" ]] || die "App missing at $APP_DIR"
ensure_persistent_uploads
export INGESTION_UPLOAD_DIR="${INGESTION_UPLOAD_DIR:-$PERSIST_UPLOADS}"
export VIDEO_INGESTION_UPLOAD_DIR="${VIDEO_INGESTION_UPLOAD_DIR:-$PERSIST_VIDEO_UPLOADS}"
export VIDEO_INGESTION_JOBS_DIR="${VIDEO_INGESTION_JOBS_DIR:-$PERSIST_VIDEO_JOBS}"
export VIDEO_INGESTION_CHUNKS_DIR="${VIDEO_INGESTION_CHUNKS_DIR:-$PERSIST_VIDEO_CHUNKS}"
FRONTEND_BUILD_DIR="$(resolve_frontend_build_dir "$FRONTEND_DIR")"
log "Flutter build dir: $FRONTEND_BUILD_DIR"
stop_screen django
# Gunicorn rewrites argv to "gunicorn: master [pastor_ai.wsgi:application]",
# so "gunicorn pastor_ai.wsgi" does not match a live master and stale workers
# keep serving old code on :8000.
pkill -9 -f 'pastor_ai.wsgi' 2>/dev/null || true
pkill -9 -f 'gunicorn:' 2>/dev/null || true
sleep 1
fuser -k "${DJANGO_PORT}/tcp" 2>/dev/null || true
sleep 1
screen -dmS django bash -c "
  source '${SCRIPT_DIR}/scripts/load_env.sh' &&
  pastor_load_env_file '${CONFIG_ENV}' &&
  source '${VENV_DIR}/bin/activate' &&
  cd '${APP_DIR}' &&
  export FRONTEND_BUILD_DIR='$(resolve_frontend_build_dir "$FRONTEND_DIR")' &&
  export QDRANT_URL='${QDRANT_URL:-http://127.0.0.1:$QDRANT_PORT}' &&
  export QDRANT_COLLECTION='${QDRANT_COLLECTION:-sermon_brain}' &&
  export VLLM_URL='${VLLM_URL:-http://127.0.0.1:$VLLM_PORT/v1}' &&
  export VLLM_MODEL='${VLLM_MODEL:-christianai}' &&
  export VLLM_API_KEY=\"\${VLLM_API_KEY:-${VLLM_API_KEY:-}}\" &&
  export RUNPOD_API_KEY=\"\${RUNPOD_API_KEY:-${RUNPOD_API_KEY:-}}\" &&
  export RUNPOD_VLLM_ENDPOINT_ID='${RUNPOD_VLLM_ENDPOINT_ID:-}' &&
  export VLLM_MODE='${VLLM_MODE:-}' &&
  export CPU_ONLY='${CPU_ONLY:-}' &&
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
  export GOOGLE_CLIENT_SECRET='${GOOGLE_CLIENT_SECRET:-}' &&
  export GOOGLE_REFRESH_TOKEN='${GOOGLE_REFRESH_TOKEN:-}' &&
  export GMAIL_SENDER='${GMAIL_SENDER:-}' &&
  export GMAIL_SERVICE_ACCOUNT_JSON='${GMAIL_SERVICE_ACCOUNT_JSON:-}' &&
  export GMAIL_SERVICE_ACCOUNT_FILE='${GMAIL_SERVICE_ACCOUNT_FILE:-}' &&
  export STRIPE_SECRET_KEY='${STRIPE_SECRET_KEY:-}' &&
  export STRIPE_PUBLISHABLE_KEY='${STRIPE_PUBLISHABLE_KEY:-}' &&
  export STRIPE_WEBHOOK_SECRET='${STRIPE_WEBHOOK_SECRET:-}' &&
  export STRIPE_PRICE_MONTHLY='${STRIPE_PRICE_MONTHLY:-}' &&
  export STRIPE_PRICE_YEARLY='${STRIPE_PRICE_YEARLY:-}' &&
  export PUBLIC_APP_URL='${PUBLIC_APP_URL:-}' &&
  export BILLING_MOCK_CHECKOUT='${BILLING_MOCK_CHECKOUT:-}' &&
  export MAILCHIMP_API_KEY='${MAILCHIMP_API_KEY:-}' &&
  export MAILCHIMP_AUDIENCE_ID='${MAILCHIMP_AUDIENCE_ID:-}' &&
  export EMAIL_HOST='${EMAIL_HOST:-}' &&
  export EMAIL_PORT='${EMAIL_PORT:-587}' &&
  export EMAIL_HOST_USER='${EMAIL_HOST_USER:-}' &&
  export EMAIL_HOST_PASSWORD='${EMAIL_HOST_PASSWORD:-}' &&
  export EMAIL_USE_TLS='${EMAIL_USE_TLS:-true}' &&
  export DEFAULT_FROM_EMAIL='$(pastor_escape_sq "${DEFAULT_FROM_EMAIL:-}")' &&
  export SESSION_SCOPE_SALT='${SESSION_SCOPE_SALT:-}' &&
  export HUGGING_FACE_HUB_TOKEN='${HUGGING_FACE_HUB_TOKEN:-${HF_TOKEN:-}}' &&
  export HF_HOME='${HF_HOME:-$WS/hf_cache}' &&
  export DJANGO_SUPERUSER_USERNAME='${DJANGO_SUPERUSER_USERNAME:-admin}' &&
  export DJANGO_SUPERUSER_PASSWORD='${DJANGO_SUPERUSER_PASSWORD:-admin123}' &&
  export DJANGO_SUPERUSER_EMAIL='${DJANGO_SUPERUSER_EMAIL:-admin@localhost}' &&
  export DJANGO_ADMIN_URL='${DJANGO_ADMIN_URL:-rB4zKwO2wTBCD3pAxRIdTWsvw0w8}' &&
  # Gunicorn stays off the GPU. Sermon embed + rerank go through SEARCH_SIDECAR_URL.
  export CUDA_VISIBLE_DEVICES='' &&
  export EMBEDDING_DEVICE='${EMBEDDING_DEVICE:-cpu}' &&
  export SEARCH_SIDECAR_URL='${SEARCH_SIDECAR_URL:-}' &&
  export RERANK_MODEL='${RERANK_MODEL:-BAAI/bge-reranker-v2-m3}' &&
  export EMBEDDING_MODEL_NAME='${EMBEDDING_MODEL_NAME:-BAAI/bge-base-en-v1.5}' &&
  export QDRANT_VECTOR_SIZE='${QDRANT_VECTOR_SIZE:-768}' &&
  export INGESTION_UPLOAD_DIR='${INGESTION_UPLOAD_DIR:-$PERSIST_UPLOADS}' &&
  export VIDEO_INGESTION_UPLOAD_DIR='${VIDEO_INGESTION_UPLOAD_DIR:-$PERSIST_VIDEO_UPLOADS}' &&
  export VIDEO_INGESTION_JOBS_DIR='${VIDEO_INGESTION_JOBS_DIR:-$PERSIST_VIDEO_JOBS}' &&
  export VIDEO_INGESTION_CHUNKS_DIR='${VIDEO_INGESTION_CHUNKS_DIR:-$PERSIST_VIDEO_CHUNKS}' &&
  export WHISPER_MODEL='${WHISPER_MODEL:-base}' &&
  export WHISPER_DEVICE='cpu' &&
  export WHISPER_MODE='${WHISPER_MODE:-}' &&
  export WHISPER_URL='${WHISPER_URL:-}' &&
  export RUNPOD_WHISPER_ENDPOINT_ID='${RUNPOD_WHISPER_ENDPOINT_ID:-}' &&
  export WHISPER_API_KEY=\"\${WHISPER_API_KEY:-${WHISPER_API_KEY:-}}\" &&
  export WHISPER_CACHE_DIR='${WHISPER_CACHE_DIR:-/workspace/persistent/whisper}' &&
  export PERSIST_PG_DUMP='${PERSIST_PG_DUMP}' &&
  export CHAT_MAX_HISTORY_CHARS='${CHAT_MAX_HISTORY_CHARS:-20000}' &&
  export CHAT_MAX_HISTORY_TURNS='${CHAT_MAX_HISTORY_TURNS:-10}' &&
  export CHAT_MAX_CONTEXT_CHARS='${CHAT_MAX_CONTEXT_CHARS:-40000}' &&
  export CHAT_MAX_TOKENS='${CHAT_MAX_TOKENS:-1024}' &&
  export CHAT_CONTEXT_WINDOW='${CHAT_CONTEXT_WINDOW:-32768}' &&
  export VLLM_MAX_MODEL_LEN='${VLLM_MAX_MODEL_LEN:-32768}' &&
  export CHAT_TIMEOUT_S='${CHAT_TIMEOUT_S:-360}' &&
  export RETRIEVAL_K='${RETRIEVAL_K:-24}' &&
  export RETRIEVAL_THRESHOLD='${RETRIEVAL_THRESHOLD:-0.8}' &&
  export RETRIEVAL_CANDIDATE_MULTIPLIER='${RETRIEVAL_CANDIDATE_MULTIPLIER:-8}' &&
  export RETRIEVAL_MAX_PER_SOURCE='${RETRIEVAL_MAX_PER_SOURCE:-4}' &&
  export RETRIEVAL_MAX_PER_BIBLE_BOOK='${RETRIEVAL_MAX_PER_BIBLE_BOOK:-2}' &&
  export RETRIEVAL_BIBLE_RATIO='${RETRIEVAL_BIBLE_RATIO:-0.40}' &&
  export RETRIEVAL_VIDEO_RATIO='${RETRIEVAL_VIDEO_RATIO:-0.45}' &&
  export RETRIEVAL_SOURCE_MIN='${RETRIEVAL_SOURCE_MIN:-3}' &&
  export RETRIEVAL_SOURCE_MAX='${RETRIEVAL_SOURCE_MAX:-5}' &&
  export VIDEO_TOPIC_METADATA_LLM='${VIDEO_TOPIC_METADATA_LLM:-1}' &&
  export INGEST_CHUNK_SIZE='${INGEST_CHUNK_SIZE:-1800}' &&
  export INGEST_CHUNK_OVERLAP='${INGEST_CHUNK_OVERLAP:-250}' &&
  export INGEST_QDRANT_UPSERT_BATCH='${INGEST_QDRANT_UPSERT_BATCH:-128}' &&
  python manage.py migrate --noinput &&
  python manage.py ensure_superuser &&
  exec gunicorn pastor_ai.wsgi:application --bind 0.0.0.0:${DJANGO_PORT} --worker-class gthread --threads 4 --workers 2 --timeout 1800 \
    >> '${LOG_DIR}/django.log' 2>&1
"
django_ready=0
for _django_try in $(seq 1 45); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${DJANGO_PORT}/api/auth/config/" || true)"
  if [[ "$code" == "200" ]]; then
    django_ready=1
    break
  fi
  sleep 2
done
if [[ "$django_ready" == "1" ]]; then
  log "Django on :${DJANGO_PORT}"
else
  warn "Django not responding yet — see ${LOG_DIR}/django.log"
fi

# Whisper media ingest must not run inside gunicorn — start.sh kills those workers.
# On GPU pods Whisper uses leftover MIG VRAM unless a serverless Whisper endpoint
# is configured. BGE embeddings stay on CPU.
stop_screen video-ingest
VIDEO_CUDA_EXPORT="export CUDA_VISIBLE_DEVICES=''"
if whisper_is_remote; then
  VIDEO_ALLOW_GPU="export PASTOR_AI_ALLOW_GPU=0"
  log "Video ingest will call serverless GPU Whisper at $(whisper_runsync_url)"
elif [[ -n "${GPU_CUDA_VISIBLE:-}" && "${WHISPER_DEVICE}" == "cuda" ]]; then
  VIDEO_CUDA_EXPORT="export CUDA_VISIBLE_DEVICES='${GPU_CUDA_VISIBLE}'"
  VIDEO_ALLOW_GPU="export PASTOR_AI_ALLOW_GPU=1"
else
  VIDEO_ALLOW_GPU="export PASTOR_AI_ALLOW_GPU=0"
  if vllm_cpu_only_pod; then
    warn "CPU pod has no RUNPOD_WHISPER_ENDPOINT_ID — video ingest will use local CPU Whisper (slow)"
  fi
fi
screen -dmS video-ingest bash -c "
  source '${SCRIPT_DIR}/scripts/load_env.sh'
  pastor_load_env_file '${CONFIG_ENV}'
  source '${VENV_DIR}/bin/activate'
  cd '${APP_DIR}'
  ${VIDEO_ALLOW_GPU}
  ${VIDEO_CUDA_EXPORT}
  export EMBEDDING_DEVICE='${EMBEDDING_DEVICE:-cpu}'
  export EMBEDDING_MODEL_NAME='${EMBEDDING_MODEL_NAME:-BAAI/bge-base-en-v1.5}'
  export QDRANT_VECTOR_SIZE='${QDRANT_VECTOR_SIZE:-768}'
  export QDRANT_URL='${QDRANT_URL:-http://127.0.0.1:$QDRANT_PORT}'
  export QDRANT_COLLECTION='${QDRANT_COLLECTION:-sermon_brain}'
  export INGESTION_UPLOAD_DIR='${INGESTION_UPLOAD_DIR:-$PERSIST_UPLOADS}'
  export VIDEO_INGESTION_UPLOAD_DIR='${VIDEO_INGESTION_UPLOAD_DIR:-$PERSIST_VIDEO_UPLOADS}'
  export VIDEO_INGESTION_JOBS_DIR='${VIDEO_INGESTION_JOBS_DIR:-$PERSIST_VIDEO_JOBS}'
  export VIDEO_INGESTION_CHUNKS_DIR='${VIDEO_INGESTION_CHUNKS_DIR:-$PERSIST_VIDEO_CHUNKS}'
  export WHISPER_MODEL='${WHISPER_MODEL:-base}'
  export WHISPER_DEVICE='${WHISPER_DEVICE}'
  export WHISPER_MODE='${WHISPER_MODE:-}'
  export WHISPER_URL='${WHISPER_URL:-}'
  export RUNPOD_WHISPER_ENDPOINT_ID='${RUNPOD_WHISPER_ENDPOINT_ID:-}'
  export WHISPER_API_KEY=\"\${WHISPER_API_KEY:-${WHISPER_API_KEY:-}}\"
  export RUNPOD_API_KEY=\"\${RUNPOD_API_KEY:-${RUNPOD_API_KEY:-}}\"
  export WHISPER_CACHE_DIR='${WHISPER_CACHE_DIR:-/workspace/persistent/whisper}'
  export PERSIST_PG_DUMP='${PERSIST_PG_DUMP}'
  export PYTHONUNBUFFERED=1
  exec python -u manage.py run_video_ingestion_worker >> '${LOG_DIR}/video_ingest_worker.log' 2>&1
"
sleep 1
screen -ls | grep -q 'video-ingest' && log "Video ingest worker on screen video-ingest" \
  || warn "Video ingest worker did not start — see ${LOG_DIR}/video_ingest_worker.log"

# Tunnel. Production uses a named Cloudflare tunnel; tokens.env may still say ngrok.
if [[ "${TUNNEL:-}" == "ngrok" ]] && ! command -v ngrok >/dev/null 2>&1; then
  warn "TUNNEL=ngrok but ngrok is not installed — using cloudflared"
  TUNNEL=cloudflared
fi
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
    if ! ensure_cloudflared_binary; then
      warn "Skipping Cloudflare tunnel — public hostname will return 1033 until cloudflared is installed"
    else
      stop_screen cloudflared
      # Kill any leftover quick/named tunnel process so we don't keep an old URL.
      pkill -f 'cloudflared tunnel' 2>/dev/null || true
      : > "$LOG_DIR/cloudflared.log"
      TOKEN_FILE="$(resolve_cloudflare_tunnel_token_file)"
      PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-christianaiapophatictestdomain.com}"
      if [[ -n "${TOKEN_FILE}" && -f "$TOKEN_FILE" ]]; then
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
if [[ -f "$WS/public_url.txt" ]]; then
  echo "Admin (private — share only with staff): $(cat "$WS/public_url.txt")/${DJANGO_ADMIN_URL}/"
fi
echo "Admin (local, private): http://127.0.0.1:${DJANGO_PORT}/${DJANGO_ADMIN_URL}/"
echo "Logs: $LOG_DIR/"
echo ""
if vllm_use_local_server; then
  warn "First chat may take several minutes while the LLM loads into GPU memory."
else
  warn "vLLM is remote (${VLLM_URL}). First chat after idle can take 1–3 minutes (serverless cold start)."
fi

# When onboot.sh is the RunPod start command it sets PASTOR_KEEP_ALIVE=1.
# Sleep here if we were exec'd as that command so the container does not exit.
if [[ "${PASTOR_KEEP_ALIVE:-}" == "1" ]]; then
  log "Keeping container alive (PASTOR_KEEP_ALIVE=1)"
  exec sleep infinity
fi
