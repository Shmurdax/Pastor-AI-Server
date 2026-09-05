#!/usr/bin/env bash
# vLLM local vs RunPod Serverless helpers. Sourced by install.sh and start.sh.
# Does not start processes; only resolves URLs/keys and whether this host
# should run a local OpenAI-compatible vLLM server.

_vllm_lc() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

vllm_cpu_only_pod() {
  local mode
  mode="$(_vllm_lc "${VLLM_MODE:-}")"
  case "$mode" in
    serverless|remote|cpu) return 0 ;;
  esac
  [[ "${CPU_ONLY:-0}" == "1" ]]
}

vllm_url_is_local() {
  local url="${1:-}"
  [[ "$url" =~ ^https?://(127\.0\.0\.1|localhost|\[::1\]|vllm)(:|/|$) ]]
}

vllm_resolved_url() {
  local id url
  id="${RUNPOD_VLLM_ENDPOINT_ID:-}"
  id="${id#"${id%%[![:space:]]*}"}"
  id="${id%"${id##*[![:space:]]}"}"
  if [[ -n "$id" ]]; then
    printf '%s\n' "https://api.runpod.ai/v2/${id}/openai/v1"
    return 0
  fi
  url="${VLLM_URL:-http://127.0.0.1:${VLLM_PORT:-8010}/v1}"
  url="${url%/}"
  if [[ "$url" =~ ^https://api\.runpod\.ai/v2/[^/]+$ ]]; then
    printf '%s\n' "${url}/openai/v1"
    return 0
  fi
  printf '%s\n' "$url"
}

vllm_resolved_api_key() {
  local key="${VLLM_API_KEY:-${RUNPOD_API_KEY:-}}"
  case "$key" in
    ""|*paste_here*|not-needed|EMPTY) printf '' ;;
    *) printf '%s' "$key" ;;
  esac
}

# True when this machine should start python -m vllm.entrypoints.openai.api_server.
vllm_use_local_server() {
  vllm_cpu_only_pod && return 1
  [[ -n "${RUNPOD_VLLM_ENDPOINT_ID:-}" ]] && return 1
  vllm_url_is_local "$(vllm_resolved_url)"
}

whisper_runsync_url() {
  local id url
  id="${RUNPOD_WHISPER_ENDPOINT_ID:-}"
  id="${id#"${id%%[![:space:]]*}"}"
  id="${id%"${id##*[![:space:]]}"}"
  if [[ -n "$id" ]]; then
    printf '%s\n' "https://api.runpod.ai/v2/${id}/runsync"
    return 0
  fi
  url="${WHISPER_URL:-}"
  url="${url%/}"
  [[ -z "$url" ]] && return 0
  if [[ "$url" == */runsync ]]; then
    printf '%s\n' "$url"
  elif [[ "$url" == */run ]]; then
    printf '%s\n' "${url}sync"
  elif [[ "$url" =~ ^https://api\.runpod\.ai/v2/[^/]+$ ]]; then
    printf '%s\n' "${url}/runsync"
  else
    printf '%s\n' "$url"
  fi
}

whisper_is_remote() {
  local mode
  mode="$(_vllm_lc "${WHISPER_MODE:-}")"
  case "$mode" in
    serverless|remote|gpu) return 0 ;;
  esac
  [[ -n "${RUNPOD_WHISPER_ENDPOINT_ID:-}" ]] && return 0
  [[ "$(whisper_runsync_url)" == https://api.runpod.ai/* ]] && return 0
  return 1
}

vllm_upsert_config() {
  local config="${1:-}"
  local key="$2"
  local val="${3:-}"
  [[ -n "$config" && -f "$config" && -n "$key" ]] || return 0
  [[ -z "$val" ]] && return 0
  case "$val" in
    *paste_here*|hf_paste_here) return 0 ;;
  esac
  if grep -q "^${key}=" "$config" 2>/dev/null; then
    local esc
    esc="$(printf '%s' "$val" | sed -e 's/[\\/&]/\\&/g')"
    sed -i "s|^${key}=.*|${key}=${esc}|" "$config"
  else
    echo "${key}=${val}" >> "$config"
  fi
}

# Point config.env at the serverless OpenAI URL when this host is a CPU web pod.
vllm_apply_config() {
  local config="${1:-}"
  local url key
  [[ -n "$config" && -f "$config" ]] || return 0
  url="$(vllm_resolved_url)"
  key="$(vllm_resolved_api_key)"
  if ! vllm_use_local_server; then
    vllm_upsert_config "$config" VLLM_MODE "${VLLM_MODE:-serverless}"
    vllm_upsert_config "$config" VLLM_URL "$url"
    [[ "${CPU_ONLY:-0}" == "1" ]] && vllm_upsert_config "$config" CPU_ONLY 1
    [[ -n "${RUNPOD_VLLM_ENDPOINT_ID:-}" ]] && \
      vllm_upsert_config "$config" RUNPOD_VLLM_ENDPOINT_ID "${RUNPOD_VLLM_ENDPOINT_ID}"
    [[ -n "$key" ]] && vllm_upsert_config "$config" RUNPOD_API_KEY "$key"
    [[ -n "${VLLM_API_KEY:-}" ]] && vllm_upsert_config "$config" VLLM_API_KEY "${VLLM_API_KEY}"
    vllm_upsert_config "$config" WHISPER_DEVICE "${WHISPER_DEVICE:-cpu}"
    if [[ -z "${CHAT_TIMEOUT_S:-}" ]] || awk "BEGIN{exit !(${CHAT_TIMEOUT_S:-0} < 600)}"; then
      vllm_upsert_config "$config" CHAT_TIMEOUT_S 600
    fi
  fi
  if whisper_is_remote; then
    vllm_upsert_config "$config" WHISPER_MODE "${WHISPER_MODE:-serverless}"
    vllm_upsert_config "$config" WHISPER_URL "$(whisper_runsync_url)"
    [[ -n "${RUNPOD_WHISPER_ENDPOINT_ID:-}" ]] && \
      vllm_upsert_config "$config" RUNPOD_WHISPER_ENDPOINT_ID "${RUNPOD_WHISPER_ENDPOINT_ID}"
  fi
}
