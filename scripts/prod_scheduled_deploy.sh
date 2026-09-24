#!/usr/bin/env bash
# 1:00am production gate. Does nothing unless /workspace/persistent/deploy/armed
# names the current origin/master SHA. On failure, returns to the previous
# commit and web build. Restores the predeploy dump only when migrate failed
# or the previous process cannot become healthy.
#
# Tests: SCHEDULED_DEPLOY_SOURCE_ONLY=1 source scripts/prod_scheduled_deploy.sh
set -euo pipefail

_sched_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$_sched_root/git_channel.sh"
# shellcheck source=/dev/null
source "$_sched_root/pod_profile.sh"
# shellcheck source=/dev/null
source "$_sched_root/deploy_steps.sh"

sched_log() { echo "[scheduled-deploy] $*"; }

# Cron's PATH is /usr/bin:/bin. deploy_update.sh adds the SDK; this job must too.
sched_prepare_env() {
  local ws="$1"
  if [[ -f "$ws/scripts/load_env.sh" && -f "$ws/config.env" ]]; then
    # shellcheck source=/dev/null
    source "$ws/scripts/load_env.sh"
    pastor_load_env_file "$ws/config.env"
  fi
  if [[ -x "$ws/.flutter-sdk/bin/flutter" ]]; then
    export PATH="$ws/.flutter-sdk/bin:$PATH"
  fi
  if [[ -x "$ws/venv/bin/python" ]]; then
    export PATH="$ws/venv/bin:$PATH"
  fi
  if [[ "${SCHEDULED_SKIP_TOOL_CHECKS:-0}" != "1" && -f "$ws/scripts/git_safe_directory.sh" ]]; then
    # shellcheck source=/dev/null
    source "$ws/scripts/git_safe_directory.sh"
    pastor_allow_git_on_runpod_volume "$ws"
  fi
}

sched_arm_file() {
  printf '%s\n' "${DEPLOY_ARM_FILE:-${PERSIST_ROOT:-/workspace/persistent}/deploy/armed}"
}

sched_clear_arm() {
  rm -f "$(sched_arm_file)"
}

sched_preflight() {
  local ws="$1" sha="$2" manifest="$3"
  local channel disk_kb free_mib flutter_bin
  channel="$(pastor_git_channel "$ws")"
  [[ "$channel" == "master" ]] || { sched_log "preflight: channel is $channel"; return 1; }
  [[ "${PASTOR_ENV:-}" != "development" ]] || { sched_log "preflight: PASTOR_ENV=development"; return 1; }
  [[ ! -f "$ws/tokens.test.env" || "${SCHEDULED_ALLOW_TEST_ENV:-0}" == "1" ]] || {
    sched_log "preflight: tokens.test.env is present on production"
    return 1
  }
  [[ -f "$manifest" ]] || { sched_log "preflight: missing release manifest"; return 1; }
  local key
  while read -r key; do
    [[ -n "$key" ]] || continue
    grep -q -E "^${key}=.+" "$ws/tokens.env" || {
      sched_log "preflight: production tokens.env missing $key"
      return 1
    }
  done < <(awk '/^REQUIRED /{print $2}' "$manifest")
  flutter_bin="$(command -v flutter || true)"
  [[ -n "$flutter_bin" || "${SCHEDULED_SKIP_TOOL_CHECKS:-0}" == "1" ]] || {
    sched_log "preflight: flutter is not on PATH"
    return 1
  }
  [[ -x "$ws/venv/bin/python" || "${SCHEDULED_SKIP_TOOL_CHECKS:-0}" == "1" ]] || {
    sched_log "preflight: venv missing"
    return 1
  }
  if [[ "${SCHEDULED_SKIP_TOOL_CHECKS:-0}" != "1" ]]; then
    disk_kb="$(df -Pk "$ws" | awk 'NR==2 {print $4}')"
    [[ "${disk_kb:-0}" -ge "${MIN_FREE_DISK_KB:-1048576}" ]] || {
      sched_log "preflight: low disk (${disk_kb:-0} KB free)"
      return 1
    }
    if pastor_has_gpu; then
      free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || true)"
      if [[ "$free_mib" =~ ^[0-9]+$ && "$free_mib" -lt "${MIN_FREE_GPU_MIB:-8000}" ]]; then
        sched_log "preflight: GPU has ${free_mib} MiB free"
        return 1
      fi
    fi
    deploy_health_localhost "${DJANGO_PORT:-8000}" || {
      sched_log "preflight: current site is unhealthy"
      return 1
    }
  fi
  if [[ -n "${DEPLOY_HOOK_PREFLIGHT_HEALTH:-}" ]]; then
    "$DEPLOY_HOOK_PREFLIGHT_HEALTH" || return 1
  fi
  sched_log "preflight ok for $sha"
}

# Returns 0 when the job ran (success or handled failure), 2 when skipped.
prod_scheduled_deploy() {
  local ws="${1:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}"
  local arm sha armed manifest frontend dump
  sched_prepare_env "$ws"
  arm="$(sched_arm_file)"
  if [[ ! -f "$arm" ]]; then
    sched_log "skipped: not armed"
    return 2
  fi
  armed="$(tr -d '[:space:]' < "$arm")"
  if [[ -d "$ws/.git" && "${SCHEDULED_SKIP_FETCH:-0}" != "1" ]]; then
    git -C "$ws" fetch origin master >/dev/null 2>&1 || true
    sha="$(git -C "$ws" rev-parse origin/master 2>/dev/null || true)"
  else
    sha="${SCHEDULED_ORIGIN_MASTER:-$armed}"
  fi
  if [[ -z "$sha" || "$armed" != "$sha" ]]; then
    sched_log "skipped: armed SHA ${armed:-empty} does not match origin/master ${sha:-unknown}"
    return 2
  fi
  manifest="$ws/release/${sha}.manifest"
  if ! sched_preflight "$ws" "$sha" "$manifest"; then
    sched_log "preflight failed; arm cleared; live site unchanged"
    sched_clear_arm
    return 1
  fi

  frontend="$ws/frontend"
  deploy_record_previous "$ws"
  if ! deploy_checkout "$ws" master; then
    sched_log "checkout failed; live site unchanged"
    sched_clear_arm
    return 1
  fi
  if ! deploy_flutter_staging "$frontend"; then
    sched_log "flutter staging build failed; restoring previous tree"
    deploy_rollback_code "$ws" || true
    sched_clear_arm
    return 1
  fi

  dump="${PERSIST_ROOT:-/workspace/persistent}/postgres/predeploy-${sha}.dump"
  deploy_pg_dump "$dump" "${POSTGRES_DB:-ai_db}"

  if ! deploy_pip "$ws/backend/app" "$ws/venv"; then
    sched_log "pip failed before migrate"
    deploy_rollback_code "$ws" || true
    sched_clear_arm
    return 1
  fi
  if ! deploy_migrate "$ws/backend/app"; then
    sched_log "ROLLBACK migrate failed; restoring predeploy dump"
    deploy_pg_restore "$dump" "${POSTGRES_DB:-ai_db}" || true
    deploy_rollback_code "$ws" || true
    sched_clear_arm
    echo "ROLLBACK dump restored from $dump" 
    return 1
  fi
  deploy_swap_web "$frontend"
  deploy_start "$ws" || true
  if ! deploy_health_localhost "${DJANGO_PORT:-8000}"; then
    sched_log "ROLLBACK new process unhealthy; returning to previous SHA"
    deploy_rollback_code "$ws" || true
    deploy_start "$ws" || true
    if ! deploy_health_localhost "${DJANGO_PORT:-8000}"; then
      sched_log "ROLLBACK previous process unhealthy; restoring predeploy dump"
      deploy_pg_restore "$dump" "${POSTGRES_DB:-ai_db}" || true
      deploy_start "$ws" || true
      echo "ROLLBACK dump restored from $dump"
    else
      echo "ROLLBACK code restored; new schema left in place"
    fi
    sched_clear_arm
    return 1
  fi
  sched_log "success $sha"
  sched_clear_arm
  return 0
}

if [[ "${SCHEDULED_DEPLOY_SOURCE_ONLY:-0}" != "1" && "${BASH_SOURCE[0]}" == "$0" ]]; then
  prod_scheduled_deploy "${WORKSPACE_ROOT:-/workspace/pastor-ai}"
fi
