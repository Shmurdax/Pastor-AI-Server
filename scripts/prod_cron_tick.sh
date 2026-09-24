#!/usr/bin/env bash
# Cron entry point. The crontab must not contain % (cron treats it as a newline).
# Fires from minute 0 of every UTC hour and continues only at 01:00 America/Chicago.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hour="$(TZ="${PROD_DEPLOY_TZ:-America/Chicago}" date +%H)"
[[ "$hour" == "01" ]] || exit 0
if [[ -x "$ROOT/.flutter-sdk/bin/flutter" ]]; then
  export PATH="$ROOT/.flutter-sdk/bin:$PATH"
fi
if [[ -x "$ROOT/venv/bin/python" ]]; then
  export PATH="$ROOT/venv/bin:$PATH"
fi
exec bash "$ROOT/scripts/prod_scheduled_deploy.sh"
