# Git 2.35+ refuses repos whose directory owner is not the current user
# ("fatal: detected dubious ownership"). RunPod network volumes and the
# vendored Flutter SDK at $WS/.flutter-sdk commonly trip this during
# `flutter build web`.

pastor_git_safe_directory_known() {
  local dir="${1:-}"
  [[ -n "$dir" ]] || return 1
  git config --global --get-all safe.directory 2>/dev/null | grep -Fxq "$dir"
}

pastor_mark_git_safe_directory() {
  local dir="${1:-}"
  [[ -n "$dir" ]] || return 0
  pastor_git_safe_directory_known "$dir" && return 0
  git config --global --add safe.directory "$dir" >/dev/null 2>&1 || true
}

# Allow git (and Flutter's child git processes) to use this volume.
pastor_allow_git_on_runpod_volume() {
  local ws="${1:-${WS:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}}"
  local n="${GIT_CONFIG_COUNT:-0}"
  printf -v "GIT_CONFIG_KEY_${n}" '%s' 'safe.directory'
  printf -v "GIT_CONFIG_VALUE_${n}" '%s' '*'
  export "GIT_CONFIG_KEY_${n}" "GIT_CONFIG_VALUE_${n}"
  export GIT_CONFIG_COUNT=$((n + 1))

  pastor_mark_git_safe_directory '*'
  [[ -n "$ws" ]] || return 0
  pastor_mark_git_safe_directory "$ws"
  pastor_mark_git_safe_directory "${ws}/.flutter-sdk"
}
