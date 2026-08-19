#!/usr/bin/env bash
# Persist sermon PDFs, ingested videos, and a Postgres dump on the RunPod network volume.
# Container-local /var/lib/postgresql and git-synced backend/app/uploads are wiped
# on pod recreate / install.sh rsync --delete. Keep durable data outside the repo tree.
#
# Live PGDATA cannot live on this volume (chown to user postgres is not permitted).
# The cluster stays on local disk; we pg_dump/pg_restore the app database onto
# /workspace/persistent so remigrations keep the document catalog and sermon links.
#
# Sourced by start.sh and install.sh. Expects: APP_DIR, log, warn.
# Optional: POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD.

PERSIST_ROOT="${PERSIST_ROOT:-/workspace/persistent}"
PERSIST_UPLOADS="${PERSIST_UPLOADS:-$PERSIST_ROOT/uploads/admin_ingestion}"
PERSIST_VIDEO_UPLOADS="${PERSIST_VIDEO_UPLOADS:-$PERSIST_ROOT/uploads/admin_video_ingestion}"
PERSIST_VIDEO_JOBS="${PERSIST_VIDEO_JOBS:-$PERSIST_ROOT/uploads/admin_video_ingestion_jobs}"
PERSIST_VIDEO_CHUNKS="${PERSIST_VIDEO_CHUNKS:-$PERSIST_ROOT/uploads/admin_video_ingestion_chunks}"
PERSIST_PG_ROOT="${PERSIST_PG_ROOT:-$PERSIST_ROOT/postgres}"
PERSIST_PG_DUMP="${PERSIST_PG_DUMP:-$PERSIST_PG_ROOT/ai_db.dump}"
PERSIST_RESTORE_MARKER="${PERSIST_RESTORE_MARKER:-/var/lib/postgresql/.pastor_ai_restored}"

detect_pg_version() {
  ls /usr/lib/postgresql 2>/dev/null | sort -V | tail -1
}

ensure_persistent_uploads() {
  local app_uploads="${APP_DIR}/uploads/admin_ingestion"
  local app_video_uploads="${APP_DIR}/uploads/admin_video_ingestion"
  local app_video_jobs="${APP_DIR}/uploads/admin_video_ingestion_jobs"
  local app_video_chunks="${APP_DIR}/uploads/admin_video_ingestion_chunks"
  mkdir -p "$PERSIST_UPLOADS" "$PERSIST_VIDEO_UPLOADS" "$PERSIST_VIDEO_JOBS" "$PERSIST_VIDEO_CHUNKS" "${APP_DIR}/uploads"
  chmod a+rX "$PERSIST_ROOT" "$PERSIST_ROOT/uploads" "$PERSIST_UPLOADS" "$PERSIST_VIDEO_UPLOADS" "$PERSIST_VIDEO_JOBS" "$PERSIST_VIDEO_CHUNKS" 2>/dev/null || true
  if [[ -d "$app_uploads" && ! -L "$app_uploads" ]]; then
    shopt -s nullglob
    local existing=("$app_uploads"/*)
    if ((${#existing[@]})); then
      log "Moving existing sermon PDFs into $PERSIST_UPLOADS"
      mv -n "${existing[@]}" "$PERSIST_UPLOADS/" 2>/dev/null || true
    fi
    rm -rf "$app_uploads"
  fi
  ln -sfn "$PERSIST_UPLOADS" "$app_uploads"
  log "Sermon PDFs persist at $PERSIST_UPLOADS"
  if [[ -d "$app_video_uploads" && ! -L "$app_video_uploads" ]]; then
    shopt -s nullglob
    local existing_videos=("$app_video_uploads"/*)
    if ((${#existing_videos[@]})); then
      log "Moving existing ingested videos into $PERSIST_VIDEO_UPLOADS"
      mv -n "${existing_videos[@]}" "$PERSIST_VIDEO_UPLOADS/" 2>/dev/null || true
    fi
    rm -rf "$app_video_uploads"
  fi
  ln -sfn "$PERSIST_VIDEO_UPLOADS" "$app_video_uploads"
  log "Ingested videos persist at $PERSIST_VIDEO_UPLOADS"
  if [[ -d "$app_video_jobs" && ! -L "$app_video_jobs" ]]; then
    shopt -s nullglob
    local existing_jobs=("$app_video_jobs"/*)
    if ((${#existing_jobs[@]})); then
      log "Moving existing video job staging into $PERSIST_VIDEO_JOBS"
      mv -n "${existing_jobs[@]}" "$PERSIST_VIDEO_JOBS/" 2>/dev/null || true
    fi
    rm -rf "$app_video_jobs"
  fi
  ln -sfn "$PERSIST_VIDEO_JOBS" "$app_video_jobs"
  log "Video ingest job staging persists at $PERSIST_VIDEO_JOBS"
  if [[ -d "$app_video_chunks" && ! -L "$app_video_chunks" ]]; then
    shopt -s nullglob
    local existing_chunks=("$app_video_chunks"/*)
    if ((${#existing_chunks[@]})); then
      log "Moving existing video upload chunks into $PERSIST_VIDEO_CHUNKS"
      mv -n "${existing_chunks[@]}" "$PERSIST_VIDEO_CHUNKS/" 2>/dev/null || true
    fi
    rm -rf "$app_video_chunks"
  fi
  ln -sfn "$PERSIST_VIDEO_CHUNKS" "$app_video_chunks"
  log "Video ingest chunk staging persists at $PERSIST_VIDEO_CHUNKS"
}

_pg_ready() {
  su -s /bin/bash postgres -c "psql -c 'SELECT 1'" >/dev/null 2>&1
}

_pg_doc_count() {
  local db="${POSTGRES_DB:-ai_db}"
  su -s /bin/bash postgres -c "psql -d '${db}' -tAc \"SELECT count(*) FROM core_ingesteddocument\"" 2>/dev/null | tr -d '[:space:]'
}

_pg_dump_app_db() {
  local db="${POSTGRES_DB:-ai_db}"
  mkdir -p "$PERSIST_PG_ROOT"
  chmod a+rX "$PERSIST_ROOT" "$PERSIST_PG_ROOT" 2>/dev/null || true
  local tmp="/tmp/pastor_ai_db.$$.dump"
  rm -f "$tmp"
  if ! su -s /bin/bash postgres -c "pg_dump -Fc --no-owner -d '${db}' -f '${tmp}'" 2>/dev/null; then
    rm -f "$tmp"
    return 1
  fi
  if [[ ! -s "$tmp" ]]; then
    rm -f "$tmp"
    return 1
  fi
  # Never replace a real catalog dump with an empty-database dump.
  local live_count
  live_count="$(_pg_doc_count || true)"
  if [[ -s "$PERSIST_PG_DUMP" && "${live_count:-0}" == "0" ]]; then
    warn "Skipping Postgres dump: live DB has 0 ingested documents but $PERSIST_PG_DUMP already exists"
    rm -f "$tmp"
    return 0
  fi
  cp -f "$tmp" "${PERSIST_PG_DUMP}.tmp"
  mv -f "${PERSIST_PG_DUMP}.tmp" "$PERSIST_PG_DUMP"
  chmod a+r "$PERSIST_PG_DUMP" 2>/dev/null || true
  rm -f "$tmp"
  return 0
}

dump_persistent_postgres() {
  if _pg_dump_app_db; then
    log "Wrote Postgres dump $PERSIST_PG_DUMP"
  else
    warn "Postgres dump failed"
  fi
}

start_postgres_dump_loop() {
  screen -S pgdump -X quit 2>/dev/null || true
  screen -dmS pgdump bash -c "
    while true; do
      sleep 60
      tmp=/tmp/pastor_ai_db.$$.dump
      rm -f \"\$tmp\"
      if su -s /bin/bash postgres -c \"pg_dump -Fc --no-owner -d '${POSTGRES_DB:-ai_db}' -f '\$tmp'\" >/dev/null 2>&1 \\
         && [ -s \"\$tmp\" ]; then
        live=\$(su -s /bin/bash postgres -c \"psql -d '${POSTGRES_DB:-ai_db}' -tAc \\\"SELECT count(*) FROM core_ingesteddocument\\\"\" 2>/dev/null | tr -d '[:space:]')
        if [ -s '${PERSIST_PG_DUMP}' ] && [ \"\${live:-0}\" = 0 ]; then
          rm -f \"\$tmp\"
          continue
        fi
        mkdir -p '${PERSIST_PG_ROOT}'
        cp -f \"\$tmp\" '${PERSIST_PG_DUMP}.tmp'
        mv -f '${PERSIST_PG_DUMP}.tmp' '${PERSIST_PG_DUMP}'
        chmod a+r '${PERSIST_PG_DUMP}' 2>/dev/null || true
      fi
      rm -f \"\$tmp\"
    done
  "
}

_restore_persistent_postgres() {
  local user="${POSTGRES_USER:-pastor}"
  local db="${POSTGRES_DB:-ai_db}"
  local restore_copy="/tmp/pastor_ai_restore.dump"

  if [[ ! -s "$PERSIST_PG_DUMP" ]]; then
    return 0
  fi
  if [[ -f "$PERSIST_RESTORE_MARKER" ]]; then
    log "Postgres catalog already restored this container (marker present)"
    return 0
  fi

  log "Restoring app database from $PERSIST_PG_DUMP"
  cp -f "$PERSIST_PG_DUMP" "$restore_copy"
  chmod a+r "$restore_copy"

  # Custom-format restore: warnings from --clean on an empty DB are expected.
  su -s /bin/bash postgres -c "pg_restore --no-owner --role='${user}' --clean --if-exists -d '${db}' '${restore_copy}'" \
    >/dev/null 2>&1 || su -s /bin/bash postgres -c "pg_restore --no-owner --role='${user}' -d '${db}' '${restore_copy}'" \
    >/dev/null 2>&1 || true
  rm -f "$restore_copy"

  local live_count
  live_count="$(_pg_doc_count || true)"
  if [[ -n "$live_count" ]]; then
    touch "$PERSIST_RESTORE_MARKER" 2>/dev/null || true
    log "Restored ingested document catalog (${live_count} documents)"
    return 0
  fi
  warn "pg_restore did not recreate core_ingesteddocument — dump left untouched for retry"
  return 1
}

ensure_persistent_postgres() {
  local ver
  ver="$(detect_pg_version)"
  if [[ -z "$ver" ]]; then
    warn "PostgreSQL binaries missing — cannot persist database"
    return 1
  fi

  local conf="/etc/postgresql/${ver}/main/postgresql.conf"
  local default_data="/var/lib/postgresql/${ver}/main"
  mkdir -p "$PERSIST_PG_ROOT"
  chmod a+rX "$PERSIST_ROOT" "$PERSIST_PG_ROOT" 2>/dev/null || true

  # Never point live PGDATA at the network volume (chown to postgres fails).
  if [[ -f "$conf" ]]; then
    sed -i -E "s|^[[:space:]]*#?[[:space:]]*data_directory[[:space:]]*=.*|data_directory = '${default_data}'|" "$conf"
  fi

  pg_ctlcluster "$ver" main stop --force 2>/dev/null || service postgresql stop 2>/dev/null || true
  sleep 1
  pg_ctlcluster "$ver" main start 2>/dev/null || service postgresql start 2>/dev/null || true
  sleep 2
  if ! _pg_ready; then
    warn "Postgres did not become ready on local data directory"
    return 1
  fi
  log "Postgres running on local cluster (PG ${ver})"

  local user="${POSTGRES_USER:-pastor}"
  local db="${POSTGRES_DB:-ai_db}"
  local pass="${POSTGRES_PASSWORD:-}"
  if [[ -n "$user" && -n "$db" ]]; then
    su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${user}'\"" 2>/dev/null | grep -q 1 \
      || su -s /bin/bash postgres -c "psql -c \"CREATE USER ${user} WITH PASSWORD '${pass}' CREATEDB;\"" 2>/dev/null || true
    su -s /bin/bash postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${db}'\"" 2>/dev/null | grep -q 1 \
      || su -s /bin/bash postgres -c "psql -c \"CREATE DATABASE ${db} OWNER ${user};\"" 2>/dev/null || true
  fi

  _restore_persistent_postgres || true
  dump_persistent_postgres
  start_postgres_dump_loop
}
