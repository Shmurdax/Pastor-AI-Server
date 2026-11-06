#!/usr/bin/env bash
# Development CPU pod: pull development, isolate, migrate, health-check, write a marker.
# Does not push and does not arm production.
#
# Postgres on this pod is local. A stopped cluster used to fail migrate with
# "connection refused", leave the old rehearsal marker in place, and block
# promote_to_master.sh from publishing the release manifest production arms.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_channel.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/pod_profile.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/load_env.sh"

dev_pipeline_pg_host() {
  printf '%s\n' "${POSTGRES_HOST:-127.0.0.1}"
}

dev_pipeline_pg_port() {
  printf '%s\n' "${POSTGRES_PORT:-5432}"
}

dev_pipeline_pg_is_local() {
  case "$(dev_pipeline_pg_host)" in
    127.0.0.1|localhost|::1) return 0 ;;
    *) return 1 ;;
  esac
}

# True when something accepts TCP connections on the Django database host.
dev_pipeline_pg_accepts() {
  local host port
  host="$(dev_pipeline_pg_host)"
  port="$(dev_pipeline_pg_port)"
  if [[ -n "${DEV_PIPELINE_PG_READY_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_READY_HOOK" "$host" "$port"
    return
  fi
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -q -h "$host" -p "$port"
    return
  fi
  python3 - "$host" "$port" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

# RunPod remigration wipes apt packages. pg_ctlcluster and the sysv postgresql
# service are both absent until the server package is installed. Return 2 when
# that install cannot be done.
dev_pipeline_install_postgres() {
  if [[ -n "${DEV_PIPELINE_PG_INSTALL_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_INSTALL_HOOK"
    return
  fi
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$(id -u)" != "0" ]]; then
    echo "dev-pipeline: pg_ctlcluster is not installed. Re-run as root so apt can install postgresql." >&2
    return 2
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "dev-pipeline: pg_ctlcluster is not installed and apt-get is not available." >&2
    return 2
  fi
  echo "dev-pipeline: pg_ctlcluster is not installed; installing postgresql"
  export DEBIAN_FRONTEND=noninteractive
  if ! apt-get update -qq; then
    echo "dev-pipeline: apt-get update failed" >&2
    return 2
  fi
  if ! apt-get install -y postgresql postgresql-contrib \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold; then
    echo "dev-pipeline: apt-get install postgresql failed" >&2
    return 2
  fi
  hash -r
  if ! command -v pg_ctlcluster >/dev/null 2>&1; then
    echo "dev-pipeline: postgresql installed but pg_ctlcluster is still missing" >&2
    return 2
  fi
  DEV_PIPELINE_PG_JUST_INSTALLED=1
  return 0
}

dev_pipeline_sql_quote() {
  local value="$1"
  value="${value//\'/\'\'}"
  printf "'%s'" "$value"
}

# Run psql as the postgres superuser. SQL is fed on stdin.
# `psql -c -c ...` made the statement the database name ("GRANT ALL ... does not exist")
# and `psql -tAc -c` treated SELECT as a connection string.
dev_pipeline_psql_as_postgres() {
  local flags="${1:-}" sql="$2"
  printf '%s\n' "$sql" | su -s /bin/bash postgres -c "psql -v ON_ERROR_STOP=1 ${flags} -f -"
}

# A fresh cluster has the postgres superuser and no app role. Django then fails
# migrate with "role does not exist" instead of connection refused.
dev_pipeline_ensure_app_database() {
  if [[ -n "${DEV_PIPELINE_PG_ROLE_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_ROLE_HOOK"
    return
  fi
  local user db pass pass_sql
  user="${POSTGRES_USER:-pastor}"
  db="${POSTGRES_DB:-ai_db}"
  pass="${POSTGRES_PASSWORD:-}"
  [[ "$user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "dev-pipeline: refusing unsafe POSTGRES_USER" >&2
    return 1
  }
  [[ "$db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "dev-pipeline: refusing unsafe POSTGRES_DB" >&2
    return 1
  }
  if ! command -v psql >/dev/null 2>&1; then
    echo "dev-pipeline: psql is missing, so the app database was not created" >&2
    return 1
  fi
  pass_sql="$(dev_pipeline_sql_quote "$pass")"
  # printf %s does not expand $ inside the password a second time.
  local role_sql db_sql grant_sql
  printf -v role_sql 'CREATE USER %s WITH PASSWORD %s CREATEDB;' "$user" "$pass_sql"
  printf -v db_sql 'CREATE DATABASE %s OWNER %s;' "$db" "$user"
  printf -v grant_sql 'GRANT ALL PRIVILEGES ON DATABASE %s TO %s;' "$db" "$user"
  if ! dev_pipeline_psql_as_postgres -tA "SELECT 1 FROM pg_roles WHERE rolname='${user}'" | grep -q 1; then
    if ! dev_pipeline_psql_as_postgres "" "$role_sql"; then
      echo "dev-pipeline: could not create Postgres role ${user}" >&2
      return 1
    fi
  fi
  if ! dev_pipeline_psql_as_postgres -tA "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
    if ! dev_pipeline_psql_as_postgres "" "$db_sql"; then
      echo "dev-pipeline: could not create database ${db}" >&2
      return 1
    fi
  fi
  dev_pipeline_psql_as_postgres "" "$grant_sql" >/dev/null || true
}

# A package wipe also removes the local data directory. The network volume still
# has the dump start.sh restores. Only do that after this run installed Postgres,
# so a cluster that was merely stopped is left as it is.
dev_pipeline_restore_persistent_postgres() {
  if [[ -n "${DEV_PIPELINE_PG_RESTORE_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_RESTORE_HOOK"
    return
  fi
  [[ "${DEV_PIPELINE_PG_JUST_INSTALLED:-0}" == "1" ]] || return 0
  local runtime="$ROOT/persist_runtime.sh"
  [[ -f "$runtime" ]] || return 0
  # persist_runtime.sh calls log/warn. Do not replace a caller's functions
  # (deploy_update.sh uses those names for its own messages).
  if ! declare -F log >/dev/null 2>&1; then
    log() { echo "dev-pipeline: $*"; }
  fi
  if ! declare -F warn >/dev/null 2>&1; then
    warn() { echo "dev-pipeline: $*" >&2; }
  fi
  # shellcheck source=/dev/null
  source "$runtime"
  echo "dev-pipeline: restoring the persistent database if this container has not restored it yet"
  _restore_persistent_postgres || true
}

dev_pipeline_start_local_postgres() {
  if [[ -n "${DEV_PIPELINE_PG_START_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_START_HOOK"
    return
  fi
  local install_rc=0 ver
  dev_pipeline_install_postgres || install_rc=$?
  if [[ "$install_rc" -ne 0 ]]; then
    return "$install_rc"
  fi
  hash -r
  ver="$(ls /usr/lib/postgresql 2>/dev/null | sort -V | tail -1 || true)"
  if [[ -n "$ver" ]] && command -v pg_ctlcluster >/dev/null 2>&1; then
    echo "dev-pipeline: pg_ctlcluster ${ver} main start"
    if pg_ctlcluster "$ver" main start; then
      return 0
    fi
    if pg_ctlcluster "$ver" main status >/dev/null 2>&1; then
      echo "dev-pipeline: postgres cluster ${ver}/main is already online"
      return 0
    fi
  fi
  if command -v service >/dev/null 2>&1; then
    echo "dev-pipeline: service postgresql start"
    if service postgresql start; then
      return 0
    fi
    echo "dev-pipeline: service postgresql did not start (unrecognized service means the package is not installed)" >&2
  fi
  # The package postinst often starts the cluster before pg_ctlcluster is first used.
  if [[ "${DEV_PIPELINE_PG_JUST_INSTALLED:-0}" == "1" ]]; then
    return 0
  fi
  echo "dev-pipeline: pg_ctlcluster and service postgresql could not start the cluster" >&2
  return 1
}

# Start the local cluster when Django's host:port is refusing connections.
# A remote POSTGRES_HOST is left alone.
dev_pipeline_marker_blocked() {
  echo "dev-pipeline: the rehearsal marker was not written, so promote cannot publish a release manifest." >&2
  return 1
}

dev_pipeline_postgres_ready() {
  if ! dev_pipeline_ensure_app_database; then
    dev_pipeline_marker_blocked
    return
  fi
  dev_pipeline_restore_persistent_postgres || true
  echo "dev-pipeline: postgres is accepting connections on $(dev_pipeline_pg_host):$(dev_pipeline_pg_port)"
}

dev_pipeline_ensure_postgres() {
  local host port attempts pause i start_rc
  host="$(dev_pipeline_pg_host)"
  port="$(dev_pipeline_pg_port)"
  DEV_PIPELINE_PG_JUST_INSTALLED=0
  if dev_pipeline_pg_accepts; then
    dev_pipeline_postgres_ready
    return
  fi
  if ! dev_pipeline_pg_is_local; then
    echo "dev-pipeline: postgres at ${host}:${port} is not accepting connections" >&2
    return 1
  fi
  echo "dev-pipeline: postgres is not accepting connections on ${host}:${port}; starting the local cluster"
  start_rc=0
  dev_pipeline_start_local_postgres || start_rc=$?
  if [[ "$start_rc" -eq 2 ]]; then
    echo "dev-pipeline: postgres did not accept connections on ${host}:${port}" >&2
    dev_pipeline_marker_blocked
    return
  fi
  attempts="${DEV_PIPELINE_PG_ATTEMPTS:-30}"
  pause="${DEV_PIPELINE_PG_PAUSE_S:-1}"
  for ((i = 1; i <= attempts; i++)); do
    if dev_pipeline_pg_accepts; then
      dev_pipeline_postgres_ready
      return
    fi
    if [[ "$i" -lt "$attempts" && "$pause" != "0" ]]; then
      sleep "$pause"
    fi
  done
  echo "dev-pipeline: postgres did not accept connections on ${host}:${port}" >&2
  dev_pipeline_marker_blocked
  return
}

dev_pipeline_main() {
  local WS CHANNEL MODE VIMEO_TEST APP PORT SHA GPU_SMOKE
  local before after path code allowed attempts pause try ready matched

  WS="${WORKSPACE_ROOT:-$ROOT}"
  CHANNEL="$(pastor_git_channel "$WS")"
  [[ "$CHANNEL" == "development" ]] || {
    echo "dev-pipeline: refusing because channel is $CHANNEL" >&2
    exit 1
  }

  if [[ "${DEV_PIPELINE_SKIP_ISOLATE:-0}" != "1" ]]; then
    bash "$ROOT/scripts/isolate_dev_env.sh"
  fi

  if [[ -d "$WS/.git" && "${DEV_PIPELINE_SKIP_PULL:-0}" != "1" ]]; then
    git -C "$WS" fetch origin development
    before="$(git -C "$WS" rev-parse HEAD 2>/dev/null || echo none)"
    git -C "$WS" checkout -B development FETCH_HEAD
    after="$(git -C "$WS" rev-parse HEAD)"
    # The running shell already loaded this file. Restart so migrate uses the
    # script that just landed, including the Postgres startup below.
    if [[ "$before" != "$after" && "${DEV_PIPELINE_REEXECED:-0}" != "1" && -f "$WS/scripts/dev_pipeline.sh" ]]; then
      echo "dev-pipeline: checked out ${after}; restarting with that script"
      export DEV_PIPELINE_REEXECED=1
      export DEV_PIPELINE_SKIP_PULL=1
      exec bash "$WS/scripts/dev_pipeline.sh"
    fi
  fi

  pastor_load_env_file "$WS/config.env"
  pastor_load_env_file "$WS/tokens.env"

  MODE="$(pastor_vllm_mode_name)"
  [[ "$MODE" == "serverless" ]] || {
    echo "dev-pipeline: refusing local vLLM on the development pod" >&2
    exit 1
  }

  VIMEO_TEST=""
  if [[ -f "$WS/tokens.test.env" ]]; then
    VIMEO_TEST="$(grep -E '^VIMEO_FOLDER_ID=' "$WS/tokens.test.env" | tail -1 | cut -d= -f2- || true)"
  fi
  if [[ -z "${VIMEO_TEST:-}" ]]; then
    echo "dev-pipeline: skipping Vimeo sync (no test folder)"
  fi

  if [[ "${DEV_PIPELINE_SKIP_POSTGRES:-0}" != "1" ]]; then
    dev_pipeline_ensure_postgres
  fi

  APP="$WS/backend/app"
  if [[ "${DEV_PIPELINE_SKIP_MIGRATE:-0}" != "1" && -x "$WS/venv/bin/python" ]]; then
    (cd "$APP" && "$WS/venv/bin/python" manage.py migrate --noinput)
  fi

  PORT="${DJANGO_PORT:-8000}"
  # deploy_update.sh stops at migrate when Postgres is down, so nothing is left
  # listening on 8000. The rehearsal cannot write a marker until Django answers.
  if [[ "${DEV_PIPELINE_SKIP_HEALTH:-0}" != "1" && "${DEV_PIPELINE_SKIP_START:-0}" != "1" ]]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/auth/config/" || true)"
    if [[ "$code" != "200" ]]; then
      if [[ -n "${DEV_PIPELINE_START_HOOK:-}" ]]; then
        "$DEV_PIPELINE_START_HOOK" "$WS"
      elif [[ ! -f "$WS/start.sh" ]]; then
        echo "dev-pipeline: $WS/start.sh is missing, so Django was not started" >&2
        exit 1
      else
        echo "dev-pipeline: Django is not answering on 127.0.0.1:${PORT} (HTTP ${code:-000}); running start.sh"
        # onboot sets PASTOR_KEEP_ALIVE=1, which would make start.sh never return.
        PASTOR_KEEP_ALIVE=0 bash "$WS/start.sh"
      fi
      DEV_PIPELINE_HEALTH_ATTEMPTS="${DEV_PIPELINE_HEALTH_ATTEMPTS:-30}"
      DEV_PIPELINE_HEALTH_PAUSE_S="${DEV_PIPELINE_HEALTH_PAUSE_S:-2}"
    fi
  fi
  if [[ "${DEV_PIPELINE_SKIP_HEALTH:-0}" != "1" ]]; then
    # auth/config is public. Media and church events are premium routes:
    # 401 means Django is up and the gate is closed.
    # Retry: a worker can 500 once on a connection opened while Postgres was down.
    local -A expect_ok=(
      [/api/auth/config/]=200
      [/api/media/]="200 401"
      [/api/church-events/]="200 401"
    )
    attempts="${DEV_PIPELINE_HEALTH_ATTEMPTS:-5}"
    pause="${DEV_PIPELINE_HEALTH_PAUSE_S:-2}"
    ready=0
    code=""
    path=""
    for ((try = 1; try <= attempts; try++)); do
      ready=1
      for path in /api/auth/config/ /api/media/ /api/church-events/; do
        code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}" || true)"
        matched=0
        for allowed in ${expect_ok[$path]}; do
          [[ "$code" == "$allowed" ]] && matched=1
        done
        if [[ "$matched" != "1" ]]; then
          ready=0
          break
        fi
      done
      [[ "$ready" == "1" ]] && break
      if [[ "$try" -lt "$attempts" && "$pause" != "0" ]]; then
        sleep "$pause"
      fi
    done
    [[ "$ready" == "1" ]] || {
      echo "dev-pipeline: GET $path returned ${code:-000}" >&2
      if [[ "${code:-000}" == "000" ]]; then
        echo "dev-pipeline: Django is not listening on 127.0.0.1:${PORT}" >&2
      fi
      exit 1
    }
  fi

  SHA="$(git -C "$WS" rev-parse HEAD 2>/dev/null || echo unknown)"
  GPU_SMOKE="${GPU_SMOKE:-0}"
  mkdir -p "$WS/release"
  cat > "$WS/.dev_pipeline_success" <<EOF
SHA=${SHA}
HEALTH=ok
ISOLATION=ok
GPU_SMOKE=${GPU_SMOKE}
EOF
  chmod 600 "$WS/.dev_pipeline_success"
  echo "dev-pipeline: success marker $SHA"
}

if [[ "${DEV_PIPELINE_SOURCE_ONLY:-0}" != "1" && "${BASH_SOURCE[0]}" == "$0" ]]; then
  dev_pipeline_main
fi
