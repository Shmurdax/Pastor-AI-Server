#!/usr/bin/env bash
# Crawl thenordins.org + sister ministry sites into Qdrant sermon_brain.
# Usage: bash /workspace/pastor-ai/crawl_websites.sh
set -euo pipefail

WS="${PASTOR_AI_ROOT:-/workspace/pastor-ai}"
if [[ ! -d "$WS/backend/app" ]]; then
  WS="$(cd "$(dirname "$0")" && pwd)"
fi
APP_DIR="$WS/backend/app"
LOG_DIR="${LOG_DIR:-$WS/logs}"
mkdir -p "$LOG_DIR"

cd "$APP_DIR"
if [[ -f "$WS/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$WS/venv/bin/activate"
elif [[ -f /workspace/venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /workspace/venv/bin/activate
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pastor_ai.settings}"
export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
export QDRANT_COLLECTION="${QDRANT_COLLECTION:-sermon_brain}"

echo "=== Website crawl starting $(date -Iseconds) ===" | tee -a "$LOG_DIR/website_crawl.log"
python -u manage.py crawl_websites "$@" 2>&1 | tee -a "$LOG_DIR/website_crawl.log"
echo "=== Website crawl finished $(date -Iseconds) ===" | tee -a "$LOG_DIR/website_crawl.log"
