#!/usr/bin/env bash
# Persist sermon PDFs, ingested videos, a Postgres dump, and the Cloudflare
# named-tunnel token/binary on the RunPod network volume.
# Container-local /var/lib/postgresql and git-synced backend/app/uploads are wiped
# on pod recreate / install.sh rsync --delete. Keep durable data outside the repo tree.
#
# Live PGDATA cannot live on this volume (chown to user postgres is not permitted).
# The cluster stays on local disk; we pg_dump/pg_restore the app database onto
# /workspace/persistent so remigrations keep the document catalog and sermon links.
#
# Sourced by start.sh, install.sh, and apply-tokens.sh. Expects: APP_DIR, log, warn.
# Optional: POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD.

PERSIST_ROOT="${PERSIST_ROOT:-/workspace/persistent}"
PERSIST_UPLOADS="${PERSIST_UPLOADS:-$PERSIST_ROOT/uploads/admin_ingestion}"
PERSIST_VIDEO_UPLOADS="${PERSIST_VIDEO_UPLOADS:-$PERSIST_ROOT/uploads/admin_video_ingestion}"
PERSIST_VIDEO_JOBS="${PERSIST_VIDEO_JOBS:-$PERSIST_ROOT/uploads/admin_video_ingestion_jobs}"
PERSIST_VIDEO_CHUNKS="${PERSIST_VIDEO_CHUNKS:-$PERSIST_ROOT/uploads/admin_video_ingestion_chunks}"
PERSIST_PG_ROOT="${PERSIST_PG_ROOT:-$PERSIST_ROOT/postgres}"
PERSIST_PG_DUMP="${PERSIST_PG_DUMP:-$PERSIST_PG_ROOT/ai_db.dump}"
PERSIST_RESTORE_MARKER="${PERSIST_RESTORE_MARKER:-/var/lib/postgresql/.pastor_ai_restored}"
PERSIST_CLOUDFLARED="${PERSIST_CLOUDFLARED:-$PERSIST_ROOT/bin/cloudflared}"
WS_CLOUDFLARED="${WS_CLOUDFLARED:-/workspace/bin/cloudflared}"
CLOUDFLARED_RELEASE_URL="${CLOUDFLARED_RELEASE_URL:-https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64}"
PERSIST_TUNNEL_TOKEN="${PERSIST_TUNNEL_TOKEN:-$PERSIST_ROOT/.cloudflared/tunnel.token}"
PERSIST_BOOT="${PERSIST_BOOT:-$PERSIST_ROOT/boot}"
PERSIST_CONFIG="${PERSIST_CONFIG:-$PERSIST_ROOT/config.env}"
PERSIST_TOKENS="${PERSIST_TOKENS:-$PERSIST_ROOT/tokens.env}"
PERSIST_QDRANT_BIN="${PERSIST_QDRANT_BIN:-$PERSIST_ROOT/bin/qdrant}"
WS_QDRANT_BIN="${WS_QDRANT_BIN:-${QDRANT_BIN:-/workspace/bin/qdrant}}"
QDRANT_RELEASE_URL="${QDRANT_RELEASE_URL:-https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz}"
SEED_INGEST_DUMP="${SEED_INGEST_DUMP:-${WS:-/workspace/pastor-ai}/seed/ingested_catalog.dump}"
PERSIST_BOOT_SCRIPTS=(
  onboot.sh
  start.sh
  persist_runtime.sh
  gpu_runtime.sh
  vllm_runtime.sh
  apply-tokens.sh
  install.sh
)

# Published example path from older docs. Keep if already stored so staff
# bookmarks do not break, but never mint it for a blank install.
DJANGO_ADMIN_URL_DEFAULT="${DJANGO_ADMIN_URL_DEFAULT:-rB4zKwO2wTBCD3pAxRIdTWsvw0w8}"

_clean_django_admin_url() {
  local v="${1:-}"
  v="${v#/}"
  v="${v%/}"
  printf '%s' "$v" | tr -cd 'A-Za-z0-9'
}

_generate_django_admin_url() {
  openssl rand -hex 16
}

ensure_django_admin_url() {
  # Persist a private staff URL (not /admin/) into config.env so it survives restarts.
  local config="${1:-${CONFIG_ENV:-}}"
  local current
  current="$(_clean_django_admin_url "${DJANGO_ADMIN_URL:-}")"
  if [[ -z "$current" && -n "$config" && -f "$config" ]]; then
    current="$(_clean_django_admin_url "$(grep '^DJANGO_ADMIN_URL=' "$config" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")")"
  fi
  if [[ -z "$current" || "${current,,}" == "admin" ]]; then
    current="$(_generate_django_admin_url)"
  fi
  DJANGO_ADMIN_URL="$current"
  export DJANGO_ADMIN_URL
  if [[ -n "$config" && -f "$config" ]]; then
    if grep -q '^DJANGO_ADMIN_URL=' "$config" 2>/dev/null; then
      local existing
      existing="$(_clean_django_admin_url "$(grep '^DJANGO_ADMIN_URL=' "$config" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")")"
      if [[ -z "$existing" || "${existing,,}" == "admin" ]]; then
        sed -i "s|^DJANGO_ADMIN_URL=.*|DJANGO_ADMIN_URL=${current}|" "$config"
      fi
    else
      echo "DJANGO_ADMIN_URL=${current}" >> "$config"
    fi
  fi
}

warn_insecure_runtime_config() {
  local debug="${DJANGO_DEBUG:-false}"
  local cors="${DJANGO_CORS_ALLOW_ALL_ORIGINS:-false}"
  local session_secure="${DJANGO_SESSION_COOKIE_SECURE:-}"
  local csrf_secure="${DJANGO_CSRF_COOKIE_SECURE:-}"
  local mock="${BILLING_MOCK_CHECKOUT:-}"
  local pw="${DJANGO_SUPERUSER_PASSWORD:-}"
  if [[ "${debug,,}" == "true" ]]; then
    warn "DJANGO_DEBUG=true — Django will serve debug pages. Set DJANGO_DEBUG=false before production."
  fi
  if [[ "${cors,,}" == "true" ]]; then
    warn "DJANGO_CORS_ALLOW_ALL_ORIGINS=true — disable this for production (same-origin Flutter does not need it)."
  fi
  if [[ "${session_secure,,}" == "false" || "${csrf_secure,,}" == "false" ]]; then
    warn "Secure cookies are disabled. Set DJANGO_SESSION_COOKIE_SECURE=true and DJANGO_CSRF_COOKIE_SECURE=true behind HTTPS."
  fi
  if [[ -z "$pw" || "${pw,,}" == "admin123" ]]; then
    warn "Staff password is missing or is the published default. Set DJANGO_SUPERUSER_PASSWORD (12+) and DJANGO_SUPERUSER_RESET_PASSWORD=1."
  fi
  if [[ "${DJANGO_ADMIN_URL:-}" == "$DJANGO_ADMIN_URL_DEFAULT" ]]; then
    warn "DJANGO_ADMIN_URL is the documented example path. Generate a new one with: openssl rand -hex 16"
  fi
  if [[ -z "${PUBLIC_API_KEY:-}" ]]; then
    warn "PUBLIC_API_KEY is empty — chat/warmup are publicly callable (GPU spend). Optional: set a key if you want a shared-secret gate."
  fi
  if [[ -z "$mock" || "${mock,,}" == "true" || "${mock,,}" == "1" ]]; then
    if [[ "${debug,,}" == "true" || "${mock,,}" == "true" || "${mock,,}" == "1" ]]; then
      warn "Mock checkout may gift Premium without Stripe. Set BILLING_MOCK_CHECKOUT=false for production."
    fi
  fi
}

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

_copy_cloudflared_to() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp -f "$src" "$dest" && chmod +x "$dest"
}

# RunPod remigrations wipe /usr/local/bin. Keep a copy on the network volume and
# restore/install before starting the named tunnel (otherwise Cloudflare 1033).
ensure_cloudflared_binary() {
  local dest="/usr/local/bin/cloudflared"
  mkdir -p /usr/local/bin "$(dirname "$PERSIST_CLOUDFLARED")" /workspace/bin
  if ! command -v cloudflared >/dev/null 2>&1; then
    if [[ -x "$PERSIST_CLOUDFLARED" ]]; then
      _copy_cloudflared_to "$PERSIST_CLOUDFLARED" "$dest"
      log "Restored cloudflared from $PERSIST_CLOUDFLARED"
    elif [[ -x "$WS_CLOUDFLARED" ]]; then
      _copy_cloudflared_to "$WS_CLOUDFLARED" "$dest"
      log "Restored cloudflared from $WS_CLOUDFLARED"
    else
      warn "cloudflared missing — installing (required for the public Cloudflare hostname)"
      if curl -fL --retry 3 --retry-delay 2 -o "$dest" "$CLOUDFLARED_RELEASE_URL"; then
        chmod +x "$dest"
        log "cloudflared installed"
      else
        warn "cloudflared download failed — named tunnel will not start (Cloudflare 1033)"
        return 1
      fi
    fi
  fi
  local bin
  bin="$(command -v cloudflared || true)"
  [[ -n "$bin" ]] || return 1
  _copy_cloudflared_to "$bin" "$PERSIST_CLOUDFLARED" 2>/dev/null || true
  _copy_cloudflared_to "$bin" "$WS_CLOUDFLARED" 2>/dev/null || true
  return 0
}

_trim_tunnel_token() {
  local token="${1-}"
  token="${token//$'\r'/}"
  # trim leading/trailing whitespace including newlines
  token="${token#"${token%%[![:space:]]*}"}"
  token="${token%"${token##*[![:space:]]}"}"
  printf '%s' "$token"
}

_write_tunnel_token_file() {
  local dest="$1" token="$2"
  [[ -n "$dest" && -n "$token" ]] || return 1
  mkdir -p "$(dirname "$dest")"
  printf '%s\n' "$token" > "$dest"
  chmod 600 "$dest" 2>/dev/null || true
}

# Mirror the named-tunnel token onto the persistent volume and restore it after
# remigration. Prints the path start.sh should pass to cloudflared.
# Priority: CLOUDFLARE_TUNNEL_TOKEN env → $WS/.cloudflared/tunnel.token → persist copy.
resolve_cloudflare_tunnel_token_file() {
  local ws_root="${WS:-/workspace/pastor-ai}"
  local default_file="${CLOUDFLARE_TUNNEL_TOKEN_FILE:-$ws_root/.cloudflared/tunnel.token}"
  local persist_file="${PERSIST_TUNNEL_TOKEN}"
  mkdir -p "$(dirname "$default_file")" "$(dirname "$persist_file")"

  local token=""
  if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]]; then
    token="$(_trim_tunnel_token "$CLOUDFLARE_TUNNEL_TOKEN")"
  fi
  if [[ -z "$token" && -s "$default_file" ]]; then
    token="$(_trim_tunnel_token "$(cat "$default_file")")"
  fi
  if [[ -z "$token" && -s "$persist_file" ]]; then
    token="$(_trim_tunnel_token "$(cat "$persist_file")")"
    # stdout is the token path (captured by start.sh); keep restore notes on stderr.
    echo "[✔] Restored Cloudflare tunnel token from $persist_file" >&2
  fi
  if [[ -z "$token" ]]; then
    return 0
  fi

  # Always write both copies so a git-synced pastor-ai tree or a remigration
  # cannot leave the named tunnel with only one (wiped) location.
  _write_tunnel_token_file "$default_file" "$token"
  _write_tunnel_token_file "$persist_file" "$token"
  printf '%s\n' "$default_file"
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

# Data-only catalog from git (no users, sessions, chat, or tokens). Used when a
# new network volume has no /workspace/persistent/postgres/ai_db.dump yet.
# Requires Django migrations to have created the tables first.
restore_seed_ingested_catalog() {
  local seed="${SEED_INGEST_DUMP:-}"
  local persist_seed="${PERSIST_PG_ROOT}/ingested_catalog.dump"
  if [[ ! -s "$seed" && -s "$persist_seed" ]]; then
    seed="$persist_seed"
  fi
  if [[ -s "$seed" && ! -s "$persist_seed" ]]; then
    mkdir -p "$PERSIST_PG_ROOT"
    cp -f "$seed" "$persist_seed" 2>/dev/null || true
    chmod a+r "$persist_seed" 2>/dev/null || true
  fi
  [[ -s "$seed" ]] || return 0
  _pg_ready || return 0
  local live_count
  live_count="$(_pg_doc_count || true)"
  if [[ -n "$live_count" && "$live_count" != "0" ]]; then
    return 0
  fi
  local user="${POSTGRES_USER:-pastor}"
  local db="${POSTGRES_DB:-ai_db}"
  log "Restoring ingested catalog seed from $seed"
  su -s /bin/bash postgres -c "pg_restore --no-owner --role='${user}' --data-only --disable-triggers -d '${db}' '${seed}'" \
    >/dev/null 2>&1 || true
  live_count="$(_pg_doc_count || true)"
  if [[ -n "$live_count" && "$live_count" != "0" ]]; then
    log "Restored ingested catalog seed (${live_count} documents)"
    return 0
  fi
  warn "Seed catalog restore did not load core_ingesteddocument"
  return 1
}

_copy_secret_file() {
  local src="$1" dest="$2"
  [[ -s "$src" ]] || return 1
  mkdir -p "$(dirname "$dest")"
  cp -f "$src" "$dest"
  chmod 600 "$dest" 2>/dev/null || true
}

# Mirror config/tokens onto the network volume. Never print file contents.
mirror_runtime_secrets() {
  local ws_root="${WS:-/workspace/pastor-ai}"
  if [[ -s "$ws_root/config.env" ]]; then
    _copy_secret_file "$ws_root/config.env" "$PERSIST_CONFIG" || true
  fi
  if [[ -s "$ws_root/tokens.env" ]]; then
    _copy_secret_file "$ws_root/tokens.env" "$PERSIST_TOKENS" || true
  fi
}

ensure_persistent_boot_bundle() {
  local ws_root="${WS:-/workspace/pastor-ai}"
  mkdir -p "$PERSIST_BOOT" "$(dirname "$PERSIST_QDRANT_BIN")"
  local name src
  for name in "${PERSIST_BOOT_SCRIPTS[@]}"; do
    src="$ws_root/$name"
    if [[ -f "$src" ]]; then
      cp -a "$src" "$PERSIST_BOOT/$name"
      chmod +x "$PERSIST_BOOT/$name" 2>/dev/null || true
    fi
  done
  if [[ -f "$ws_root/onboot.sh" ]]; then
    cp -a "$ws_root/onboot.sh" "$PERSIST_ROOT/onboot.sh"
    chmod +x "$PERSIST_ROOT/onboot.sh" 2>/dev/null || true
  elif [[ -f "$PERSIST_BOOT/onboot.sh" ]]; then
    cp -a "$PERSIST_BOOT/onboot.sh" "$PERSIST_ROOT/onboot.sh"
    chmod +x "$PERSIST_ROOT/onboot.sh" 2>/dev/null || true
  fi
  if [[ -s "$ws_root/seed/ingested_catalog.dump" ]]; then
    mkdir -p "$PERSIST_PG_ROOT"
    cp -f "$ws_root/seed/ingested_catalog.dump" "$PERSIST_PG_ROOT/ingested_catalog.dump" 2>/dev/null || true
  fi
  mirror_runtime_secrets
  if [[ -x "${WS_QDRANT_BIN}" ]]; then
    cp -f "${WS_QDRANT_BIN}" "$PERSIST_QDRANT_BIN" 2>/dev/null || true
    chmod +x "$PERSIST_QDRANT_BIN" 2>/dev/null || true
  fi
}

restore_workspace_from_persist() {
  local ws_root="${WS:-/workspace/pastor-ai}"
  mkdir -p "$ws_root"
  local name
  for name in "${PERSIST_BOOT_SCRIPTS[@]}"; do
    if [[ ! -f "$ws_root/$name" && -f "$PERSIST_BOOT/$name" ]]; then
      cp -a "$PERSIST_BOOT/$name" "$ws_root/$name"
      chmod +x "$ws_root/$name" 2>/dev/null || true
      log "Restored $name from $PERSIST_BOOT"
    fi
  done
  if [[ ! -s "$ws_root/config.env" && -s "$PERSIST_CONFIG" ]]; then
    _copy_secret_file "$PERSIST_CONFIG" "$ws_root/config.env" || true
    log "Restored config.env from persistent volume"
  fi
  if [[ ! -s "$ws_root/tokens.env" && -s "$PERSIST_TOKENS" ]]; then
    _copy_secret_file "$PERSIST_TOKENS" "$ws_root/tokens.env" || true
    log "Restored tokens.env from persistent volume"
  fi
  if [[ ! -s "$ws_root/seed/ingested_catalog.dump" && -s "$PERSIST_PG_ROOT/ingested_catalog.dump" ]]; then
    mkdir -p "$ws_root/seed"
    cp -f "$PERSIST_PG_ROOT/ingested_catalog.dump" "$ws_root/seed/ingested_catalog.dump" 2>/dev/null || true
  fi
}

ensure_qdrant_binary() {
  local dest="${WS_QDRANT_BIN}"
  mkdir -p "$(dirname "$dest")" "$(dirname "$PERSIST_QDRANT_BIN")"
  if [[ ! -x "$dest" ]]; then
    if [[ -x "$PERSIST_QDRANT_BIN" ]]; then
      cp -f "$PERSIST_QDRANT_BIN" "$dest"
      chmod +x "$dest"
      log "Restored qdrant from $PERSIST_QDRANT_BIN"
    else
      warn "qdrant missing — downloading"
      local tmp
      tmp="$(mktemp -d)"
      if curl -fL --retry 3 --retry-delay 2 -o "$tmp/qdrant.tgz" "$QDRANT_RELEASE_URL"; then
        tar -xzf "$tmp/qdrant.tgz" -C "$tmp"
        if [[ -f "$tmp/qdrant" ]]; then
          mv -f "$tmp/qdrant" "$dest"
          chmod +x "$dest"
          log "qdrant installed"
        else
          warn "qdrant archive missing binary"
        fi
      else
        warn "qdrant download failed"
      fi
      rm -rf "$tmp"
    fi
  fi
  [[ -x "$dest" ]] || return 1
  cp -f "$dest" "$PERSIST_QDRANT_BIN" 2>/dev/null || true
  chmod +x "$PERSIST_QDRANT_BIN" 2>/dev/null || true
  return 0
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
