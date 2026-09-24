#!/usr/bin/env bash
# One-way copy of production Postgres and Qdrant onto the development pod,
# then isolate the copy so it cannot reach production users.
#
#   bash scripts/sync_prod_data_to_dev.sh --source user@ssh.runpod.io
# Tests source this file with SYNC_SOURCE_ONLY=1.
set -euo pipefail

_sync_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$_sync_root/git_channel.sh"
# shellcheck source=/dev/null
source "$_sync_root/isolate_dev_env.sh"

sync_die() { echo "sync: $*" >&2; return 1; }

sync_assert_direction() {
  local src_channel="$1" dest_channel="$2" dest_pg="$3" dest_qdrant="$4"
  [[ "$src_channel" == "master" ]] || { sync_die "source channel must be master"; return 1; }
  [[ "$dest_channel" == "development" ]] || { sync_die "destination channel must be development"; return 1; }
  case "$dest_pg" in
    127.0.0.1|localhost|::1) ;;
    *) sync_die "destination POSTGRES_HOST must be loopback"; return 1 ;;
  esac
  case "$dest_qdrant" in
    *127.0.0.1*|*localhost*|*::1*) ;;
    *) sync_die "destination QDRANT_URL must be loopback"; return 1 ;;
  esac
}

sync_record_denylist_line() {
  local file="$1" kind="$2" value="$3"
  [[ -n "$value" ]] || return 0
  mkdir -p "$(dirname "$file")"
  touch "$file"
  grep -q -E "^${kind} ${value}$" "$file" || printf '%s %s\n' "$kind" "$value" >> "$file"
  chmod 600 "$file"
}

if [[ "${SYNC_SOURCE_ONLY:-0}" != "1" && "${BASH_SOURCE[0]}" == "$0" ]]; then
  SOURCE_HOST=""
  KEEP_DUMP=0
  WITH_VIDEOS=0
  REDACT_PEOPLE=1
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --source) SOURCE_HOST="$2"; shift 2 ;;
      --keep-dump) KEEP_DUMP=1; shift ;;
      --with-videos) WITH_VIDEOS=1; shift ;;
      --no-redact-people) REDACT_PEOPLE=0; shift ;;
      *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
  done
  [[ -n "$SOURCE_HOST" ]] || { echo "pass --source user@host" >&2; exit 2; }

  WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
  DEST_CHANNEL="$(pastor_git_channel "$WS")"
  # shellcheck disable=SC1091
  [[ -f "$WS/config.env" ]] && source "$WS/config.env"
  DEST_PG="${POSTGRES_HOST:-127.0.0.1}"
  DEST_QDRANT="${QDRANT_URL:-http://127.0.0.1:6333}"
  SRC_CHANNEL="$(ssh -o BatchMode=yes "$SOURCE_HOST" "tr -d '[:space:]' < /workspace/pastor-ai/.git_channel")"
  sync_assert_direction "$SRC_CHANNEL" "$DEST_CHANNEL" "$DEST_PG" "$DEST_QDRANT"

  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  REMOTE_DUMP="/tmp/ai_db-${STAMP}.dump"
  LOCAL_DUMP="/tmp/ai_db-${STAMP}.dump"
  ssh -o BatchMode=yes "$SOURCE_HOST" "umask 077 && su -s /bin/bash postgres -c \"pg_dump -Fc --no-owner -d ${POSTGRES_DB:-ai_db} -f ${REMOTE_DUMP}\""
  scp -o BatchMode=yes "$SOURCE_HOST:$REMOTE_DUMP" "$LOCAL_DUMP"
  ssh -o BatchMode=yes "$SOURCE_HOST" "rm -f '$REMOTE_DUMP'"

  # Record production integration ids seen in the source env, then refuse them on dev.
  DENY="$WS/.isolation_denylist"
  while read -r key value; do
    case "$key" in
      RUNPOD_VLLM_ENDPOINT_ID|RUNPOD_WHISPER_ENDPOINT_ID) sync_record_denylist_line "$DENY" endpoint "$value" ;;
      MAILCHIMP_AUDIENCE_ID) sync_record_denylist_line "$DENY" mailchimp_audience "$value" ;;
      VIMEO_FOLDER_ID) sync_record_denylist_line "$DENY" vimeo_folder "$value" ;;
    esac
  done < <(ssh -o BatchMode=yes "$SOURCE_HOST" "grep -E '^(RUNPOD_VLLM_ENDPOINT_ID|RUNPOD_WHISPER_ENDPOINT_ID|MAILCHIMP_AUDIENCE_ID|VIMEO_FOLDER_ID)=' /workspace/pastor-ai/tokens.env" || true)

  screen -S django -X quit >/dev/null 2>&1 || true
  su -s /bin/bash postgres -c "pg_restore --no-owner --clean --if-exists -d '${POSTGRES_DB:-ai_db}' '${LOCAL_DUMP}'" || true
  su -s /bin/bash postgres -c "psql -d '${POSTGRES_DB:-ai_db}' -v ON_ERROR_STOP=1 -f '${_sync_root}/scrub_dev_database.sql'"
  if [[ "$REDACT_PEOPLE" == "1" ]]; then
    su -s /bin/bash postgres -c "psql -d '${POSTGRES_DB:-ai_db}' -v ON_ERROR_STOP=1 -f '${_sync_root}/scrub_dev_people.sql'"
  fi

  QDRANT_PORT="${QDRANT_PORT:-6333}"
  ssh -o BatchMode=yes "$SOURCE_HOST" "curl -sf -X POST http://127.0.0.1:${QDRANT_PORT}/collections/sermon_brain/snapshots" > /tmp/qdrant-snap.json
  SNAP_NAME="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])' < /tmp/qdrant-snap.json)"
  ssh -o BatchMode=yes "$SOURCE_HOST" "curl -sf -o /tmp/${SNAP_NAME} http://127.0.0.1:${QDRANT_PORT}/collections/sermon_brain/snapshots/${SNAP_NAME} && rm -f /tmp/${SNAP_NAME}.done" || true
  scp -o BatchMode=yes "$SOURCE_HOST:/tmp/${SNAP_NAME}" "/tmp/${SNAP_NAME}"
  ssh -o BatchMode=yes "$SOURCE_HOST" "rm -f /tmp/${SNAP_NAME}"
  curl -sf -X PUT "http://127.0.0.1:${QDRANT_PORT}/collections/sermon_brain/snapshots/recover" \
    -H 'Content-Type: application/json' \
    -d "{\"location\":\"file:///tmp/${SNAP_NAME}\"}" >/dev/null
  rm -f "/tmp/${SNAP_NAME}"

  isolate_apply "$WS"
  if [[ "$KEEP_DUMP" == "1" ]]; then
    mkdir -p "${PERSIST_ROOT:-/workspace/persistent}/postgres"
    mv "$LOCAL_DUMP" "${PERSIST_ROOT:-/workspace/persistent}/postgres/dev-copy.dump"
    chmod 600 "${PERSIST_ROOT:-/workspace/persistent}/postgres/dev-copy.dump"
  else
    rm -f "$LOCAL_DUMP"
  fi
  if [[ "$WITH_VIDEOS" == "1" ]]; then
    echo "sync: --with-videos copies referenced upload files; run rsync of /workspace/persistent/uploads manually if this pod cannot see the source volume"
  fi
  echo "sync: development database isolated"
fi
