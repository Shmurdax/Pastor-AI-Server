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
grep -q 'pastor_sync_git_channel' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must sync via helper"
grep -q 'pastor_sync_git_channel' "$ROOT/onboot.sh" || fail "onboot.sh must sync git before start"
grep -q 'checkout -f -B' "$ROOT/scripts/sync_git_channel.sh" || fail "sync helper must force-checkout the fetched channel"
grep -q 'reset --hard FETCH_HEAD' "$ROOT/scripts/sync_git_channel.sh" || fail "sync helper must hard-reset to fetched channel"
grep -q 'DEPLOYED_SHA' "$ROOT/scripts/sync_git_channel.sh" || fail "sync helper must write DEPLOYED_SHA"
grep -q 'deploy_update.sh' "$ROOT/persist_runtime.sh" || fail "persist boot bundle must include deploy_update.sh"
grep -q 'sync_git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy sync_git_channel.sh"
grep -q 'api/health/' "$ROOT/backend/app/pastor_ai/urls.py" || fail "urls.py must expose /api/health/"
grep -q 'DEPLOYED_\*' "$ROOT/.gitignore" || fail ".gitignore must ignore DEPLOYED_* stamps"
if grep -q 'skipped git pull' "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not skip a failed git fetch"
fi
if grep -Eq 'git -C .* (fetch|checkout|reset) .*2>/dev/null' "$ROOT/scripts/sync_git_channel.sh"; then
  fail "git fetch/checkout/reset must not swallow stderr"
fi

# Dirty working tree must still move HEAD to FETCH_HEAD (prod pod failure mode).
# shellcheck source=/dev/null
source "$ROOT/scripts/git_safe_directory.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/sync_git_channel.sh"
UPSTREAM="$(mktemp -d)"
CLONE="$(mktemp -d)"
git init -q -b master "$UPSTREAM"
git -C "$UPSTREAM" config user.email test@example.com
git -C "$UPSTREAM" config user.name test
printf 'one\n' > "$UPSTREAM/file"
git -C "$UPSTREAM" add file
git -C "$UPSTREAM" commit -qm one
printf 'two\n' > "$UPSTREAM/file"
git -C "$UPSTREAM" add file
git -C "$UPSTREAM" commit -qm two
git clone -q "$UPSTREAM" "$CLONE"
git -C "$CLONE" checkout -q HEAD~1
printf 'dirt\n' > "$CLONE/file"
echo master > "$CLONE/.git_channel"
unset PASTOR_SKIP_GIT_SYNC || true
pastor_sync_git_channel "$CLONE" master
[[ "$(git -C "$CLONE" log -1 --pretty=%s)" == "two" ]] || fail "dirty tree should hard-reset to origin/master"
[[ "$(cat "$CLONE/file")" == "two" ]] || fail "dirty file should be discarded on sync"
[[ "${PASTOR_GIT_CHANGED}" == "1" ]] || fail "sync should flag PASTOR_GIT_CHANGED"
[[ "$(tr -d '[:space:]' < "$CLONE/DEPLOYED_DIRTY")" == "0" ]] || fail "stamp dirty should be 0"
[[ -s "$CLONE/DEPLOYED_SHA" ]] || fail "sync should write DEPLOYED_SHA"
[[ "$(tr -d '[:space:]' < "$CLONE/DEPLOYED_SHA")" == "$(git -C "$CLONE" rev-parse HEAD)" ]] \
  || fail "DEPLOYED_SHA must match HEAD"
rm -rf "$UPSTREAM" "$CLONE"
grep -q 'git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy git_channel.sh"
grep -q 'git_safe_directory.sh' "$ROOT/install.sh" || fail "install.sh must copy git_safe_directory.sh"
grep -q 'promote_to_master.sh' "$ROOT/install.sh" || fail "install.sh must copy promote_to_master.sh"
grep -q 'REPO_BRANCH="${REPO_BRANCH:-development}"' "$ROOT/install.sh" || fail "install.sh default branch must be development"
grep -q '## Git channels' "$ROOT/README.md" || fail "README must document development vs master"
grep -q '`development`' "$ROOT/README.md" || fail "README must name development"
grep -q '`master`' "$ROOT/README.md" || fail "README must name master"
grep -q 'onboot.sh' "$ROOT/README.md" || fail "README must document onboot git sync"

echo "OK git channel development/master"
