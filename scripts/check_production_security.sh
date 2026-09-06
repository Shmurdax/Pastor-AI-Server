#!/usr/bin/env bash
# Read-only production security checklist for the RunPod CPU web pod.
# Usage: bash /workspace/pastor-ai/scripts/check_production_security.sh
set -euo pipefail

WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
fail=0
warn() { echo "[!] $*" >&2; fail=1; }
ok() { echo "[ok] $*"; }

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$CONFIG"
set +a

[[ "${DJANGO_DEBUG:-false}" == "true" ]] && warn "DJANGO_DEBUG=true" || ok "DJANGO_DEBUG is not true"
[[ "${DJANGO_CORS_ALLOW_ALL_ORIGINS:-false}" == "true" ]] && warn "CORS allows all origins" || ok "CORS is not wide open"
[[ "${DJANGO_SESSION_COOKIE_SECURE:-}" == "true" ]] && ok "session cookies marked secure" || warn "DJANGO_SESSION_COOKIE_SECURE is not true"
[[ "${DJANGO_CSRF_COOKIE_SECURE:-}" == "true" ]] && ok "CSRF cookies marked secure" || warn "DJANGO_CSRF_COOKIE_SECURE is not true"
[[ "${DJANGO_SUPERUSER_PASSWORD:-}" == "admin123" || -z "${DJANGO_SUPERUSER_PASSWORD:-}" ]] \
  && warn "staff password missing or is the published default" \
  || ok "staff password is set and is not admin123"
[[ "${DJANGO_ADMIN_URL:-}" == "rB4zKwO2wTBCD3pAxRIdTWsvw0w8" ]] \
  && warn "DJANGO_ADMIN_URL is the documented example path" \
  || ok "DJANGO_ADMIN_URL is not the documented example"
[[ "${BILLING_MOCK_CHECKOUT:-}" == "true" || "${BILLING_MOCK_CHECKOUT:-}" == "1" ]] \
  && warn "BILLING_MOCK_CHECKOUT is explicitly enabled" \
  || ok "BILLING_MOCK_CHECKOUT is not explicitly enabled"
[[ -z "${PUBLIC_API_KEY:-}" ]] && warn "PUBLIC_API_KEY empty (public chat/GPU spend)" || ok "PUBLIC_API_KEY is set"
[[ -n "${STRIPE_SECRET_KEY:-}" ]] && ok "Stripe secret is set" || warn "Stripe is not configured (Premium cannot charge)"

if command -v ss >/dev/null 2>&1; then
  if ss -lntp 2>/dev/null | grep -qE '0\.0\.0\.0:6333|:::6333'; then
    warn "Qdrant is listening on all interfaces (:6333)"
  else
    ok "Qdrant is not on 0.0.0.0:6333"
  fi
fi

if command -v ps >/dev/null 2>&1; then
  if ps -eo args= | grep -E 'screen|bash -c' | grep -qE 'RUNPOD_API_KEY=rpa_|STRIPE_SECRET_KEY=sk_'; then
    warn "A process command line appears to contain an API secret (rotate that key)"
  else
    ok "No obvious API secrets in process command lines"
  fi
fi

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "Production checks failed. See warnings above." >&2
  exit 1
fi
echo ""
echo "Production security checklist passed."
