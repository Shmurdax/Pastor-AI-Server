#!/usr/bin/env bash
# Resolve which Git branch this Pastor-AI checkout should track.
#
#   development — all new work (christian-ai-dev)
#   master      — production pin (christian-ai-prd)
#
# Override order:
#   1. PASTOR_GIT_BRANCH env
#   2. REPO_BRANCH env (install.sh)
#   3. $WS/.git_channel (one line, no comments)
#   4. default: development
#
# Legacy names latest→development and stable→master still resolve.
pastor_git_canonicalize() {
  case "${1:-}" in
    development|latest) printf '%s\n' "development" ;;
    master|stable) printf '%s\n' "master" ;;
    *) printf '%s\n' "development" ;;
  esac
}

pastor_git_channel() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local channel=""
  if [[ -n "${PASTOR_GIT_BRANCH:-}" ]]; then
    channel="$PASTOR_GIT_BRANCH"
  elif [[ -n "${REPO_BRANCH:-}" ]]; then
    channel="$REPO_BRANCH"
  elif [[ -f "$ws/.git_channel" ]]; then
    channel="$(tr -d '[:space:]' < "$ws/.git_channel")"
  fi
  pastor_git_canonicalize "$channel"
}

pastor_write_git_channel() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local channel
  channel="$(pastor_git_canonicalize "${2:-$(pastor_git_channel "$ws")}")"
  mkdir -p "$ws"
  printf '%s\n' "$channel" > "$ws/.git_channel"
}
