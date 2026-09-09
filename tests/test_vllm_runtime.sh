#!/usr/bin/env bash
# vLLM URL / serverless-mode helpers (no GPU required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/vllm_runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

unset RUNPOD_VLLM_ENDPOINT_ID VLLM_URL VLLM_MODE CPU_ONLY VLLM_API_KEY RUNPOD_API_KEY VLLM_PORT RUNPOD_WHISPER_ENDPOINT_ID WHISPER_URL WHISPER_MODE || true
VLLM_URL="http://127.0.0.1:8010/v1"
vllm_use_local_server || fail "localhost vLLM should start a local server"
vllm_url_is_local "$VLLM_URL" || fail "127.0.0.1 should be local"
vllm_cpu_only_pod && fail "default is not a CPU-only pod" || true

CPU_ONLY=1
vllm_cpu_only_pod || fail "CPU_ONLY=1 should be cpu-only"
vllm_use_local_server && fail "CPU_ONLY=1 must skip local vLLM" || true
unset CPU_ONLY

VLLM_MODE=serverless
vllm_use_local_server && fail "VLLM_MODE=serverless must skip local vLLM" || true
unset VLLM_MODE

VLLM_URL="http://vllm:8000/v1"
vllm_url_is_local "$VLLM_URL" || fail "docker hostname vllm should be local"

VLLM_URL="https://api.runpod.ai/v2/abc123/openai/v1"
vllm_url_is_local "$VLLM_URL" && fail "runpod URL must not be local" || true
vllm_use_local_server && fail "runpod URL must skip local vLLM" || true

unset VLLM_URL
RUNPOD_VLLM_ENDPOINT_ID="abc123"
[[ "$(vllm_resolved_url)" == "https://api.runpod.ai/v2/abc123/openai/v1" ]] \
  || fail "endpoint id url: $(vllm_resolved_url)"
vllm_use_local_server && fail "endpoint id must skip local vLLM" || true

VLLM_URL="https://api.runpod.ai/v2/xyz789"
unset RUNPOD_VLLM_ENDPOINT_ID
[[ "$(vllm_resolved_url)" == "https://api.runpod.ai/v2/xyz789/openai/v1" ]] \
  || fail "bare runpod url should append /openai/v1: $(vllm_resolved_url)"

RUNPOD_API_KEY="rp_live"
[[ "$(vllm_resolved_api_key)" == "rp_live" ]] || fail "api key"
VLLM_API_KEY="direct"
[[ "$(vllm_resolved_api_key)" == "direct" ]] || fail "VLLM_API_KEY should win"
RUNPOD_API_KEY="paste_here"
unset VLLM_API_KEY
[[ -z "$(vllm_resolved_api_key)" ]] || fail "placeholder api key should be empty"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
VLLM_URL=http://127.0.0.1:8010/v1
CHAT_TIMEOUT_S=360
EOF
CPU_ONLY=1
RUNPOD_VLLM_ENDPOINT_ID="ep9"
RUNPOD_API_KEY="rp_cfg"
VLLM_MODE=serverless
CHAT_TIMEOUT_S=360
vllm_apply_config "$TMP"
grep -q '^VLLM_URL=https://api.runpod.ai/v2/ep9/openai/v1$' "$TMP" || fail "config url not rewritten"
grep -q '^CHAT_TIMEOUT_S=600$' "$TMP" || fail "serverless timeout should bump to 600"
grep -q '^CHAT_MAX_HISTORY_CHARS=20000$' "$TMP" || fail "history chars should be upserted"
grep -q '^CHAT_MAX_HISTORY_TURNS=10$' "$TMP" || fail "history turns should be upserted"
grep -q '^CHAT_MAX_TOKENS=768$' "$TMP" || fail "max tokens should be upserted to ~1500 chars"
grep -q 'CHAT_MAX_HISTORY_TURNS' "$ROOT/start.sh" || fail "start.sh must export history turns"
grep -q 'chat_apply_config' "$ROOT/start.sh" || fail "start.sh must apply chat budget to config.env"
grep -q '^CPU_ONLY=1$' "$TMP" || fail "CPU_ONLY not written"
grep -q '^RUNPOD_API_KEY=rp_cfg$' "$TMP" || fail "api key not written"

unset RUNPOD_VLLM_ENDPOINT_ID VLLM_URL VLLM_MODE VLLM_API_KEY || true
CPU_ONLY=1
RUNPOD_WHISPER_ENDPOINT_ID="wh9"
WHISPER_MODE=serverless
vllm_apply_config "$TMP"
grep -q '^WHISPER_URL=https://api.runpod.ai/v2/wh9/runsync$' "$TMP" || fail "whisper url not written"
grep -q '^RUNPOD_WHISPER_ENDPOINT_ID=wh9$' "$TMP" || fail "whisper endpoint not written"
whisper_is_remote || fail "whisper_is_remote should be true with endpoint id"
[[ "$(whisper_runsync_url)" == "https://api.runpod.ai/v2/wh9/runsync" ]] || fail "whisper runsync url"

grep -q 'vllm_use_local_server' "$ROOT/start.sh" || fail "start.sh must skip local vLLM when remote"
grep -q 'RUNPOD_WHISPER_ENDPOINT_ID' "$ROOT/start.sh" || fail "start.sh must export whisper endpoint"
grep -A8 'dmS django' "$ROOT/start.sh" | grep -q 'CONFIG_ENV' \
  || fail "django screen must source config.env so RUNPOD_API_KEY reaches gunicorn"
grep -A40 'dmS django' "$ROOT/start.sh" | grep -Fq 'RUNPOD_API_KEY=\"\${RUNPOD_API_KEY' \
  || fail "django screen must keep sourced RUNPOD_API_KEY (not wipe it with an empty outer expansion)"
grep -A80 'dmS django' "$ROOT/start.sh" | grep -q 'RUNPOD_WHISPER_ENDPOINT_ID' \
  || fail "django screen must export RUNPOD_WHISPER_ENDPOINT_ID"
grep -A40 'dmS video-ingest' "$ROOT/start.sh" | grep -Fq 'RUNPOD_API_KEY=\"\${RUNPOD_API_KEY' \
  || fail "video-ingest screen must keep sourced RUNPOD_API_KEY"
grep -q 'vllm_runtime.sh' "$ROOT/install.sh" || fail "install.sh must ship vllm_runtime.sh"
grep -q 'CPU_ONLY' "$ROOT/install.sh" || fail "install.sh must support CPU_ONLY"

echo "OK vllm_runtime local vs serverless helpers"
