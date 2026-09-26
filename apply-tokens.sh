#!/usr/bin/env bash
# Apply tokens.env into config.env (and optionally restart services).
# Usage:
#   bash apply-tokens.sh              # update config.env only
#   bash apply-tokens.sh --restart    # update + bash start.sh
set -euo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKENS="${TOKENS_FILE:-$WS/tokens.env}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
# shellcheck source=/dev/null
source "$WS/scripts/load_env.sh"

if [[ ! -f "$TOKENS" ]]; then
  if [[ -f "$WS/tokens.env.example" ]]; then
    cp "$WS/tokens.env.example" "$TOKENS"
    echo "Created $TOKENS from example — edit it, paste tokens, re-run this script."
    exit 1
  fi
  echo "Missing $TOKENS" >&2
  exit 1
fi

# Do not `source` tokens.env — apostrophes in DEFAULT_FROM_EMAIL / JSON break bash.
pastor_load_env_file "$TOKENS"

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run install.sh first (or create config.env)." >&2
  exit 1
fi

# Existing pods shipped with noreply@; codes now go out from the ministry inbox.
if [[ -z "${GMAIL_SENDER:-}" || "${GMAIL_SENDER}" == "noreply@thenordins.org" ]]; then
  GMAIL_SENDER="info@thenordins.org"
fi
if [[ -z "${DEFAULT_FROM_EMAIL:-}" || "${DEFAULT_FROM_EMAIL}" == "Nordin's AI <noreply@thenordins.org>" ]]; then
  DEFAULT_FROM_EMAIL="Nordin's AI <info@thenordins.org>"
fi
if [[ -z "${GMAIL_SERVICE_ACCOUNT_FILE:-}" && -f "$WS/secrets/gmail-sender.json" ]]; then
  GMAIL_SERVICE_ACCOUNT_FILE="$WS/secrets/gmail-sender.json"
fi
# One-line JSON in tokens.env is safer as base64 so config.env can still be sourced.
if [[ -n "${GMAIL_SERVICE_ACCOUNT_JSON:-}" && "${GMAIL_SERVICE_ACCOUNT_JSON}" == \{* ]]; then
  if command -v base64 >/dev/null 2>&1; then
    GMAIL_SERVICE_ACCOUNT_JSON="$(
      printf '%s' "$GMAIL_SERVICE_ACCOUNT_JSON" | base64 -w0 2>/dev/null \
        || printf '%s' "$GMAIL_SERVICE_ACCOUNT_JSON" | base64 | tr -d '\n'
    )"
  fi
fi

upsert() {
  local key="$1" val="${2:-}"
  local assign tmp
  [[ -z "$val" ]] && return 0
  # Skip unedited placeholders
  case "$val" in
    *paste_here*|hf_paste_here|ghp_paste_here) return 0 ;;
  esac
  assign="$(pastor_env_quoted_assignment "$key" "$val")"
  if grep -q "^${key}=" "$CONFIG" 2>/dev/null; then
    tmp="$(mktemp)"
    awk -v k="$key" -v a="$assign" '
      index($0, k "=") == 1 { print a; next }
      { print }
    ' "$CONFIG" > "$tmp" && mv "$tmp" "$CONFIG"
  else
    printf '%s\n' "$assign" >> "$CONFIG"
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
upsert DJANGO_ADMIN_URL "${DJANGO_ADMIN_URL:-}"
upsert POSTGRES_PASSWORD "${POSTGRES_PASSWORD:-}"
upsert PUBLIC_API_KEY "${PUBLIC_API_KEY:-}"
upsert GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID:-}"
upsert GOOGLE_CLIENT_SECRET "${GOOGLE_CLIENT_SECRET:-}"
upsert GOOGLE_REFRESH_TOKEN "${GOOGLE_REFRESH_TOKEN:-}"
upsert GMAIL_SENDER "${GMAIL_SENDER:-}"
upsert GMAIL_SERVICE_ACCOUNT_JSON "${GMAIL_SERVICE_ACCOUNT_JSON:-}"
upsert GMAIL_SERVICE_ACCOUNT_FILE "${GMAIL_SERVICE_ACCOUNT_FILE:-}"
upsert STRIPE_SECRET_KEY "${STRIPE_SECRET_KEY:-}"
upsert STRIPE_PUBLISHABLE_KEY "${STRIPE_PUBLISHABLE_KEY:-}"
upsert STRIPE_WEBHOOK_SECRET "${STRIPE_WEBHOOK_SECRET:-}"
upsert STRIPE_PRICE_MONTHLY "${STRIPE_PRICE_MONTHLY:-}"
upsert STRIPE_PRICE_YEARLY "${STRIPE_PRICE_YEARLY:-}"
upsert PUBLIC_APP_URL "${PUBLIC_APP_URL:-}"
upsert BILLING_MOCK_CHECKOUT "${BILLING_MOCK_CHECKOUT:-}"
upsert MAILCHIMP_API_KEY "${MAILCHIMP_API_KEY:-}"
upsert MAILCHIMP_AUDIENCE_ID "${MAILCHIMP_AUDIENCE_ID:-}"
upsert EMAIL_HOST "${EMAIL_HOST:-}"
upsert EMAIL_PORT "${EMAIL_PORT:-}"
upsert EMAIL_HOST_USER "${EMAIL_HOST_USER:-}"
upsert EMAIL_HOST_PASSWORD "${EMAIL_HOST_PASSWORD:-}"
upsert EMAIL_USE_TLS "${EMAIL_USE_TLS:-}"
upsert DEFAULT_FROM_EMAIL "${DEFAULT_FROM_EMAIL:-}"
upsert VIMEO_ACCESS_TOKEN "${VIMEO_ACCESS_TOKEN:-}"
upsert VIMEO_FOLDER_ID "${VIMEO_FOLDER_ID:-}"
upsert VIMEO_USER_ID "${VIMEO_USER_ID:-}"
upsert VIMEO_SHOWCASE_ID "${VIMEO_SHOWCASE_ID:-}"
upsert VIMEO_FREE_PREVIEW_ID "${VIMEO_FREE_PREVIEW_ID:-}"
upsert DROPBOX_ACCESS_TOKEN "${DROPBOX_ACCESS_TOKEN:-}"
upsert DROPBOX_NOTES_FOLDER "${DROPBOX_NOTES_FOLDER:-}"
upsert DROPBOX_SHARED_URL "${DROPBOX_SHARED_URL:-}"
upsert RUNPOD_API_KEY "${RUNPOD_API_KEY:-}"
upsert VLLM_API_KEY "${VLLM_API_KEY:-}"
upsert RUNPOD_VLLM_ENDPOINT_ID "${RUNPOD_VLLM_ENDPOINT_ID:-}"
upsert VLLM_URL "${VLLM_URL:-}"
upsert VLLM_MODE "${VLLM_MODE:-}"
upsert CPU_ONLY "${CPU_ONLY:-}"
upsert RUNPOD_WHISPER_ENDPOINT_ID "${RUNPOD_WHISPER_ENDPOINT_ID:-}"
upsert WHISPER_URL "${WHISPER_URL:-}"
upsert WHISPER_MODE "${WHISPER_MODE:-}"
upsert WHISPER_API_KEY "${WHISPER_API_KEY:-}"

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

echo "Done."

if [[ -f "$WS/vllm_runtime.sh" ]]; then
  # shellcheck disable=SC1091
  source "$WS/vllm_runtime.sh"
  vllm_apply_config "$CONFIG"
fi

if [[ "${1:-}" == "--restart" ]]; then
  echo "Restarting services..."
  bash "$WS/start.sh"
fi
