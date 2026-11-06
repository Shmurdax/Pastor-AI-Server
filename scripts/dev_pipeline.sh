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

dev_pipeline_start_local_postgres() {
  if [[ -n "${DEV_PIPELINE_PG_START_HOOK:-}" ]]; then
    "$DEV_PIPELINE_PG_START_HOOK"
    return
  fi
  local ver
  ver="$(ls /usr/lib/postgresql 2>/dev/null | sort -V | tail -1 || true)"
  if [[ -n "$ver" ]] && command -v pg_ctlcluster >/dev/null 2>&1; then
    echo "dev-pipeline: pg_ctlcluster ${ver} main start"
    if pg_ctlcluster "$ver" main start; then
      return 0
    fi
  fi
  if command -v service >/dev/null 2>&1; then
    echo "dev-pipeline: service postgresql start"
    service postgresql start
    return
  fi
  echo "dev-pipeline: neither pg_ctlcluster nor service is available" >&2
  return 1
}

# Start the local cluster when Django's host:port is refusing connections.
# A remote POSTGRES_HOST is left alone.
dev_pipeline_ensure_postgres() {
  local host port attempts pause i
  host="$(dev_pipeline_pg_host)"
  port="$(dev_pipeline_pg_port)"
  if dev_pipeline_pg_accepts; then
    return 0
  fi
  if ! dev_pipeline_pg_is_local; then
    echo "dev-pipeline: postgres at ${host}:${port} is not accepting connections" >&2
    return 1
  fi
  echo "dev-pipeline: postgres is not accepting connections on ${host}:${port}; starting the local cluster"
  dev_pipeline_start_local_postgres || true
  attempts="${DEV_PIPELINE_PG_ATTEMPTS:-30}"
  pause="${DEV_PIPELINE_PG_PAUSE_S:-1}"
  for ((i = 1; i <= attempts; i++)); do
    if dev_pipeline_pg_accepts; then
      echo "dev-pipeline: postgres is accepting connections on ${host}:${port}"
      return 0
    fi
    if [[ "$i" -lt "$attempts" && "$pause" != "0" ]]; then
      sleep "$pause"
    fi
  done
  echo "dev-pipeline: postgres did not accept connections on ${host}:${port}" >&2
  echo "dev-pipeline: the rehearsal marker was not written, so promote cannot publish a release manifest." >&2
  return 1
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
