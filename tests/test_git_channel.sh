#!/usr/bin/env bash
# Branch-channel helpers for latest vs stable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_channel.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }

unset PASTOR_GIT_BRANCH REPO_BRANCH
DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

[[ "$(pastor_git_channel "$DIR")" == "latest" ]] || fail "default channel should be latest"

echo stable > "$DIR/.git_channel"
[[ "$(pastor_git_channel "$DIR")" == "stable" ]] || fail ".git_channel should win over default"

PASTOR_GIT_BRANCH=latest
[[ "$(pastor_git_channel "$DIR")" == "latest" ]] || fail "PASTOR_GIT_BRANCH should override .git_channel"
unset PASTOR_GIT_BRANCH

REPO_BRANCH=master
[[ "$(pastor_git_channel "$DIR")" == "master" ]] || fail "REPO_BRANCH should be accepted"
unset REPO_BRANCH

echo bogus > "$DIR/.git_channel"
[[ "$(pastor_git_channel "$DIR")" == "latest" ]] || fail "unknown channel should fall back to latest"

pastor_write_git_channel "$DIR" stable
[[ "$(cat "$DIR/.git_channel")" == "stable" ]] || fail "pastor_write_git_channel should persist stable"

grep -q 'PASTOR_GIT_BRANCH' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must honor PASTOR_GIT_BRANCH"
grep -q 'pastor_git_channel' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must use git_channel helper"
if grep -q 'pull --ff-only origin master' "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not hardcode origin master only"
fi
grep -q 'git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy git_channel.sh"
grep -q 'REPO_BRANCH="${REPO_BRANCH:-latest}"' "$ROOT/install.sh" || fail "install.sh default branch must be latest"
grep -q '## Git channels' "$ROOT/README.md" || fail "README must document latest vs stable"

echo "OK git channel latest/stable"
