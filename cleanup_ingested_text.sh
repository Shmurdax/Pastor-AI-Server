#!/usr/bin/env bash
# Structured cleanup helper for admin Document Ingestion text.
#
# Cleans extracted sermon/Bible text the same way the injection admin pipeline
# does before chunking into Qdrant. Original PDFs under
# uploads/admin_ingestion are never modified (sermon library links keep working).
#
# Usage:
#   ./cleanup_ingested_text.sh --demo
#   ./cleanup_ingested_text.sh --file /path/to/extracted.txt
#   ./cleanup_ingested_text.sh --file notes.md --markdown --write /tmp/cleaned.md
set -euo pipefail

WS="${PASTOR_AI_ROOT:-/workspace/pastor-ai}"
if [[ ! -d "$WS/backend/app" ]]; then
  WS="$(cd "$(dirname "$0")" && pwd)"
fi
APP_DIR="$WS/backend/app"
CONFIG_ENV="${CONFIG_ENV:-$WS/config.env}"

if [[ ! -f "${APP_DIR}/manage.py" ]]; then
  echo "error: manage.py not found at ${APP_DIR}/manage.py" >&2
  exit 1
fi

if [[ -f "$CONFIG_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV"
  set +a
fi

if [[ -f "$WS/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$WS/venv/bin/activate"
elif [[ -f /workspace/venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /workspace/venv/bin/activate
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pastor_ai.settings}"

cd "${APP_DIR}"
exec python manage.py cleanup_ingested_text "$@"
