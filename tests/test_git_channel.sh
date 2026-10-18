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
grep -q 'pastor_resolve_git_channel' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must follow .git_channel"
if grep -q 'CHANNEL=master' "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not force master when .git_channel is set"
fi
grep -q 'pastor_sync_git_channel' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must sync via helper"
grep -q 'pastor_sync_git_channel' "$ROOT/onboot.sh" || fail "onboot.sh must sync git before start"
grep -q 'PASTOR_PRESERVE_FLUTTER_BUILD=1' "$ROOT/onboot.sh" \
  || fail "onboot.sh must keep a same-SHA Flutter rebuild"
grep -q 'PASTOR_FLUTTER_BUILD_PRESERVED' "$ROOT/onboot.sh" \
  || fail "onboot.sh must rebuild the dev site when the Flutter bundle was reset"
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
unset PASTOR_GIT_BRANCH REPO_BRANCH
rm -f "$DIR/.git_channel"
[[ "$(pastor_resolve_git_channel "$DIR")" == "master" ]] || fail "missing .git_channel should resolve to master"
printf 'development\n' > "$DIR/.git_channel"
[[ "$(pastor_resolve_git_channel "$DIR")" == "development" ]] || fail "dev pod .git_channel should resolve to development"
printf 'master\n' > "$DIR/.git_channel"
[[ "$(pastor_resolve_git_channel "$DIR")" == "master" ]] || fail "prod pod .git_channel should resolve to master"
PASTOR_GIT_BRANCH=development
[[ "$(pastor_resolve_git_channel "$DIR")" == "development" ]] || fail "PASTOR_GIT_BRANCH should override .git_channel at resolve"
unset PASTOR_GIT_BRANCH
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
mkdir -p "$CLONE/frontend/build/web"
printf 'old\n' > "$CLONE/frontend/build/web/index.html"
git -C "$CLONE" add frontend/build/web/index.html
git -C "$CLONE" commit -qm flutter
printf 'rebuilt\n' > "$CLONE/frontend/build/web/index.html"
pastor_git_tracked_dirty "$CLONE" && fail "flutter web rebuild should not count as dirty"
printf 'overlay\n' > "$CLONE/file"
pastor_git_tracked_dirty "$CLONE" || fail "tracked overlay should still count as dirty"
rm -rf "$UPSTREAM" "$CLONE"

# Same-SHA boot sync must keep the Flutter bundle deploy_update compiled.
# A plain sync (deploy_update) still discards it and rebuilds afterwards.
PRESERVE_UP="$(mktemp -d)"
PRESERVE_CLONE="$(mktemp -d)"
git init -q -b development "$PRESERVE_UP"
git -C "$PRESERVE_UP" config user.email test@example.com
git -C "$PRESERVE_UP" config user.name test
mkdir -p "$PRESERVE_UP/frontend/build/web"
printf 'committed\n' > "$PRESERVE_UP/frontend/build/web/index.html"
printf 'src\n' > "$PRESERVE_UP/file"
git -C "$PRESERVE_UP" add frontend/build/web/index.html file
git -C "$PRESERVE_UP" commit -qm pinned
git clone -q "$PRESERVE_UP" "$PRESERVE_CLONE"
printf 'development\n' > "$PRESERVE_CLONE/.git_channel"
printf 'rebuilt\n' > "$PRESERVE_CLONE/frontend/build/web/index.html"
PASTOR_PRESERVE_FLUTTER_BUILD=1
pastor_sync_git_channel "$PRESERVE_CLONE" development
[[ "$(cat "$PRESERVE_CLONE/frontend/build/web/index.html")" == "rebuilt" ]] \
  || fail "same-SHA sync should keep the local Flutter rebuild"
[[ "${PASTOR_FLUTTER_BUILD_PRESERVED}" == "1" ]] || fail "preserve flag should be set"
[[ "${PASTOR_GIT_CHANGED}" == "0" ]] || fail "flutter-only rebuild must not force a deploy"
printf 'rebuilt-again\n' > "$PRESERVE_CLONE/frontend/build/web/index.html"
PASTOR_PRESERVE_FLUTTER_BUILD=0
pastor_sync_git_channel "$PRESERVE_CLONE" development
[[ "$(cat "$PRESERVE_CLONE/frontend/build/web/index.html")" == "committed" ]] \
  || fail "sync without preserve must restore the committed Flutter bundle"
[[ "${PASTOR_FLUTTER_BUILD_PRESERVED}" == "0" ]] || fail "preserve flag must stay unset"
printf 'rebuilt\n' > "$PRESERVE_CLONE/frontend/build/web/index.html"
printf 'newer\n' > "$PRESERVE_UP/file"
git -C "$PRESERVE_UP" add file
git -C "$PRESERVE_UP" commit -qm newer
PASTOR_PRESERVE_FLUTTER_BUILD=1
pastor_sync_git_channel "$PRESERVE_CLONE" development
[[ "$(git -C "$PRESERVE_CLONE" log -1 --pretty=%s)" == "newer" ]] \
  || fail "new upstream commit should still move HEAD"
[[ "$(cat "$PRESERVE_CLONE/frontend/build/web/index.html")" == "committed" ]] \
  || fail "HEAD move must discard the parked Flutter rebuild"
[[ "${PASTOR_GIT_CHANGED}" == "1" ]] || fail "HEAD move must set PASTOR_GIT_CHANGED"
[[ "${PASTOR_FLUTTER_BUILD_PRESERVED}" == "0" ]] || fail "HEAD move must not mark the Flutter build preserved"
unset PASTOR_PRESERVE_FLUTTER_BUILD
rm -rf "$PRESERVE_UP" "$PRESERVE_CLONE"
grep -q 'git_channel.sh' "$ROOT/install.sh" || fail "install.sh must copy git_channel.sh"
grep -q 'git_safe_directory.sh' "$ROOT/install.sh" || fail "install.sh must copy git_safe_directory.sh"
grep -q 'promote_to_master.sh' "$ROOT/install.sh" || fail "install.sh must copy promote_to_master.sh"
grep -q 'REPO_BRANCH="${REPO_BRANCH:-development}"' "$ROOT/install.sh" || fail "install.sh default branch must be development"
grep -q '## Git channels' "$ROOT/README.md" || fail "README must document development vs master"
grep -q '`development`' "$ROOT/README.md" || fail "README must name development"
grep -q '`master`' "$ROOT/README.md" || fail "README must name master"
grep -q 'onboot.sh' "$ROOT/README.md" || fail "README must document onboot git sync"

echo "OK git channel development/master"
