#!/usr/bin/env bash
# Install the production cron once. It does not arm a deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${WORKSPACE_ROOT:-$ROOT}"
TZ_NAME="${PROD_DEPLOY_TZ:-America/Chicago}"
LOG="$WS/logs/scheduled-deploy.log"
CMD="CRON_TZ=${TZ_NAME}
0 1 * * * bash $WS/scripts/prod_scheduled_deploy.sh >> $LOG 2>&1
"
mkdir -p "$WS/logs"
if crontab -l >/dev/null 2>&1; then
  crontab -l | grep -v 'prod_scheduled_deploy.sh' > /tmp/pastor-cron.$$ || true
else
  : > /tmp/pastor-cron.$$
fi
printf '%s\n' "$CMD" >> /tmp/pastor-cron.$$
crontab /tmp/pastor-cron.$$
rm -f /tmp/pastor-cron.$$
echo "Installed 01:00 ${TZ_NAME} cron. It stays quiet until arm_prod_deploy.sh is run."
