#!/usr/bin/env bash
# Branch-channel helpers for development vs master.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_channel.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }

unset PASTOR_GIT_BRANCH REPO_BRANCH
DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

[[ "$(pastor_git_channel "$DIR")" == "development" ]] || fail "default channel should be development"

echo master > "$DIR/.git_channel"
[[ "$(pastor_git_channel "$DIR")" == "master" ]] || fail ".git_channel master should win over default"

echo stable > "$DIR/.git_channel"
[[ "$(pastor_git_channel "$DIR")" == "master" ]] || fail "legacy stable should map to master"

PASTOR_GIT_BRANCH=development
[[ "$(pastor_git_channel "$DIR")" == "development" ]] || fail "PASTOR_GIT_BRANCH should override .git_channel"
unset PASTOR_GIT_BRANCH

PASTOR_GIT_BRANCH=latest
[[ "$(pastor_git_channel "$DIR")" == "development" ]] || fail "legacy latest should map to development"
unset PASTOR_GIT_BRANCH

echo bogus > "$DIR/.git_channel"
[[ "$(pastor_git_channel "$DIR")" == "development" ]] || fail "unknown channel should fall back to development"

pastor_write_git_channel "$DIR" latest
[[ "$(cat "$DIR/.git_channel")" == "development" ]] || fail "write should persist canonical development"

grep -q 'PASTOR_GIT_BRANCH' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must honor PASTOR_GIT_BRANCH"
grep -q 'pastor_git_channel' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must use git_channel helper"
if grep -q 'pull --ff-only origin master' "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not hardcode origin master only"
fi
grep -q 'git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy git_channel.sh"
grep -q 'promote_to_master.sh' "$ROOT/install.sh" || fail "install.sh must copy promote_to_master.sh"
grep -q 'REPO_BRANCH="${REPO_BRANCH:-development}"' "$ROOT/install.sh" || fail "install.sh default branch must be development"
grep -q '## Git channels' "$ROOT/README.md" || fail "README must document development vs master"
grep -q '`development`' "$ROOT/README.md" || fail "README must name development"
grep -q '`master`' "$ROOT/README.md" || fail "README must name master"

echo "OK git channel development/master"
