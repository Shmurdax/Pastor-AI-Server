#!/usr/bin/env bash
# Fetch origin/$CHANNEL and hard-reset the Pastor-AI checkout so a RunPod
# volume cannot silently stay on an old SHA or a dirty overlay.
#
# Sourced by deploy_update.sh and onboot.sh. Safe to source more than once.
#
# Env:
#   PASTOR_SKIP_GIT_SYNC=1     no-op (caller already synced)
#   PASTOR_GIT_SYNC_TIMEOUT    git fetch timeout seconds (default 90)
#
# Exported after pastor_sync_git_channel:
#   PASTOR_GIT_CHANGED=0|1     1 if HEAD moved or tracked dirt was discarded
#   PASTOR_GIT_SHA
#   PASTOR_GIT_CHANNEL
#   PASTOR_GIT_ORIGIN_SHA
#   PASTOR_GIT_DIRTY           0 after a successful reset
#
# Return:
#   0 synced (or skip)
#   1 fetch/reset failed — onboot may fail-open so the pod still boots

_pastor_git_log() {
  if declare -F log >/dev/null 2>&1; then
    log "$@"
  else
    echo "[git-sync] $*"
  fi
}

_pastor_git_warn() {
  if declare -F warn >/dev/null 2>&1; then
    warn "$@"
  else
    echo "[git-sync] $*" >&2
  fi
}

pastor_git_stamp_paths() {
  # Prints the workspace root used for DEPLOYED_* stamp files.
  printf '%s' "${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
}

pastor_git_tracked_dirty() {
  local ws="${1:-}"
  [[ -d "$ws/.git" ]] || return 1
  # Flutter web rebuild during deploy_update always touches tracked
  # frontend/build/web files. That is not version drift.
  git -C "$ws" status --porcelain --untracked-files=no 2>/dev/null \
    | grep -v 'frontend/build/' \
    | grep -q .
}

pastor_resolve_git_channel() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  if [[ -n "${PASTOR_GIT_BRANCH:-}${REPO_BRANCH:-}" ]]; then
    pastor_git_channel "$ws"
  elif [[ -f "$ws/.git_channel" ]]; then
    pastor_git_channel "$ws"
  else
    # Missing channel file: production pin. Dev pods persist .git_channel.
    printf '%s\n' "master"
  fi
}

pastor_write_deploy_stamp() {
  local ws="${1:-}"
  local channel="${2:-}"
  local sha="${3:-}"
  local origin_sha="${4:-}"
  local dirty="${5:-0}"
  local err="${6:-}"
  local oneline=""
  [[ -n "$ws" ]] || return 0
  mkdir -p "$ws"
  if [[ -n "$sha" && -d "$ws/.git" ]]; then
    oneline="$(git -C "$ws" log -1 --oneline "$sha" 2>/dev/null || true)"
  fi
  if [[ -z "$oneline" && -d "$ws/.git" ]]; then
    oneline="$(git -C "$ws" log -1 --oneline 2>/dev/null || true)"
  fi
  printf '%s\n' "$sha" > "$ws/DEPLOYED_SHA"
  printf '%s\n' "$sha" > "$ws/DEPLOYED_MASTER_SHA"
  printf '%s\n' "$oneline" > "$ws/DEPLOYED_ONELINE"
  printf '%s\n' "$oneline" > "$ws/DEPLOYED_MASTER_ONELINE"
  printf '%s\n' "$channel" > "$ws/DEPLOYED_CHANNEL"
  printf '%s\n' "$origin_sha" > "$ws/DEPLOYED_ORIGIN_SHA"
  printf '%s\n' "$dirty" > "$ws/DEPLOYED_DIRTY"
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$ws/DEPLOYED_AT"
  if [[ -n "$err" ]]; then
    printf '%s\n' "$err" > "$ws/DEPLOYED_SYNC_ERROR"
  else
    rm -f "$ws/DEPLOYED_SYNC_ERROR"
    : > "$ws/DEPLOYED_SYNC_ERROR"
  fi
}

pastor_record_running_git() {
  # Refresh stamps from the live tree without fetching. Used by start.sh so
  # DEPLOYED_MASTER_SHA cannot stay on a previous overlay SHA.
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local channel sha origin_sha dirty=0
  [[ -d "$ws/.git" ]] || return 1
  channel="$(pastor_resolve_git_channel "$ws")"
  sha="$(git -C "$ws" rev-parse HEAD 2>/dev/null || true)"
  origin_sha="$(git -C "$ws" rev-parse "refs/remotes/origin/${channel}" 2>/dev/null || true)"
  if [[ -z "$origin_sha" && -f "$ws/DEPLOYED_ORIGIN_SHA" ]]; then
    origin_sha="$(tr -d '[:space:]' < "$ws/DEPLOYED_ORIGIN_SHA")"
  fi
  pastor_git_tracked_dirty "$ws" && dirty=1
  pastor_write_deploy_stamp "$ws" "$channel" "$sha" "$origin_sha" "$dirty" ""
  PASTOR_GIT_SHA="$sha"
  PASTOR_GIT_CHANNEL="$channel"
  PASTOR_GIT_ORIGIN_SHA="$origin_sha"
  PASTOR_GIT_DIRTY="$dirty"
  export PASTOR_GIT_SHA PASTOR_GIT_CHANNEL PASTOR_GIT_ORIGIN_SHA PASTOR_GIT_DIRTY
}

pastor_warn_if_git_drift() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local sha origin_sha dirty=0
  [[ -d "$ws/.git" ]] || return 0
  sha="$(git -C "$ws" rev-parse --short HEAD 2>/dev/null || true)"
  origin_sha="$(git -C "$ws" rev-parse --short "refs/remotes/origin/$(pastor_resolve_git_channel "$ws")" 2>/dev/null || true)"
  pastor_git_tracked_dirty "$ws" && dirty=1
  if [[ "$dirty" -eq 1 ]]; then
    _pastor_git_warn "Working tree has tracked edits — production is not a clean origin/$(pastor_resolve_git_channel "$ws") checkout (HEAD $sha)"
  fi
  if [[ -n "$origin_sha" && -n "$sha" && "$sha" != "$origin_sha" ]]; then
    _pastor_git_warn "HEAD $sha is not origin/$(pastor_resolve_git_channel "$ws") $origin_sha — run bash $ws/deploy_update.sh"
  fi
}

pastor_sync_git_channel() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local channel="${2:-}"
  local before_sha after_sha origin_sha timeout_s fetch_rc
  PASTOR_GIT_CHANGED=0
  export PASTOR_GIT_CHANGED
  if [[ "${PASTOR_SKIP_GIT_SYNC:-0}" == "1" ]]; then
    pastor_record_running_git "$ws" || true
    return 0
  fi
  if [[ ! -d "$ws/.git" ]]; then
    _pastor_git_warn "No .git at $ws — cannot sync to GitHub"
    pastor_write_deploy_stamp "$ws" "${channel:-master}" "" "" "1" "no .git checkout"
    return 1
  fi

  if [[ -z "$channel" ]]; then
    channel="$(pastor_resolve_git_channel "$ws")"
  fi
  channel="$(pastor_git_canonicalize "$channel")"
  pastor_write_git_channel "$ws" "$channel"

  if declare -F pastor_allow_git_on_runpod_volume >/dev/null 2>&1; then
    pastor_allow_git_on_runpod_volume "$ws"
  fi

  before_sha="$(git -C "$ws" rev-parse HEAD 2>/dev/null || true)"
  if pastor_git_tracked_dirty "$ws"; then
    PASTOR_GIT_CHANGED=1
  fi

  timeout_s="${PASTOR_GIT_SYNC_TIMEOUT:-90}"
  _pastor_git_log "Fetching origin/$channel"
  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout_s" git -C "$ws" fetch origin "$channel"
    fetch_rc=$?
  else
    git -C "$ws" fetch origin "$channel"
    fetch_rc=$?
  fi
  if [[ "$fetch_rc" -ne 0 ]]; then
    _pastor_git_warn "git fetch origin $channel failed (rc=$fetch_rc)"
    pastor_record_running_git "$ws" || true
    pastor_write_deploy_stamp "$ws" "$channel" "${PASTOR_GIT_SHA:-$before_sha}" \
      "${PASTOR_GIT_ORIGIN_SHA:-}" "${PASTOR_GIT_DIRTY:-1}" \
      "git fetch origin $channel failed (rc=$fetch_rc)"
    return 1
  fi

  origin_sha="$(git -C "$ws" rev-parse FETCH_HEAD)"
  _pastor_git_log "Resetting to origin/$channel ($(git -C "$ws" rev-parse --short FETCH_HEAD))"
  # -f discards a dirty working tree. Without it, checkout -B is a no-op on
  # pods that have local edits and deploy_update silently stays behind.
  if ! git -C "$ws" checkout -f -B "$channel" FETCH_HEAD; then
    _pastor_git_warn "git checkout $channel failed"
    pastor_write_deploy_stamp "$ws" "$channel" "$before_sha" "$origin_sha" "1" \
      "git checkout $channel failed"
    return 1
  fi
  if ! git -C "$ws" reset --hard FETCH_HEAD; then
    _pastor_git_warn "git reset --hard $channel failed"
    pastor_write_deploy_stamp "$ws" "$channel" "$before_sha" "$origin_sha" "1" \
      "git reset --hard $channel failed"
    return 1
  fi

  after_sha="$(git -C "$ws" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$before_sha" != "$after_sha" ]]; then
    PASTOR_GIT_CHANGED=1
  fi
  export PASTOR_GIT_CHANGED
  PASTOR_GIT_SHA="$after_sha"
  PASTOR_GIT_CHANNEL="$channel"
  PASTOR_GIT_ORIGIN_SHA="$origin_sha"
  PASTOR_GIT_DIRTY=0
  export PASTOR_GIT_SHA PASTOR_GIT_CHANNEL PASTOR_GIT_ORIGIN_SHA PASTOR_GIT_DIRTY
  pastor_write_deploy_stamp "$ws" "$channel" "$after_sha" "$origin_sha" "0" ""
  _pastor_git_log "Now at $(git -C "$ws" log -1 --oneline)"
  return 0
}
