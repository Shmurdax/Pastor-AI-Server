#!/usr/bin/env bash
# Isolation, arming, and fail-closed production deploy gates.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

export ISOLATE_SOURCE_ONLY=1
export SCHEDULED_DEPLOY_SOURCE_ONLY=1
export SYNC_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/isolate_dev_env.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/prod_scheduled_deploy.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/sync_prod_data_to_dev.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/deploy_steps.sh"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

# --- pod profile ---
export PASTOR_GIT_BRANCH=master CPU_ONLY=0 VLLM_MODE=local
unset CLOUDFLARE_TUNNEL_TOKEN || true
profile="$(pastor_pod_profile_print "$DIR")"
printf '%s\n' "$profile" | grep -q '^channel=master$' || fail "profile channel"
printf '%s\n' "$profile" | grep -q '^vllm=local$' || fail "profile local vllm"
printf '%s\n' "$profile" | grep -q '^tunnel=quick$' || fail "profile quick tunnel"
echo secret > "$DIR/.cloudflared-skip"
mkdir -p "$DIR/.cloudflared"
echo token > "$DIR/.cloudflared/tunnel.token"
profile="$(pastor_pod_profile_print "$DIR")"
printf '%s\n' "$profile" | grep -q '^tunnel=named$' || fail "named tunnel"
rm -rf "$DIR/.cloudflared"
export PASTOR_GIT_BRANCH=development CPU_ONLY=1 VLLM_MODE=serverless
profile="$(pastor_pod_profile_print "$DIR")"
printf '%s\n' "$profile" | grep -q '^channel=development$' || fail "dev channel"
printf '%s\n' "$profile" | grep -q '^vllm=serverless$' || fail "dev serverless"

# --- isolation refuses master and live keys ---
echo master > "$DIR/.git_channel"
unset PASTOR_GIT_BRANCH REPO_BRANCH
printf 'DJANGO_SUPERUSER_PASSWORD=not-admin\n' > "$DIR/tokens.test.env"
if isolate_apply "$DIR" 2>/dev/null; then
  fail "isolate must refuse the master channel"
fi
echo development > "$DIR/.git_channel"
printf '%s\n' \
  'STRIPE_SECRET_KEY=sk_live_should_not_stick' \
  'DJANGO_SUPERUSER_PASSWORD=admin123' \
  > "$DIR/tokens.test.env"
if isolate_apply "$DIR" 2>/dev/null; then
  fail "admin123 must abort isolation"
fi
printf '%s\n' \
  'DJANGO_SUPERUSER_PASSWORD=dev-only-secret' \
  'STRIPE_SECRET_KEY=' \
  'PUBLIC_APP_URL=https://dev.example.test' \
  > "$DIR/tokens.test.env"
printf '%s\n' 'STRIPE_SECRET_KEY=sk_live_from_prod' 'GITHUB_TOKEN=ghp_secret' > "$DIR/tokens.env"
touch "$DIR/config.env"
isolate_apply "$DIR" >/dev/null
stripe="$(isolate_env_get "$DIR/tokens.env" "STRIPE_SECRET_KEY")"
[[ -z "$stripe" ]] || fail "missing test stripe key must clear sk_live_, got $stripe"
github="$(isolate_env_get "$DIR/tokens.env" "GITHUB_TOKEN")"
[[ -z "$github" ]] || fail "GITHUB_TOKEN must be cleared from tokens.env"
grep -q 'STRIPE_SECRET_KEY cleared' "$DIR/isolation_report" || fail "report should say stripe was cleared"

# --- sync direction ---
if sync_assert_direction master master 127.0.0.1 http://127.0.0.1:6333 2>/dev/null; then
  fail "sync must refuse a master destination"
fi
sync_assert_direction master development 127.0.0.1 http://127.0.0.1:6333

# --- scheduled deploy ---
export SCHEDULED_SKIP_FETCH=1 SCHEDULED_SKIP_TOOL_CHECKS=1 SCHEDULED_ALLOW_TEST_ENV=1
export DEPLOY_ARM_FILE="$DIR/armed"
export PASTOR_GIT_BRANCH=master
unset DEPLOY_HOOK_CHECKOUT DEPLOY_HOOK_FLUTTER DEPLOY_HOOK_PIP DEPLOY_HOOK_MIGRATE || true
unset DEPLOY_HOOK_START DEPLOY_HOOK_HEALTH DEPLOY_HOOK_DUMP DEPLOY_HOOK_RESTORE DEPLOY_HOOK_ROLLBACK || true
unset DEPLOY_HOOK_PREFLIGHT_HEALTH || true
rm -f "$DEPLOY_ARM_FILE"
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "2" ]] || fail "unarmed deploy should return 2, got $code"

mkdir -p "$DIR/frontend/build/web" "$DIR/backend/app" "$DIR/venv/bin" "$DIR/release"
echo '<html>live</html>' > "$DIR/frontend/build/web/index.html"
echo 'print(1)' > "$DIR/venv/bin/python"
chmod +x "$DIR/venv/bin/python"
SHA=abc123
printf 'SHA=%s\nHEALTH=ok\nISOLATION=ok\n' "$SHA" > "$DIR/release/${SHA}.manifest"
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
export SCHEDULED_ORIGIN_MASTER="$SHA"
CHECKED_OUT=0
prod_scheduled_deploy "$DIR" || true
[[ "$CHECKED_OUT" == "0" ]] || fail "preflight without flutter hook should not be the issue"
# Missing required key fails before checkout.
printf 'REQUIRED STRIPE_SECRET_KEY\n' >> "$DIR/release/${SHA}.manifest"
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
touch "$DIR/tokens.env"
export DEPLOY_HOOK_CHECKOUT='checkout_hook'
checkout_hook() { CHECKED_OUT=1; }
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "1" ]] || fail "missing key should fail preflight"
[[ "$CHECKED_OUT" == "0" ]] || fail "preflight failure must not checkout"
[[ ! -f "$DEPLOY_ARM_FILE" ]] || fail "preflight failure must clear the arm file"
[[ -f "$DIR/frontend/build/web/index.html" ]] || fail "live web build must remain"

# Flutter failure leaves the live build.
printf 'SHA=%s\nHEALTH=ok\nISOLATION=ok\n' "$SHA" > "$DIR/release/${SHA}.manifest"
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
export DEPLOY_HOOK_FLUTTER='flutter_fail'
flutter_fail() { return 1; }
export DEPLOY_HOOK_ROLLBACK='rollback_hook'
ROLLED=0
rollback_hook() { ROLLED=1; }
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "1" ]] || fail "flutter failure should fail the job"
[[ "$ROLLED" == "1" ]] || fail "flutter failure should roll the tree back"
grep -q live "$DIR/frontend/build/web/index.html" || fail "live build/web must be untouched"
[[ ! -f "$DEPLOY_ARM_FILE" ]] || fail "arm file must be cleared after flutter failure"

# Health failure restores the previous SHA path and clears the arm.
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
unset DEPLOY_HOOK_FLUTTER
export DEPLOY_HOOK_FLUTTER='flutter_ok'
flutter_ok() {
  mkdir -p "$2"
  echo '<html>new</html>' > "$2/index.html"
}
export DEPLOY_HOOK_PIP='ok_hook'
export DEPLOY_HOOK_MIGRATE='ok_hook'
export DEPLOY_HOOK_DUMP='dump_ok'
export DEPLOY_HOOK_START='ok_hook'
export DEPLOY_HOOK_HEALTH='health_fail'
ok_hook() { return 0; }
dump_ok() { echo dump > "$1"; }
health_fail() { return 1; }
export DEPLOY_HOOK_ROLLBACK='rollback_note'
export DEPLOY_HOOK_RESTORE='restore_skip'
restore_skip() { return 0; }
ROLLBACK_SHA=""
rollback_note() { ROLLBACK_SHA="$2"; echo previous > "$DIR/release/rolled"; }
# previous.sha is written by deploy_record_previous from git. Plant it via hook after record
# by making checkout write it... record happens before checkout. No .git so previous.sha
# may be empty. Seed a git repo so the recorded SHA is stable.
git -C "$DIR" init -q
git -C "$DIR" config user.email test@example.com
git -C "$DIR" config user.name test
echo old > "$DIR/README-old"
git -C "$DIR" add README-old
git -C "$DIR" commit -q -m old
OLD="$(git -C "$DIR" rev-parse HEAD)"
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "1" ]] || fail "health failure should fail the job, got $code"
[[ "$ROLLBACK_SHA" == "$OLD" ]] || fail "rollback should receive previous SHA $OLD, got ${ROLLBACK_SHA:-empty}"
[[ ! -f "$DEPLOY_ARM_FILE" ]] || fail "arm file must be cleared after health failure"

# Migrate failure restores the dump.
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
export DEPLOY_HOOK_MIGRATE='migrate_fail'
export DEPLOY_HOOK_HEALTH='ok_hook'
migrate_fail() { return 1; }
export DEPLOY_HOOK_RESTORE='restore_note'
RESTORED=0
restore_note() { RESTORED=1; }
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "1" ]] || fail "migrate failure should fail"
[[ "$RESTORED" == "1" ]] || fail "migrate failure must restore the dump"
[[ ! -f "$DEPLOY_ARM_FILE" ]] || fail "arm file cleared after migrate failure"

# Success clears the arm and swaps the build.
printf '%s\n' "$SHA" > "$DEPLOY_ARM_FILE"
export DEPLOY_HOOK_MIGRATE='ok_hook'
unset DEPLOY_HOOK_RESTORE
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "0" ]] || fail "healthy deploy should succeed, got $code"
[[ ! -f "$DEPLOY_ARM_FILE" ]] || fail "success must clear the arm file"
grep -q new "$DIR/frontend/build/web/index.html" || fail "staging build should be swapped in"

# SHA mismatch skips and keeps the arm file.
printf 'other\n' > "$DEPLOY_ARM_FILE"
export SCHEDULED_ORIGIN_MASTER="$SHA"
code=0
prod_scheduled_deploy "$DIR" || code=$?
[[ "$code" == "2" ]] || fail "SHA mismatch should skip, got $code"
[[ -f "$DEPLOY_ARM_FILE" ]] || fail "SHA mismatch must leave the arm file"

grep -q 'deploy_flutter_staging' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must stage the Flutter build"
grep -q 'deploy_health_localhost' "$ROOT/deploy_update.sh" || fail "deploy_update.sh health checks must fail the script"
if grep -q "auth/config/.*|| true" "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not ignore health-check failures"
fi

# Health checks retry until Django is listening.
unset DEPLOY_HOOK_HEALTH
health_dir="$(mktemp -d)"
cat > "$health_dir/curl" <<EOF
#!/bin/bash
f="$health_dir/n"
n=\$(cat "\$f" 2>/dev/null || echo 0)
n=\$((n + 1))
echo "\$n" > "\$f"
if [[ "\$n" -le 3 ]]; then printf 000; else printf 200; fi
EOF
chmod +x "$health_dir/curl"
PATH="$health_dir:$PATH" DEPLOY_HEALTH_ATTEMPTS=4 DEPLOY_HEALTH_INTERVAL=0 DEPLOY_SKIP_GPU=1 \
  deploy_health_localhost 8000 || fail "health check should wait for Django"
printf '%s\n' '#!/bin/bash' 'printf 000' > "$health_dir/curl"
code=0
PATH="$health_dir:$PATH" DEPLOY_HEALTH_ATTEMPTS=2 DEPLOY_HEALTH_INTERVAL=0 \
  deploy_health_localhost 8000 || code=$?
[[ "$code" == "1" ]] || fail "health check should fail when Django stays down"
rm -rf "$health_dir"

# Dev smoke records success only when the hook says the endpoint answered.
# shellcheck source=/dev/null
source "$ROOT/scripts/gpu_smoke.sh"
gpu_mark() { PASTOR_GPU_SMOKE=1; }
GPU_SMOKE_HOOK=true pastor_serverless_gpu_smoke
[[ "${PASTOR_GPU_SMOKE:-0}" == "0" ]] || fail "smoke hook must set the flag itself"
GPU_SMOKE_HOOK=gpu_mark pastor_serverless_gpu_smoke
[[ "$PASTOR_GPU_SMOKE" == "1" ]] || fail "smoke hook should be able to mark GPU_SMOKE"
unset GPU_SMOKE_HOOK
RUNPOD_VLLM_ENDPOINT_ID="" RUNPOD_API_KEY="" pastor_serverless_gpu_smoke
[[ "$PASTOR_GPU_SMOKE" == "0" ]] || fail "missing endpoint must leave GPU_SMOKE=0"

# Production cron install is master-only and does not create an arm file.
# shellcheck source=/dev/null
source "$ROOT/scripts/install_prod_deploy_cron.sh"
cron_ws="$(mktemp -d)"
printf 'development\n' > "$cron_ws/.git_channel"
PASTOR_GIT_BRANCH="" REPO_BRANCH="" pastor_ensure_prod_cron "$cron_ws"
[[ ! -e "$cron_ws/logs/scheduled-deploy.log" ]] || fail "development boot must not install the production cron"
rm -rf "$cron_ws"

echo "OK dev pipeline gates"
