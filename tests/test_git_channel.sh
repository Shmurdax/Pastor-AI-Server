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
grep -q 'CHANNEL=master' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must default to master"
grep -q 'checkout -f -B' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must force-checkout the fetched channel"
grep -q 'reset --hard FETCH_HEAD' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must hard-reset to fetched channel"
if grep -q 'skipped git pull' "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not skip a failed git fetch"
fi
if grep -q '2>/dev/null' "$ROOT/deploy_update.sh"; then
  # git fetch/checkout used to hide failures; keep stderr on those commands.
  git_block="$(sed -n '/Fetching origin/,/Now at /p' "$ROOT/deploy_update.sh")"
  echo "$git_block" | grep -q '2>/dev/null' && fail "deploy_update.sh git update must not swallow stderr"
fi

# Dirty working tree must still move HEAD to FETCH_HEAD (prod pod failure mode).
DIRTY="$(mktemp -d)"
git init -q "$DIRTY"
git -C "$DIRTY" config user.email test@example.com
git -C "$DIRTY" config user.name test
printf 'one\n' > "$DIRTY/file"
git -C "$DIRTY" add file
git -C "$DIRTY" commit -qm one
printf 'two\n' > "$DIRTY/file"
git -C "$DIRTY" add file
git -C "$DIRTY" commit -qm two
git -C "$DIRTY" update-ref refs/remotes/origin/master HEAD
git -C "$DIRTY" checkout -q HEAD~1
printf 'dirt\n' > "$DIRTY/file"
git -C "$DIRTY" update-ref FETCH_HEAD refs/remotes/origin/master
git -C "$DIRTY" checkout -f -B master FETCH_HEAD >/dev/null
git -C "$DIRTY" reset --hard FETCH_HEAD >/dev/null
[[ "$(git -C "$DIRTY" log -1 --pretty=%s)" == "two" ]] || fail "dirty tree should hard-reset to FETCH_HEAD"
[[ "$(cat "$DIRTY/file")" == "two" ]] || fail "dirty file should be discarded on deploy"
rm -rf "$DIRTY"
grep -q 'git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy git_channel.sh"
grep -q 'git_safe_directory.sh' "$ROOT/install.sh" || fail "install.sh must copy git_safe_directory.sh"
grep -q 'promote_to_master.sh' "$ROOT/install.sh" || fail "install.sh must copy promote_to_master.sh"
grep -q 'REPO_BRANCH="${REPO_BRANCH:-development}"' "$ROOT/install.sh" || fail "install.sh default branch must be development"
grep -q '## Git channels' "$ROOT/README.md" || fail "README must document development vs master"
grep -q '`development`' "$ROOT/README.md" || fail "README must name development"
grep -q '`master`' "$ROOT/README.md" || fail "README must name master"

echo "OK git channel development/master"
