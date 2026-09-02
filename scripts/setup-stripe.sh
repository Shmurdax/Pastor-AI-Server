#!/usr/bin/env bash
# Validate Stripe test keys and enable real Embedded Checkout (disable mock billing).
#
# Keys can live in any of:
#   1. Cursor environment secrets (STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, …)
#   2. tokens.env  →  apply-tokens.sh copies into config.env
#   3. config.env directly
#
# Usage:
#   bash scripts/setup-stripe.sh              # validate + apply
#   bash scripts/setup-stripe.sh --restart    # apply + restart services
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
VENV="${VENV_DIR:-$WS/venv}"
RESTART=0

if [[ "${1:-}" == "--restart" ]]; then
  RESTART=1
fi

log()  { echo -e "\033[0;32m[stripe]\033[0m $*"; }
warn() { echo -e "\033[1;33m[stripe]\033[0m $*"; }
die()  { echo -e "\033[0;31m[stripe]\033[0m $*" >&2; exit 1; }

if [[ ! -f "$CONFIG" ]]; then
  if [[ -f "$WS/config.env.example" ]]; then
    cp "$WS/config.env.example" "$CONFIG"
    log "Created $CONFIG from example."
  else
    die "Missing $CONFIG — run install.sh first."
  fi
fi

# Apply tokens.env + environment secret overrides into config.env.
bash "$WS/apply-tokens.sh"

# shellcheck disable=SC1090
set -a
source "$CONFIG"
set +a

_merge_env_overrides() {
  local key val
  for key in STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET \
    STRIPE_PRICE_MONTHLY STRIPE_PRICE_YEARLY PUBLIC_APP_URL BILLING_MOCK_CHECKOUT; do
    val="${!key:-}"
    [[ -n "$val" ]] || continue
    export "$key=$val"
  done
}
_merge_env_overrides

SK="${STRIPE_SECRET_KEY:-}"
PK="${STRIPE_PUBLISHABLE_KEY:-}"
WH="${STRIPE_WEBHOOK_SECRET:-}"

[[ -n "$SK" ]] || die "STRIPE_SECRET_KEY is empty. Add sk_test_… to tokens.env or environment secrets."
[[ -n "$PK" ]] || die "STRIPE_PUBLISHABLE_KEY is empty. Add pk_test_… to tokens.env or environment secrets."

case "$SK" in
  sk_test_*) log "Secret key looks like Stripe test mode." ;;
  sk_live_*) warn "Secret key is LIVE mode — use sk_test_… for testing." ;;
  *) warn "Secret key does not start with sk_test_ or sk_live_." ;;
esac

case "$PK" in
  pk_test_*) log "Publishable key looks like Stripe test mode." ;;
  pk_live_*) warn "Publishable key is LIVE mode — use pk_test_… for testing." ;;
esac

# Force real checkout when keys are present (unless explicitly overridden).
if [[ -z "${BILLING_MOCK_CHECKOUT:-}" ]]; then
  export BILLING_MOCK_CHECKOUT=false
fi

upsert_config() {
  local key="$1" val="${2:-}"
  [[ -z "$val" ]] && return 0
  local esc
  esc="$(printf '%s' "$val" | sed -e 's/[\\/&]/\\&/g')"
  if grep -q "^${key}=" "$CONFIG" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${esc}|" "$CONFIG"
  else
    echo "${key}=${val}" >> "$CONFIG"
  fi
}

upsert_config STRIPE_SECRET_KEY "$SK"
upsert_config STRIPE_PUBLISHABLE_KEY "$PK"
[[ -n "$WH" ]] && upsert_config STRIPE_WEBHOOK_SECRET "$WH"
upsert_config BILLING_MOCK_CHECKOUT "${BILLING_MOCK_CHECKOUT:-false}"
[[ -n "${PUBLIC_APP_URL:-}" ]] && upsert_config PUBLIC_APP_URL "$PUBLIC_APP_URL"
[[ -n "${STRIPE_PRICE_MONTHLY:-}" ]] && upsert_config STRIPE_PRICE_MONTHLY "$STRIPE_PRICE_MONTHLY"
[[ -n "${STRIPE_PRICE_YEARLY:-}" ]] && upsert_config STRIPE_PRICE_YEARLY "$STRIPE_PRICE_YEARLY"

log "Wrote Stripe settings to $CONFIG"

# Validate keys against Stripe API.
if [[ ! -x "$VENV/bin/python" ]]; then
  warn "Python venv missing at $VENV — skipping live API validation."
else
  "$VENV/bin/pip" install -q 'stripe>=11.0.0' 2>/dev/null || true
  if "$VENV/bin/python" - <<'PY' "$SK"
import sys
import stripe

stripe.api_key = sys.argv[1]
try:
    acct = stripe.Account.retrieve()
    print(f"Stripe account: {acct.get('id', '?')} ({acct.get('settings', {}).get('dashboard', {}).get('display_name') or 'unnamed'})")
except stripe.error.AuthenticationError:
    print("ERROR: Invalid STRIPE_SECRET_KEY — authentication failed.", file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f"ERROR: Stripe API check failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
  then
    log "Stripe API authentication OK."
  else
    die "Stripe secret key validation failed."
  fi
fi

echo ""
log "Checkout is configured for real Stripe Embedded Checkout."
log "  configured=true, mock_checkout=${BILLING_MOCK_CHECKOUT:-false}"
if [[ -z "$WH" ]]; then
  warn "STRIPE_WEBHOOK_SECRET is not set — checkout.session.completed webhooks will not sync."
  warn "For local testing run: stripe listen --forward-to localhost:8000/api/billing/webhook/"
  warn "Then paste the whsec_… signing secret into tokens.env and re-run this script."
fi
if [[ -z "${PUBLIC_APP_URL:-}" ]]; then
  warn "PUBLIC_APP_URL is not set — return_url will use the browser Origin header."
fi
echo ""
log "Test card: 4242 4242 4242 4242 · any future expiry · any CVC · any ZIP"
echo ""

if [[ "$RESTART" -eq 1 ]]; then
  log "Restarting services…"
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$WS}" bash "$WS/start.sh"
fi
