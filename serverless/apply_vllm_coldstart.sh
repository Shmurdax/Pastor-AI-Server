#!/usr/bin/env bash
# Apply cold-start tunings to the existing chat vLLM serverless endpoint.
# See serverless/apply_vllm_coldstart.py.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/serverless/apply_vllm_coldstart.py" "$@"
