#!/usr/bin/env bash
# Git safe.directory helper for the vendored Flutter SDK on RunPod volumes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_safe_directory.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
export HOME="$DIR"
unset GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0 2>/dev/null || true

pastor_mark_git_safe_directory "$DIR/.flutter-sdk"
git config --global --get-all safe.directory | grep -Fxq "$DIR/.flutter-sdk" \
  || fail "should persist .flutter-sdk as safe.directory"

pastor_mark_git_safe_directory "$DIR/.flutter-sdk"
count="$(git config --global --get-all safe.directory | grep -Fxc "$DIR/.flutter-sdk" || true)"
[[ "$count" == "1" ]] || fail "second mark should not duplicate safe.directory (got $count)"

pastor_allow_git_on_runpod_volume "$DIR"
git config --global --get-all safe.directory | grep -Fxq '*' \
  || fail "volume helper should allow all directories via '*'"
git config --global --get-all safe.directory | grep -Fxq "$DIR" \
  || fail "volume helper should allow the pastor-ai workspace"
[[ "${GIT_CONFIG_COUNT:-0}" -ge 1 ]] || fail "GIT_CONFIG_COUNT should be exported for Flutter child git"
[[ "${GIT_CONFIG_KEY_0:-}" == "safe.directory" ]] || fail "GIT_CONFIG_KEY_0 should be safe.directory"
[[ "${GIT_CONFIG_VALUE_0:-}" == "*" ]] || fail "GIT_CONFIG_VALUE_0 should be *"

grep -q 'pastor_allow_git_on_runpod_volume' "$ROOT/deploy_update.sh" \
  || fail "deploy_update.sh must mark git safe.directory before flutter build"
grep -q 'git_safe_directory.sh' "$ROOT/deploy_update.sh" \
  || fail "deploy_update.sh must source git_safe_directory.sh"
grep -q 'git_safe_directory.sh' "$ROOT/install.sh" \
  || fail "install.sh must copy git_safe_directory.sh"
grep -q 'dubious ownership' "$ROOT/RUNPOD.md" \
  || fail "RUNPOD.md must document the Flutter SDK git ownership error"

echo "OK git safe.directory for Flutter SDK"
