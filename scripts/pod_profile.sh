#!/usr/bin/env bash
# Detect how this Pastor-AI host is set up. Source this file.
#
#   channel  development | master
#   gpu      yes | no
#   vllm     local | serverless
#   tunnel   named | quick
#
# Production is the always-on GPU pod (local vLLM, named tunnel, channel master).
# Development is the CPU pod (serverless GPU, quick tunnel, channel development).

pastor_pod_ws() {
  printf '%s\n' "${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
}

pastor_has_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1
}

pastor_named_tunnel_present() {
  local ws f
  ws="$(pastor_pod_ws "${1:-}")"
  [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]] && return 0
  for f in \
    "${CLOUDFLARE_TUNNEL_TOKEN_FILE:-}" \
    "$ws/.cloudflared/tunnel.token" \
    "$ws/.cloudflared/tunnel.token.prd-copy" \
    "${PERSIST_ROOT:-/workspace/persistent}/.cloudflared/tunnel.token" \
    "${PERSIST_ROOT:-/workspace/persistent}/.cloudflared/tunnel.token.prd-copy"
  do
    [[ -n "$f" && -s "$f" ]] && return 0
  done
  return 1
}

pastor_vllm_mode_name() {
  local mode
  mode="$(printf '%s' "${VLLM_MODE:-}" | tr '[:upper:]' '[:lower:]')"
  case "$mode" in
    serverless|remote|cpu) printf 'serverless\n'; return ;;
    local) printf 'local\n'; return ;;
  esac
  if [[ "${CPU_ONLY:-0}" == "1" ]]; then
    printf 'serverless\n'
    return
  fi
  if pastor_has_gpu; then
    printf 'local\n'
  else
    printf 'serverless\n'
  fi
}

pastor_pod_profile_print() {
  local ws channel mode tunnel gpu
  ws="$(pastor_pod_ws "${1:-}")"
  # shellcheck source=/dev/null
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/git_channel.sh"
  channel="$(pastor_git_channel "$ws")"
  mode="$(pastor_vllm_mode_name)"
  if pastor_named_tunnel_present "$ws"; then
    tunnel=named
  else
    tunnel=quick
  fi
  if pastor_has_gpu; then
    gpu=yes
  else
    gpu=no
  fi
  printf 'channel=%s\n' "$channel"
  printf 'gpu=%s\n' "$gpu"
  printf 'vllm=%s\n' "$mode"
  printf 'tunnel=%s\n' "$tunnel"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  pastor_pod_profile_print "${1:-}"
fi
