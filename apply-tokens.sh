#!/usr/bin/env bash
# Apply tokens.env into config.env (and optionally restart services).
# Usage:
#   bash apply-tokens.sh                        # update config.env only
#   bash apply-tokens.sh --restart              # update + bash start.sh
#   bash apply-tokens.sh --validate-stripe      # also verify Stripe keys via API
#   bash apply-tokens.sh --validate-stripe --restart
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKENS="${TOKENS_FILE:-$WS/tokens.env}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
VENV="${VENV_DIR:-$WS/venv}"
VALIDATE_STRIPE=0
RESTART=0

for arg in "$@"; do
  case "$arg" in
    --validate-stripe) VALIDATE_STRIPE=1 ;;
    --restart) RESTART=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: bash apply-tokens.sh [--validate-stripe] [--restart]" >&2
      exit 1
      ;;
  esac
done

stripe_log()  { echo -e "\033[0;32m[stripe]\033[0m $*"; }
stripe_warn() { echo -e "\033[1;33m[stripe]\033[0m $*"; }
stripe_die()  { echo -e "\033[0;31m[stripe]\033[0m $*" >&2; exit 1; }

# Keys that may come from Cursor environment secrets or CI (override tokens.env).
STRIPE_ENV_KEYS=(
  STRIPE_SECRET_KEY
  STRIPE_PUBLISHABLE_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_MONTHLY
  STRIPE_PRICE_YEARLY
  PUBLIC_APP_URL
  BILLING_MOCK_CHECKOUT
)

_merge_env_overrides() {
  local key val
  for key in "${STRIPE_ENV_KEYS[@]}"; do
    val="${ENV_SECRET_OVERRIDE[$key]:-${!key:-}}"
    [[ -n "$val" ]] || continue
    export "$key=$val"
  done
}

_has_stripe_env_secrets() {
  local key
  for key in STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY; do
    [[ -n "${ENV_SECRET_OVERRIDE[$key]:-$(printenv "$key" 2>/dev/null || true)}" ]] || return 1
  done
}

# Capture Cursor/CI secrets before tokens.env can blank them with empty assignments.
declare -A ENV_SECRET_OVERRIDE=()
for key in "${STRIPE_ENV_KEYS[@]}"; do
  val="$(printenv "$key" 2>/dev/null || true)"
  [[ -n "$val" ]] && ENV_SECRET_OVERRIDE[$key]="$val"
done

_load_tokens_env() {
  # Empty STRIPE_*= lines in tokens.env must not wipe Cursor-injected secrets.
  local filtered
  filtered="$(mktemp)"
  grep -v -E '^(STRIPE_SECRET_KEY|STRIPE_PUBLISHABLE_KEY|STRIPE_WEBHOOK_SECRET|STRIPE_PRICE_MONTHLY|STRIPE_PRICE_YEARLY|PUBLIC_APP_URL|BILLING_MOCK_CHECKOUT)=$' \
    "$TOKENS" > "$filtered"
  # shellcheck disable=SC1090
  set -a
  source "$filtered"
  set +a
  rm -f "$filtered"
}

if [[ ! -f "$TOKENS" ]]; then
  if _has_stripe_env_secrets; then
    echo "Using Stripe keys from environment (no $TOKENS yet)."
  elif [[ -f "$WS/tokens.env.example" ]]; then
    cp "$WS/tokens.env.example" "$TOKENS"
    echo "Created $TOKENS from example — edit it, paste tokens, re-run this script."
    echo "Or add STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY as environment secrets."
    exit 1
  else
    echo "Missing $TOKENS" >&2
    exit 1
  fi
else
  _load_tokens_env
fi

_merge_env_overrides

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run install.sh first (or create config.env)." >&2
  exit 1
fi

upsert() {
  local key="$1" val="${2:-}"
  [[ -z "$val" ]] && return 0
  # Skip unedited placeholders
  case "$val" in
    *paste_here*|hf_paste_here|ghp_paste_here|sk_test_paste_here|pk_test_paste_here) return 0 ;;
  esac
  if grep -q "^${key}=" "$CONFIG" 2>/dev/null; then
    # Escape sed specials in value
    local esc
    esc="$(printf '%s' "$val" | sed -e 's/[\\/&]/\\&/g')"
    sed -i "s|^${key}=.*|${key}=${esc}|" "$CONFIG"
  else
    echo "${key}=${val}" >> "$CONFIG"
  fi
  echo "  updated ${key}"
}

echo "Applying tokens from $TOKENS → $CONFIG"

# Mirror HF tokens both ways if only one is set
if [[ -n "${HF_TOKEN:-}" && -z "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
  HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
fi
if [[ -n "${HUGGING_FACE_HUB_TOKEN:-}" && -z "${HF_TOKEN:-}" ]]; then
  HF_TOKEN="$HUGGING_FACE_HUB_TOKEN"
fi

upsert HF_TOKEN "${HF_TOKEN:-}"
upsert HUGGING_FACE_HUB_TOKEN "${HUGGING_FACE_HUB_TOKEN:-}"
upsert NGROK_AUTH_TOKEN "${NGROK_AUTH_TOKEN:-}"
upsert NGROK_DOMAIN "${NGROK_DOMAIN:-}"
upsert TUNNEL "${TUNNEL:-}"
upsert PUBLIC_DOMAIN "${PUBLIC_DOMAIN:-}"
upsert CLOUDFLARE_TUNNEL_TOKEN "${CLOUDFLARE_TUNNEL_TOKEN:-}"
upsert DJANGO_SECRET_KEY "${DJANGO_SECRET_KEY:-}"
upsert POSTGRES_PASSWORD "${POSTGRES_PASSWORD:-}"
upsert PUBLIC_API_KEY "${PUBLIC_API_KEY:-}"
upsert GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID:-}"
upsert STRIPE_SECRET_KEY "${STRIPE_SECRET_KEY:-}"
upsert STRIPE_PUBLISHABLE_KEY "${STRIPE_PUBLISHABLE_KEY:-}"
upsert STRIPE_WEBHOOK_SECRET "${STRIPE_WEBHOOK_SECRET:-}"
upsert STRIPE_PRICE_MONTHLY "${STRIPE_PRICE_MONTHLY:-}"
upsert STRIPE_PRICE_YEARLY "${STRIPE_PRICE_YEARLY:-}"
upsert PUBLIC_APP_URL "${PUBLIC_APP_URL:-}"
upsert BILLING_MOCK_CHECKOUT "${BILLING_MOCK_CHECKOUT:-}"
upsert VIMEO_ACCESS_TOKEN "${VIMEO_ACCESS_TOKEN:-}"
upsert VIMEO_FOLDER_ID "${VIMEO_FOLDER_ID:-}"
upsert VIMEO_USER_ID "${VIMEO_USER_ID:-}"
upsert VIMEO_SHOWCASE_ID "${VIMEO_SHOWCASE_ID:-}"
upsert VIMEO_FREE_PREVIEW_ID "${VIMEO_FREE_PREVIEW_ID:-}"

# Auto-disable mock checkout when real Stripe test/live keys are configured.
if [[ -n "${STRIPE_SECRET_KEY:-}" && -n "${STRIPE_PUBLISHABLE_KEY:-}" ]]; then
  case "${STRIPE_SECRET_KEY}${STRIPE_PUBLISHABLE_KEY}" in
    *paste_here*) ;;
    *)
      if [[ -z "${BILLING_MOCK_CHECKOUT:-}" ]]; then
        BILLING_MOCK_CHECKOUT=false
      fi
      upsert BILLING_MOCK_CHECKOUT "${BILLING_MOCK_CHECKOUT:-false}"
      ;;
  esac
fi

# Persist GitHub push helper (not required by runtime services)
if [[ -n "${GITHUB_TOKEN:-}" && "${GITHUB_TOKEN}" != *paste_here* ]]; then
  upsert GITHUB_TOKEN "${GITHUB_TOKEN}"
  upsert GITHUB_USER "${GITHUB_USER:-GavWrecker}"
  upsert GITHUB_REPO "${GITHUB_REPO:-GavWrecker/Pastor-AI-Server}"
fi

# Write HF token file for huggingface_hub / vLLM if present
if [[ -n "${HF_TOKEN:-}" && "${HF_TOKEN}" != *paste_here* ]]; then
  mkdir -p "${HF_HOME:-$WS/hf_cache}" "$WS/.huggingface"
  printf '%s' "$HF_TOKEN" > "${HF_HOME:-$WS/hf_cache}/token"
  printf '%s' "$HF_TOKEN" > "$WS/.huggingface/token"
  chmod 600 "${HF_HOME:-$WS/hf_cache}/token" "$WS/.huggingface/token" 2>/dev/null || true
  echo "  wrote HF token files"
fi

# Keep the named Cloudflare tunnel token on the network volume so remigration
# can restore it even if /workspace/pastor-ai/.cloudflared is wiped.
if [[ -f "$WS/persist_runtime.sh" ]]; then
  log()  { echo "  $*"; }
  warn() { echo "  $*" >&2; }
  # shellcheck disable=SC1091
  source "$WS/persist_runtime.sh"
  if [[ -n "$(resolve_cloudflare_tunnel_token_file 2>/dev/null || true)" ]]; then
    echo "  persisted Cloudflare tunnel token onto ${PERSIST_TUNNEL_TOKEN:-$PERSIST_ROOT/.cloudflared/tunnel.token}"
  fi
fi

_validate_stripe_keys() {
  local sk="${STRIPE_SECRET_KEY:-}" pk="${STRIPE_PUBLISHABLE_KEY:-}" wh="${STRIPE_WEBHOOK_SECRET:-}"

  [[ -n "$sk" ]] || stripe_die "STRIPE_SECRET_KEY is empty. Add sk_test_… to tokens.env or environment secrets."
  [[ -n "$pk" ]] || stripe_die "STRIPE_PUBLISHABLE_KEY is empty. Add pk_test_… to tokens.env or environment secrets."

  case "$sk" in
    sk_test_*) stripe_log "Secret key looks like Stripe test mode." ;;
    sk_live_*) stripe_warn "Secret key is LIVE mode — use sk_test_… for testing." ;;
    *) stripe_warn "Secret key does not start with sk_test_ or sk_live_." ;;
  esac

  case "$pk" in
    pk_test_*) stripe_log "Publishable key looks like Stripe test mode." ;;
    pk_live_*) stripe_warn "Publishable key is LIVE mode — use pk_test_… for testing." ;;
  esac

  if [[ ! -x "$VENV/bin/python" ]]; then
    stripe_warn "Python venv missing at $VENV — skipping live API validation."
    return 0
  fi

  "$VENV/bin/pip" install -q 'stripe>=11.0.0' 2>/dev/null || true
  if "$VENV/bin/python" - <<'PY' "$sk"
import sys
import stripe

stripe.api_key = sys.argv[1]
try:
    acct = stripe.Account.retrieve()
    name = getattr(getattr(getattr(acct, "settings", None), "dashboard", None), "display_name", None) or "unnamed"
    print(f"Stripe account: {acct.id} ({name})")
except stripe.error.AuthenticationError:
    print("ERROR: Invalid STRIPE_SECRET_KEY — authentication failed.", file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f"ERROR: Stripe API check failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
  then
    stripe_log "Stripe API authentication OK."
  else
    stripe_die "Stripe secret key validation failed."
  fi

  echo ""
  stripe_log "Checkout is configured for real Stripe Embedded Checkout."
  stripe_log "  configured=true, mock_checkout=${BILLING_MOCK_CHECKOUT:-false}"
  if [[ -z "$wh" ]]; then
    stripe_warn "STRIPE_WEBHOOK_SECRET is not set — checkout.session.completed webhooks will not sync."
    stripe_warn "For local testing run: stripe listen --forward-to localhost:8000/api/billing/webhook/"
    stripe_warn "Then paste the whsec_… signing secret into tokens.env and re-run this script."
  fi
  if [[ -z "${PUBLIC_APP_URL:-}" ]]; then
    stripe_warn "PUBLIC_APP_URL is not set — return_url will use the browser Origin header."
  fi
  echo ""
  stripe_log "Test card: 4242 4242 4242 4242 · any future expiry · any CVC · any ZIP"
  echo ""
}

echo "Done."

if [[ "$VALIDATE_STRIPE" -eq 1 ]]; then
  _validate_stripe_keys
fi

if [[ "$RESTART" -eq 1 ]]; then
  echo "Restarting services..."
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$WS}" bash "$WS/start.sh"
fi
