#!/usr/bin/env bash
# Cron entry point. The crontab must not contain % (cron treats it as a newline).
# Fires from minute 0 of every UTC hour and continues only at 02:00 America/Chicago.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hour="$(TZ="${PROD_DEPLOY_TZ:-America/Chicago}" date +%H)"
[[ "$hour" == "02" ]] || exit 0
exec bash "$ROOT/scripts/prod_scheduled_deploy.sh"
