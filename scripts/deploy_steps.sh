#!/usr/bin/env bash
# Fail-closed deploy steps shared by deploy_update.sh and the 1:00am job.
# Source this file. Functions honor DEPLOY_DRY_RUN=1 and optional hooks:
#   DEPLOY_HOOK_CHECKOUT, DEPLOY_HOOK_PIP, DEPLOY_HOOK_FLUTTER,
#   DEPLOY_HOOK_MIGRATE, DEPLOY_HOOK_START, DEPLOY_HOOK_HEALTH, DEPLOY_HOOK_DUMP
set -euo pipefail

deploy_steps_die() { echo "deploy-steps: $*" >&2; return 1; }

deploy_record_previous() {
  local ws="$1" frontend="$ws/frontend"
  mkdir -p "$ws/release" "$frontend/build"
  if [[ -d "$ws/.git" ]]; then
    git -C "$ws" rev-parse HEAD > "$ws/release/previous.sha"
  fi
  if [[ -d "$frontend/build/web" ]]; then
    rm -rf "$frontend/build/web.prev"
    cp -a "$frontend/build/web" "$frontend/build/web.prev"
  fi
}

deploy_checkout() {
  local ws="$1" channel="$2"
  if [[ -n "${DEPLOY_HOOK_CHECKOUT:-}" ]]; then
    "$DEPLOY_HOOK_CHECKOUT" "$ws" "$channel"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  git -C "$ws" fetch origin "$channel"
  git -C "$ws" checkout -B "$channel" FETCH_HEAD
}

deploy_pip() {
  local app="$1" venv="$2"
  if [[ -n "${DEPLOY_HOOK_PIP:-}" ]]; then
    "$DEPLOY_HOOK_PIP" "$app"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  # shellcheck disable=SC1091
  source "$venv/bin/activate"
  pip install -q -r "$app/requirements.txt"
}

deploy_flutter_staging() {
  local frontend="$1"
  local staging="$frontend/build/web.staging"
  if [[ -n "${DEPLOY_HOOK_FLUTTER:-}" ]]; then
    "$DEPLOY_HOOK_FLUTTER" "$frontend" "$staging"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  command -v flutter >/dev/null 2>&1 || deploy_steps_die "flutter is not on PATH"
  rm -rf "$staging"
  (
    cd "$frontend"
    local -a args=(build web --release --dart-define=API_BASE_URL= --output=build/web.staging)
    if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
      args+=(--dart-define=GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID}")
    fi
    flutter "${args[@]}"
  )
  [[ -f "$staging/index.html" ]] || deploy_steps_die "staging Flutter build missing index.html"
}

deploy_swap_web() {
  local frontend="$1"
  local staging="$frontend/build/web.staging"
  local live="$frontend/build/web"
  [[ -f "$staging/index.html" ]] || deploy_steps_die "refusing to swap without a staging build"
  rm -rf "$live"
  mv "$staging" "$live"
}

deploy_migrate() {
  local app="$1"
  if [[ -n "${DEPLOY_HOOK_MIGRATE:-}" ]]; then
    "$DEPLOY_HOOK_MIGRATE" "$app"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  (cd "$app" && python manage.py migrate --noinput)
}

deploy_start() {
  local ws="$1"
  if [[ -n "${DEPLOY_HOOK_START:-}" ]]; then
    "$DEPLOY_HOOK_START" "$ws"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  bash "$ws/start.sh"
}

deploy_health_localhost() {
  local port="${1:-8000}"
  if [[ -n "${DEPLOY_HOOK_HEALTH:-}" ]]; then
    "$DEPLOY_HOOK_HEALTH" "$port"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  local path code
  for path in /api/auth/config/ /api/media/ /api/church-events/; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}${path}" || true)"
    [[ "$code" == "200" ]] || deploy_steps_die "GET ${path} returned ${code:-000}"
  done
}

deploy_rollback_code() {
  local ws="$1" frontend="$ws/frontend"
  local sha=""
  [[ -f "$ws/release/previous.sha" ]] && sha="$(tr -d '[:space:]' < "$ws/release/previous.sha")"
  if [[ -n "${DEPLOY_HOOK_ROLLBACK:-}" ]]; then
    "$DEPLOY_HOOK_ROLLBACK" "$ws" "$sha"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  if [[ -n "$sha" && -d "$ws/.git" ]]; then
    git -C "$ws" checkout "$sha"
  fi
  if [[ -d "$frontend/build/web.prev" ]]; then
    rm -rf "$frontend/build/web"
    mv "$frontend/build/web.prev" "$frontend/build/web"
  fi
}

deploy_pg_dump() {
  local dest="$1" db="${2:-ai_db}"
  mkdir -p "$(dirname "$dest")"
  if [[ -n "${DEPLOY_HOOK_DUMP:-}" ]]; then
    "$DEPLOY_HOOK_DUMP" "$dest"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && { : > "$dest"; return 0; }
  su -s /bin/bash postgres -c "pg_dump -Fc --no-owner -d '${db}' -f '${dest}'"
  chmod 600 "$dest"
}

deploy_pg_restore() {
  local dump="$1" db="${2:-ai_db}"
  if [[ -n "${DEPLOY_HOOK_RESTORE:-}" ]]; then
    "$DEPLOY_HOOK_RESTORE" "$dump"
    return
  fi
  [[ "${DEPLOY_DRY_RUN:-0}" == "1" ]] && return 0
  [[ -f "$dump" ]] || deploy_steps_die "missing dump $dump"
  su -s /bin/bash postgres -c "pg_restore --no-owner --clean --if-exists -d '${db}' '${dump}'"
}
