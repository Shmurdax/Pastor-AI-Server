#!/usr/bin/env bash
# Ping the configured OpenAI-compatible vLLM endpoint (/v1/models).
# Usage: bash scripts/check_vllm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${WORKSPACE_ROOT:-$ROOT}"
if [[ -f "$WS/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$WS/config.env"
  set +a
fi
if [[ -f "$ROOT/vllm_runtime.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/vllm_runtime.sh"
else
  # shellcheck disable=SC1091
  source "$WS/vllm_runtime.sh"
fi

URL="$(vllm_resolved_url)"
KEY="$(vllm_resolved_api_key)"
echo "GET ${URL}/models"
if [[ -n "$KEY" ]]; then
  curl -sS --max-time 30 -H "Authorization: Bearer ${KEY}" "${URL}/models"
else
  curl -sS --max-time 30 "${URL}/models"
fi
echo
