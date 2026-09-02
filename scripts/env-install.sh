#!/usr/bin/env bash
# Cloud Agent / local minimal install — auth + billing, no vLLM/Qdrant/chat stack.
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV_DIR:-$WS/venv}"
APP_DIR="$WS/backend/app"

python3 -m venv "$VENV" 2>/dev/null || true
"$VENV/bin/pip" install -U pip wheel
"$VENV/bin/pip" install \
  'django>=4.2,<5.0' djangorestframework django-cors-headers \
  gunicorn 'whitenoise[brotli]' stripe google-auth requests psycopg2-binary

if [[ ! -f "$WS/config.env" && -f "$WS/config.env.example" ]]; then
  cp "$WS/config.env.example" "$WS/config.env"
  sed -i "s|/workspace/pastor-ai|$WS|g" "$WS/config.env"
fi

export DJANGO_USE_SQLITE=1
unset POSTGRES_HOST
cd "$APP_DIR"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py ensure_superuser 2>/dev/null || true

echo "env-install.sh complete"
