#!/usr/bin/env bash
# Install the production cron once. It does not arm a deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${WORKSPACE_ROOT:-$ROOT}"
TZ_NAME="${PROD_DEPLOY_TZ:-America/Chicago}"
LOG="$WS/logs/scheduled-deploy.log"
# Minute 0 of every UTC hour. prod_cron_tick.sh continues only at 01:00 Chicago.
# Keep this line free of %; cron turns an unescaped % into a newline.
CMD="0 * * * * bash $WS/scripts/prod_cron_tick.sh >> $LOG 2>&1
"
pastor_relax_cron_pam() {
  local pam="/etc/pam.d/cron"
  [[ -f "$pam" ]] || return 0
  sed -i 's/^\(session[[:space:]]\+\)required\([[:space:]]\+pam_loginuid\.so\)/\1optional\2/' "$pam"
}

pastor_start_cron_daemon() {
  pastor_relax_cron_pam
  if pgrep -x cron >/dev/null 2>&1; then
    kill "$(pgrep -x cron | head -1)" 2>/dev/null || true
    sleep 1
  fi
  if [[ -x /usr/sbin/cron ]]; then
    /usr/sbin/cron || true
  fi
}

pastor_ensure_prod_cron() {
  # Reinstall the 1:00am job after a remigration. Does not arm a deploy.
  local ws="${1:-${WORKSPACE_ROOT:-/workspace/pastor-ai}}"
  local channel="master"
  [[ "${PASTOR_SKIP_CRON:-0}" == "1" ]] && return 0
  if declare -F pastor_git_channel >/dev/null 2>&1; then
    channel="$(pastor_git_channel "$ws")"
  elif [[ -f "$ws/.git_channel" ]]; then
    channel="$(tr -d '[:space:]' < "$ws/.git_channel")"
  fi
  [[ "$channel" == "master" ]] || return 0
  if ! command -v crontab >/dev/null 2>&1 || [[ ! -x /usr/sbin/cron ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || true
    apt-get install -y -qq cron || true
  fi
  pastor_start_cron_daemon
  command -v crontab >/dev/null 2>&1 || return 0
  WORKSPACE_ROOT="$ws" bash "$ws/scripts/install_prod_deploy_cron.sh"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

mkdir -p "$WS/logs"
if crontab -l >/dev/null 2>&1; then
  crontab -l | grep -v -e 'prod_scheduled_deploy.sh' -e 'prod_cron_tick.sh' > /tmp/pastor-cron.$$ || true
else
  : > /tmp/pastor-cron.$$
fi
printf '%s\n' "$CMD" >> /tmp/pastor-cron.$$
crontab /tmp/pastor-cron.$$
rm -f /tmp/pastor-cron.$$
echo "Installed 01:00 ${TZ_NAME} cron. It stays quiet until arm_prod_deploy.sh is run."
