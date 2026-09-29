#!/usr/bin/env bash
# Dry-run admin Document Ingestion for local .txt/.md transcripts.
#
# Uses the same cleanup, title, quote-chunk, and scripture-ref path as
# production Document Ingestion. Does not write Qdrant or the library PDF.
#
# Usage:
#   ./preview_document_ingest.sh seed/books/*.txt
#   ./preview_document_ingest.sh --query "who is Immanuel" path/to/Advent.txt
set -euo pipefail

WS="${PASTOR_AI_ROOT:-/workspace/pastor-ai}"
if [[ ! -d "$WS/backend/app" ]]; then
  WS="$(cd "$(dirname "$0")" && pwd)"
fi
APP_DIR="$WS/backend/app"
CONFIG_ENV="${CONFIG_ENV:-$WS/config.env}"

if [[ -f "$CONFIG_ENV" && -f "$WS/scripts/load_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$WS/scripts/load_env.sh"
  pastor_load_env_file "$CONFIG_ENV"
fi

if [[ -f "$WS/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$WS/venv/bin/activate"
elif [[ -f /workspace/venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source /workspace/venv/bin/activate
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pastor_ai.settings}"
export PYTHONPATH="${APP_DIR}${PYTHONPATH:+:$PYTHONPATH}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  else
    PYTHON_BIN=python
  fi
fi

if [[ -f "${APP_DIR}/manage.py" ]] && "$PYTHON_BIN" -c "import django" >/dev/null 2>&1; then
  cd "${APP_DIR}"
  exec "$PYTHON_BIN" manage.py preview_document_ingest "$@"
fi

exec "$PYTHON_BIN" -m core.preview_document_ingest "$@"
