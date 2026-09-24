# One short serverless completion for the dev rehearsal marker.
# Sets PASTOR_GPU_SMOKE=1 only when the endpoint returns text.
# Source this file.

pastor_serverless_gpu_smoke() {
  local endpoint key model url payload body
  PASTOR_GPU_SMOKE=0
  if [[ -n "${GPU_SMOKE_HOOK:-}" ]]; then
    "$GPU_SMOKE_HOOK"
    return 0
  fi
  endpoint="${RUNPOD_VLLM_ENDPOINT_ID:-}"
  key="${RUNPOD_API_KEY:-${VLLM_API_KEY:-}}"
  if [[ -z "$endpoint" || -z "$key" ]]; then
    echo "dev-pipeline: GPU smoke skipped (no serverless endpoint)"
    return 0
  fi
  model="${VLLM_MODEL:-christianai}"
  url="https://api.runpod.ai/v2/${endpoint}/openai/v1/chat/completions"
  payload="$(printf '{"model":"%s","messages":[{"role":"user","content":"Reply with ok"}],"max_tokens":8,"temperature":0}' "$model")"
  body="$(curl -sf --max-time "${GPU_SMOKE_TIMEOUT:-90}" \
    -H "Authorization: Bearer ${key}" \
    -H 'Content-Type: application/json' \
    -d "$payload" \
    "$url" || true)"
  if [[ "$body" == *'"content":"'* && "$body" != *'"content":""'* ]]; then
    PASTOR_GPU_SMOKE=1
    echo "dev-pipeline: serverless GPU smoke ok"
  else
    echo "dev-pipeline: serverless GPU smoke returned no text" >&2
  fi
  return 0
}
