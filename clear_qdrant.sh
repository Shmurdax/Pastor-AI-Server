#!/usr/bin/env bash
# Delete and recreate the Qdrant sermon collection at the configured vector size.
# Use after changing EMBEDDING_MODEL_NAME / QDRANT_VECTOR_SIZE (e.g. MiniLM 384 → BGE 768).
# Usage: bash /workspace/pastor-ai/clear_qdrant.sh
set -euo pipefail

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
APP_DIR="${APP_DIR:-$WS/backend/app}"
VENV_DIR="${VENV_DIR:-$WS/venv}"
CONFIG_ENV="${CONFIG_ENV:-$WS/config.env}"
QDRANT_PORT="${QDRANT_PORT:-6333}"

[[ -f "$CONFIG_ENV" ]] && { set -a; # shellcheck disable=SC1090
  source "$CONFIG_ENV"; set +a; }

QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:${QDRANT_PORT}}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-sermon_brain}"
QDRANT_VECTOR_SIZE="${QDRANT_VECTOR_SIZE:-768}"
EMBEDDING_MODEL_NAME="${EMBEDDING_MODEL_NAME:-BAAI/bge-base-en-v1.5}"

if ! curl -sf "${QDRANT_URL}/" >/dev/null \
   && ! curl -sf "${QDRANT_URL}/readyz" >/dev/null; then
  echo "Qdrant not reachable at ${QDRANT_URL} — start it with: bash $WS/start.sh"
  exit 1
fi

echo "Clearing Qdrant collection '${QDRANT_COLLECTION}' (vector dim=${QDRANT_VECTOR_SIZE}, model=${EMBEDDING_MODEL_NAME})"

if [[ -x "$VENV_DIR/bin/python" && -d "$APP_DIR" ]]; then
  # Prefer Django helpers so recreate uses the same size as chat/ingest.
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  cd "$APP_DIR"
  export QDRANT_URL QDRANT_COLLECTION QDRANT_VECTOR_SIZE EMBEDDING_MODEL_NAME
  python - <<'PY'
import os
from qdrant_client import QdrantClient
from core.qdrant_utils import get_collection_name, get_qdrant_url, get_vector_size, reset_sermon_collection

client = QdrantClient(url=get_qdrant_url())
reset_sermon_collection(client)
name = get_collection_name()
info = client.get_collection(name)
print(f"Recreated {name}: points={info.points_count} vector_size={get_vector_size()}")
PY
else
  # Fallback: HTTP delete only (collection is recreated on next ingest/chat ensure).
  code="$(curl -s -o /tmp/qdrant_clear_body.txt -w '%{http_code}' -X DELETE \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}")"
  if [[ "$code" != "200" && "$code" != "404" ]]; then
    echo "Failed to delete collection (HTTP ${code}): $(cat /tmp/qdrant_clear_body.txt)"
    exit 1
  fi
  echo "Deleted collection '${QDRANT_COLLECTION}' (HTTP ${code}). It will be recreated empty on next ingest."
fi

echo "Done. Re-ingest with: bash $WS/ingest_sermons.sh"
