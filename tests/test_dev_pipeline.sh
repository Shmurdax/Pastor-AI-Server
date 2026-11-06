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

# Promote must publish the release manifest with the GitHub login still active.
promote="$ROOT/scripts/promote_to_master.sh"
grep -q 'skipping branch push' "$promote" || fail "promote must still publish when master matches"
grep -q 'refs/pastor/manifests' "$promote" || fail "promote must push the manifest ref"
if grep -q 'manifest ref was not pushed' "$promote"; then
  fail "promote must not ignore a failed manifest push"
fi
if grep -q 'nothing to promote' "$promote"; then
  fail "promote must not exit before the manifest push"
fi
awk '
  /git push "\$REMOTE" "\$REMOTE\/development:master"/ { branch = NR }
  /git push "\$REMOTE" "refs\/pastor\/manifests/ { manifest = NR }
  END {
    if (branch == 0 || manifest == 0 || manifest < branch) exit 1
  }
' "$promote" || fail "manifest push must follow the master push"

grep -q '.flutter-sdk/bin' "$ROOT/scripts/prod_scheduled_deploy.sh" \
  || fail "scheduled deploy must put the Flutter SDK on PATH"
grep -q 'MIN_FREE_GPU_MIB:-1024' "$ROOT/scripts/prod_scheduled_deploy.sh" \
  || fail "scheduled deploy GPU floor must allow a loaded vLLM card"
grep -q "relkind IN ('r','p','v','m')" "$ROOT/scripts/deploy_steps.sh" \
  || fail "restore must give tables back to the app user"
grep -q 'DEPLOY_HEALTH_ATTEMPTS' "$ROOT/scripts/deploy_steps.sh" \
  || fail "health check must retry while Django binds port 8000"
if grep -q 'MIN_FREE_GPU_MIB:-8000' "$ROOT/scripts/prod_scheduled_deploy.sh"; then
  fail "8000 MiB free-GPU floor blocks a loaded production GPU"
fi

health_bin="$(mktemp -d)"
health_count="$health_bin/count"
cat > "$health_bin/curl" <<'EOF'
#!/bin/bash
n=0
[[ -f "$CURL_COUNT_FILE" ]] && n="$(cat "$CURL_COUNT_FILE")"
n=$((n + 1))
printf '%s\n' "$n" > "$CURL_COUNT_FILE"
if [[ "$n" -le "${CURL_FAIL_UNTIL:-0}" ]]; then
  printf '000'
else
  printf '200'
fi
EOF
chmod +x "$health_bin/curl"
saved_path="$PATH"
saved_hook="${DEPLOY_HOOK_HEALTH:-}"
unset DEPLOY_HOOK_HEALTH
export PATH="$health_bin:$PATH"
export CURL_COUNT_FILE="$health_count"
export CURL_FAIL_UNTIL=1 DEPLOY_HEALTH_ATTEMPTS=3 DEPLOY_HEALTH_PAUSE_S=0
deploy_health_localhost 8000 || fail "health check should pass after Django starts answering"
printf '0\n' > "$health_count"
export CURL_FAIL_UNTIL=100 DEPLOY_HEALTH_ATTEMPTS=2
if deploy_health_localhost 8000; then
  fail "health check should fail when port 8000 never answers"
fi
export PATH="$saved_path"
if [[ -n "$saved_hook" ]]; then
  export DEPLOY_HOOK_HEALTH="$saved_hook"
else
  unset DEPLOY_HOOK_HEALTH
fi
rm -rf "$health_bin"

grep -q 'deploy_flutter_staging' "$ROOT/deploy_update.sh" || fail "deploy_update.sh must stage the Flutter build"
grep -q 'deploy_health_localhost' "$ROOT/deploy_update.sh" || fail "deploy_update.sh health checks must fail the script"
if grep -q "auth/config/.*|| true" "$ROOT/deploy_update.sh"; then
  fail "deploy_update.sh must not ignore health-check failures"
fi

# dev_pipeline must bring local Postgres up before migrate, or the rehearsal
# marker stays stale and promote never publishes the manifest arm looks up.
pipeline="$ROOT/scripts/dev_pipeline.sh"
awk '
  /dev_pipeline_ensure_postgres$/ { call = NR }
  /manage.py migrate/ { migrate = NR }
  END {
    if (call == 0 || migrate == 0 || call > migrate) exit 1
  }
' "$pipeline" || fail "dev pipeline must start postgres before migrate"
grep -q 'pg_ctlcluster' "$pipeline" || fail "dev pipeline must start the local postgres cluster"
grep -q 'apt-get install -y postgresql postgresql-contrib' "$pipeline" \
  || fail "dev pipeline must install postgresql when pg_ctlcluster is missing"
grep -q 'PASTOR_KEEP_ALIVE=0 bash "$WS/start.sh"' "$pipeline" \
  || fail "dev pipeline must start Django when port 8000 is closed"
grep -q -- '-f -' "$pipeline" || fail "psql must read SQL from stdin"
if grep -q 'dev_pipeline_psql_as_postgres -c ' "$pipeline"; then
  fail "psql -c must not be passed as a flag or the SQL becomes the database name"
fi
awk '
  /dev_pipeline_ensure_postgres/ { pg = NR }
  /manage.py migrate/ { mig = NR }
  END { if (pg == 0 || mig == 0 || pg > mig) exit 1 }
' "$ROOT/deploy_update.sh" || fail "deploy_update must ensure postgres before migrate"
grep -q 'Django migrations failed' "$ROOT/deploy_update.sh" \
  || fail "deploy_update must stop when migrate fails"
grep -q 'the rehearsal marker was not written' "$pipeline" \
  || fail "dev pipeline must say when postgres blocks the rehearsal marker"

export DEV_PIPELINE_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$pipeline"
[[ "$(dev_pipeline_sql_quote "a'b")" == "'a''b'" ]] || fail "sql quote must escape single quotes"

pg_dir="$DIR/pg-hooks"
mkdir -p "$pg_dir"
pg_ready_yes() { return 0; }
pg_ready_no() { return 1; }
pg_start_mark() { echo started >> "$pg_dir/started"; }
pg_start_forbidden() { echo forbidden >> "$pg_dir/started"; return 1; }
pg_start_no_package() { return 2; }
pg_role_ok() { return 0; }

export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432
export DEV_PIPELINE_PG_ROLE_HOOK=pg_role_ok
export DEV_PIPELINE_PG_READY_HOOK=pg_ready_yes
export DEV_PIPELINE_PG_START_HOOK=pg_start_forbidden
export DEV_PIPELINE_PG_ATTEMPTS=3 DEV_PIPELINE_PG_PAUSE_S=0
rm -f "$pg_dir/started"
dev_pipeline_ensure_postgres || fail "already-ready postgres should succeed"
[[ ! -f "$pg_dir/started" ]] || fail "already-ready postgres must not be restarted"

ready_calls=0
pg_ready_later() {
  ready_calls=$((ready_calls + 1))
  [[ "$ready_calls" -ge 2 ]]
}
export DEV_PIPELINE_PG_READY_HOOK=pg_ready_later
export DEV_PIPELINE_PG_START_HOOK=pg_start_mark
dev_pipeline_ensure_postgres || fail "postgres should succeed after the cluster starts"
[[ "$(wc -l < "$pg_dir/started" | tr -d ' ')" == "1" ]] || fail "down postgres should be started once"
grep -q started "$pg_dir/started" || fail "start hook should record the attempt"

export POSTGRES_HOST=10.1.2.3
export DEV_PIPELINE_PG_READY_HOOK=pg_ready_no
export DEV_PIPELINE_PG_START_HOOK=pg_start_forbidden
rm -f "$pg_dir/started"
if dev_pipeline_ensure_postgres; then
  fail "a down remote postgres must fail the rehearsal"
fi
[[ ! -f "$pg_dir/started" ]] || fail "a remote postgres host must not start the local cluster"

export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432
ready_calls=0
pg_ready_count() {
  ready_calls=$((ready_calls + 1))
  return 1
}
export DEV_PIPELINE_PG_READY_HOOK=pg_ready_count
export DEV_PIPELINE_PG_START_HOOK=pg_start_no_package
export DEV_PIPELINE_PG_ATTEMPTS=10 DEV_PIPELINE_PG_PAUSE_S=5
if dev_pipeline_ensure_postgres; then
  fail "a missing postgresql package must fail the rehearsal"
fi
[[ "$ready_calls" -eq 1 ]] || fail "install failure must not wait out the postgres retry loop, ready_calls=${ready_calls}"

unset DEV_PIPELINE_PG_READY_HOOK DEV_PIPELINE_PG_START_HOOK DEV_PIPELINE_PG_ROLE_HOOK
unset DEV_PIPELINE_PG_ATTEMPTS DEV_PIPELINE_PG_PAUSE_S

# Existence checks must see "1" on stdin-driven psql and must not put SQL in argv.
# A password containing $ and a quote must survive into the CREATE statement.
psql() { :; }
export POSTGRES_USER=pastor POSTGRES_DB=ai_db
export POSTGRES_PASSWORD='p$ass'"'"'w'
: > "$pg_dir/su.txt"
: > "$pg_dir/sql.txt"
su() {
  printf '%s\n' "$*" >> "$pg_dir/su.txt"
  cat >> "$pg_dir/sql.txt"
  printf '\n' >> "$pg_dir/sql.txt"
  if [[ "$*" == *"-tA"* ]]; then
    printf '1\n'
  fi
}
dev_pipeline_ensure_app_database || fail "existing role and database should not be recreated"
grep -q 'psql -v ON_ERROR_STOP=1 -tA -f -' "$pg_dir/su.txt" \
  || fail "role lookup must be: psql -tA -f -"
if grep -q 'SELECT' "$pg_dir/su.txt"; then
  fail "SELECT must be psql stdin, not a connection argument"
fi
grep -q "SELECT 1 FROM pg_roles WHERE rolname='pastor'" "$pg_dir/sql.txt" \
  || fail "role lookup SQL missing from stdin"
if grep -q 'CREATE USER' "$pg_dir/sql.txt"; then
  fail "existing role must not be created again"
fi
grep -q 'GRANT ALL PRIVILEGES ON DATABASE ai_db TO pastor' "$pg_dir/sql.txt" \
  || fail "grant SQL missing from stdin"
if grep -q 'GRANT ALL' "$pg_dir/su.txt"; then
  fail "GRANT must not be passed as the database name"
fi

: > "$pg_dir/su.txt"
: > "$pg_dir/sql.txt"
su() {
  printf '%s\n' "$*" >> "$pg_dir/su.txt"
  cat >> "$pg_dir/sql.txt"
  printf '\n' >> "$pg_dir/sql.txt"
}
dev_pipeline_ensure_app_database || fail "missing role should be created from stdin SQL"
needle="CREATE USER pastor WITH PASSWORD 'p"'$'"ass''w' CREATEDB;"
grep -q -F "$needle" "$pg_dir/sql.txt" || {
  echo "SQL was:" >&2
  cat "$pg_dir/sql.txt" >&2
  fail "password with a dollar and a quote was mangled"
}
unset -f su psql
unset POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT

export PROMOTE_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$promote"
grep -q 'force-with-lease' "$promote" || fail "promote must use force-with-lease when master content is already in development"
grep -q 'these master commits were not rehearsed' "$promote" \
  || fail "promote must name unrehearsed master commits"
if grep -E 'git push .*--force([^-]|$)' "$promote"; then
  fail "promote must not force-push master without a lease"
fi

plan_repo="$DIR/promote-plan"
mkdir -p "$plan_repo"
git -C "$plan_repo" init -q
git -C "$plan_repo" config user.email test@example.com
git -C "$plan_repo" config user.name test
echo base > "$plan_repo/f"
git -C "$plan_repo" add f
git -C "$plan_repo" commit -q -m base
plan_base="$(git -C "$plan_repo" rev-parse HEAD)"
echo dev > "$plan_repo/f"
git -C "$plan_repo" commit -q -am dev
plan_dev="$(git -C "$plan_repo" rev-parse HEAD)"
(
  cd "$plan_repo"
  [[ "$(promote_push_plan "$plan_dev" "$plan_base")" == "ff" ]]
  [[ "$(promote_push_plan "$plan_dev" "$plan_dev")" == "same" ]]
) || fail "promote plan should fast-forward when master is an ancestor"

git -C "$plan_repo" checkout -q -B master "$plan_base"
echo master-only > "$plan_repo/only-on-master"
git -C "$plan_repo" add only-on-master
git -C "$plan_repo" commit -q -m "master only"
plan_master="$(git -C "$plan_repo" rev-parse HEAD)"
(
  cd "$plan_repo"
  [[ "$(promote_push_plan "$plan_dev" "$plan_master")" == "refuse" ]]
) || fail "promote plan must refuse master commits development does not contain"

git -C "$plan_repo" checkout -q -B development "$plan_dev"
echo master-only > "$plan_repo/only-on-master"
git -C "$plan_repo" add only-on-master
git -C "$plan_repo" commit -q -m "same master change on development"
plan_dev_with_master="$(git -C "$plan_repo" rev-parse HEAD)"
(
  cd "$plan_repo"
  [[ "$(promote_push_plan "$plan_dev_with_master" "$plan_master")" == "lease" ]]
) || fail "promote plan should lease-push when master changes are already in the development tree"

grep -q 'refs/pastor/manifests' "$ROOT/scripts/arm_prod_deploy.sh" \
  || fail "arm must say which manifest ref is missing"
grep -q 'promote_to_master.sh publishes that ref' "$ROOT/scripts/arm_prod_deploy.sh" \
  || fail "arm must point at promote when the manifest ref is missing"

echo "OK dev pipeline gates"
