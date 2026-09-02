#!/usr/bin/env bash
# Diagnose Stripe key configuration (never prints full secret values).
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ok()   { echo -e "\033[0;32m[ok]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
bad()  { echo -e "\033[0;31m[✘]\033[0m $*"; }

sk_env_len=${#STRIPE_SECRET_KEY}
pk_env_len=${#STRIPE_PUBLISHABLE_KEY}

echo "Stripe configuration check"
echo "=========================="
echo ""

if [[ "$sk_env_len" -gt 20 && "$pk_env_len" -gt 20 ]]; then
  ok "Cursor environment secrets are injected (STRIPE_SECRET_KEY len=$sk_env_len, STRIPE_PUBLISHABLE_KEY len=$pk_env_len)"
  echo "  Run: bash apply-tokens.sh --validate-stripe --restart"
  exit 0
fi

bad "Cursor environment secrets are NOT injected in this VM"
echo "  STRIPE_SECRET_KEY env length: $sk_env_len"
echo "  STRIPE_PUBLISHABLE_KEY env length: $pk_env_len"
echo ""

if [[ -f "$WS/tokens.env" ]]; then
  sk_file="$(grep '^STRIPE_SECRET_KEY=' "$WS/tokens.env" | cut -d= -f2- || true)"
  pk_file="$(grep '^STRIPE_PUBLISHABLE_KEY=' "$WS/tokens.env" | cut -d= -f2- || true)"
  if [[ ${#sk_file} -gt 20 && ${#pk_file} -gt 20 && "$sk_file" != *paste_here* ]]; then
    ok "tokens.env has Stripe keys — run: bash apply-tokens.sh --validate-stripe"
    exit 0
  fi
  warn "tokens.env exists but STRIPE keys are empty or still placeholders"
else
  warn "No tokens.env — copy tokens.env.example and paste keys"
fi

echo ""
echo "Why dashboard secrets may not appear here:"
echo "  1. Secrets inject only when a NEW agent pod starts (not mid-run)"
echo "  2. They must be saved on the environment for this repo:"
echo "     https://cursor.com/dashboard/cloud-agents/environments/e/bcb5c9c6-814e-11f1-ba66-0e7d0216e441"
echo "  3. Names must match exactly: STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY"
echo "  4. Use Environment secrets (scoped to this env), not empty placeholder values"
echo ""
echo "Reliable workaround (RunPod + Cloud Agent):"
echo "  nano $WS/tokens.env"
echo "  bash apply-tokens.sh --validate-stripe"
echo "  bash scripts/start-minimal.sh"
exit 1
