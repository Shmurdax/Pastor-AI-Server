#!/usr/bin/env bash
# Apply tokens.env into config.env (and optionally restart services).
# Usage:
#   bash apply-tokens.sh              # update config.env only
#   bash apply-tokens.sh --restart    # update + bash start.sh
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKENS="${TOKENS_FILE:-$WS/tokens.env}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"

if [[ ! -f "$TOKENS" ]]; then
  if [[ -f "$WS/tokens.env.example" ]]; then
    cp "$WS/tokens.env.example" "$TOKENS"
    echo "Created $TOKENS from example — edit it, paste tokens, re-run this script."
    exit 1
  fi
  echo "Missing $TOKENS" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$TOKENS"
set +a

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run install.sh first (or create config.env)." >&2
  exit 1
fi

upsert() {
  local key="$1" val="${2:-}"
  [[ -z "$val" ]] && return 0
  # Skip unedited placeholders
  case "$val" in
    *paste_here*|hf_paste_here|ghp_paste_here) return 0 ;;
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
upsert DJANGO_SECRET_KEY "${DJANGO_SECRET_KEY:-}"
upsert POSTGRES_PASSWORD "${POSTGRES_PASSWORD:-}"
upsert PUBLIC_API_KEY "${PUBLIC_API_KEY:-}"
upsert GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID:-}"
upsert VIMEO_ACCESS_TOKEN "${VIMEO_ACCESS_TOKEN:-}"
upsert VIMEO_FOLDER_URL "${VIMEO_FOLDER_URL:-}"
upsert STRIPE_SECRET_KEY "${STRIPE_SECRET_KEY:-}"
upsert STRIPE_PUBLISHABLE_KEY "${STRIPE_PUBLISHABLE_KEY:-}"
upsert STRIPE_WEBHOOK_SECRET "${STRIPE_WEBHOOK_SECRET:-}"
upsert STRIPE_PRICE_MONTHLY "${STRIPE_PRICE_MONTHLY:-}"
upsert STRIPE_PRICE_YEARLY "${STRIPE_PRICE_YEARLY:-}"
upsert PUBLIC_APP_URL "${PUBLIC_APP_URL:-}"
upsert BILLING_MOCK_CHECKOUT "${BILLING_MOCK_CHECKOUT:-}"

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

echo "Done."

if [[ "${1:-}" == "--restart" ]]; then
  echo "Restarting services..."
  bash "$WS/start.sh"
fi
