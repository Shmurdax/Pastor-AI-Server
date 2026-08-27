#!/usr/bin/env bash
# RunPod container start command — reconnects Django, vLLM, and the named
# Cloudflare tunnel after a stop/start or remigration:
#   bash /workspace/pastor-ai/onboot.sh
# A copy is also kept at /workspace/persistent/onboot.sh.
set -euo pipefail

START_SH="${START_SH:-/workspace/pastor-ai/start.sh}"
if [[ ! -f "$START_SH" ]]; then
  echo "Missing $START_SH — clone/install Pastor-AI before using onboot.sh" >&2
  exit 1
fi
exec bash "$START_SH"
