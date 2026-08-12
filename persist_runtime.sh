#!/usr/bin/env bash
# Persist Postgres + sermon PDFs on the RunPod network volume.
# Container-local /var/lib/postgresql and git-synced backend/app/uploads are wiped
# on pod recreate / install.sh rsync --delete. Keep durable data outside the repo tree.
#
# Sourced by start.sh and install.sh. Expects: WS, APP_DIR, log, warn.

PERSIST_ROOT="${PERSIST_ROOT:-/workspace/persistent}"
PERSIST_UPLOADS="${PERSIST_UPLOADS:-$PERSIST_ROOT/uploads/admin_ingestion}"
PERSIST_PG_ROOT="${PERSIST_PG_ROOT:-$PERSIST_ROOT/postgres}"

detect_pg_version() {
  ls /usr/lib/postgresql 2>/dev/null | sort -V | tail -1
}

ensure_persistent_uploads() {
  local app_uploads="${APP_DIR}/uploads/admin_ingestion"
  mkdir -p "$PERSIST_UPLOADS" "${APP_DIR}/uploads"
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
}

ensure_persistent_postgres() {
  local ver
  ver="$(detect_pg_version)"
  if [[ -z "$ver" ]]; then
    warn "PostgreSQL binaries missing — cannot persist database"
    return 1
  fi

  local persist="$PERSIST_PG_ROOT/$ver"
  local conf="/etc/postgresql/${ver}/main/postgresql.conf"
  local default_data="/var/lib/postgresql/${ver}/main"

  mkdir -p "$persist"
  chown -R postgres:postgres "$PERSIST_PG_ROOT" 2>/dev/null || true

  pg_ctlcluster "$ver" main stop --force 2>/dev/null || service postgresql stop 2>/dev/null || true
  sleep 1
  rm -f "$persist/postmaster.pid" "$default_data/postmaster.pid" 2>/dev/null || true

  if [[ ! -f "$persist/PG_VERSION" ]]; then
    if [[ -f "$default_data/PG_VERSION" ]]; then
      log "Seeding persistent Postgres from container cluster → $persist"
      rsync -a "$default_data/" "$persist/"
    else
      log "Initializing persistent Postgres at $persist"
      su -s /bin/bash postgres -c "/usr/lib/postgresql/${ver}/bin/initdb -D '$persist'"
    fi
    chown -R postgres:postgres "$persist"
  else
    log "Using persistent Postgres data at $persist"
  fi

  if [[ -f "$conf" ]]; then
    if grep -qE '^[[:space:]]*#?[[:space:]]*data_directory[[:space:]]*=' "$conf"; then
      sed -i -E "s|^[[:space:]]*#?[[:space:]]*data_directory[[:space:]]*=.*|data_directory = '${persist}'|" "$conf"
    else
      echo "data_directory = '${persist}'" >> "$conf"
    fi
  else
    warn "Missing $conf — starting default cluster"
  fi

  pg_ctlcluster "$ver" main start 2>/dev/null || service postgresql start 2>/dev/null || true
  sleep 2
  if su -s /bin/bash postgres -c "psql -c 'SELECT 1'" >/dev/null 2>&1; then
    log "Postgres on persistent volume (PG ${ver})"
  else
    warn "Postgres did not become ready — see journalctl / ${LOG_DIR:-/tmp}/postgres"
  fi
}
