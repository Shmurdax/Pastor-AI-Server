#!/usr/bin/env bash
# Smoke-test the configured RunPod Faster-Whisper /runsync endpoint.
# Usage: bash scripts/check_whisper.sh
# Optional: WHISPER_SMOKE_AUDIO_URL=https://...  WHISPER_MODEL=base
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

URL="$(whisper_runsync_url || true)"
KEY="$(vllm_resolved_api_key)"
if [[ -n "${WHISPER_API_KEY:-}" && "${WHISPER_API_KEY}" != *paste_here* ]]; then
  KEY="$WHISPER_API_KEY"
fi
MODEL="${WHISPER_MODEL:-base}"
AUDIO="${WHISPER_SMOKE_AUDIO_URL:-https://github.com/runpod-workers/sample-inputs/raw/main/audio/gettysburg.wav}"

if [[ -z "$URL" ]]; then
  echo "No Whisper serverless URL. Set RUNPOD_WHISPER_ENDPOINT_ID or WHISPER_URL." >&2
  exit 1
fi
if [[ -z "$KEY" ]]; then
  echo "No API key. Set RUNPOD_API_KEY or WHISPER_API_KEY." >&2
  exit 1
fi

echo "POST ${URL}"
echo "model=${MODEL} audio=${AUDIO}"
echo "(Cold start can take 1–3 minutes.)"
curl -sS --max-time 600 \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"input\":{\"audio\":\"${AUDIO}\",\"model\":\"${MODEL}\",\"transcription\":\"plain_text\"}}" \
  "$URL"
echo
