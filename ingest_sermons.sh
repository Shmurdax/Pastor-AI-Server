#!/usr/bin/env bash
# Ingest converted_markdown sermons into Qdrant collection sermon_brain.
# Usage: bash /workspace/pastor-ai/ingest_sermons.sh
set -euo pipefail

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
APP_DIR="${APP_DIR:-$WS/backend/app}"
VENV_DIR="${VENV_DIR:-$WS/venv}"
LOG_DIR="${LOG_DIR:-$WS/logs}"
CONFIG_ENV="${CONFIG_ENV:-$WS/config.env}"

[[ -f "$CONFIG_ENV" ]] && { set -a; # shellcheck disable=SC1090
  source "$CONFIG_ENV"; set +a; }

[[ -x "$VENV_DIR/bin/python" ]] || { echo "Missing venv at $VENV_DIR"; exit 1; }
[[ -f "$APP_DIR/ingest_qdrant.py" ]] || { echo "Missing $APP_DIR/ingest_qdrant.py"; exit 1; }

# Ensure Qdrant is up
if ! curl -sf "http://127.0.0.1:${QDRANT_PORT:-6333}/" >/dev/null \
   && ! curl -sf "http://127.0.0.1:${QDRANT_PORT:-6333}/readyz" >/dev/null; then
  echo "Qdrant not reachable — start it with: bash $WS/start.sh"
  exit 1
fi

mkdir -p "$LOG_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
export HF_HOME="${HF_HOME:-$WS/hf_cache}"
export HF_HUB_ENABLE_HF_TRANSFER=0
export TRANSFORMERS_CACHE="${HF_HOME}"

cd "$APP_DIR"
echo "=== Ingest starting $(date -Iseconds) ===" | tee -a "$LOG_DIR/ingest.log"
python -u ingest_qdrant.py 2>&1 | tee -a "$LOG_DIR/ingest.log"
echo "=== Ingest finished $(date -Iseconds) ===" | tee -a "$LOG_DIR/ingest.log"

curl -sf "http://127.0.0.1:${QDRANT_PORT:-6333}/collections/sermon_brain" \
  | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',{}); print('sermon_brain points:', r.get('points_count'), 'status:', r.get('status'))"
