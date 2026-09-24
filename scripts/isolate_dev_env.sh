#!/usr/bin/env bash
# Rewrite the dev pod so live production secrets cannot be used.
# Refuses to run when the git channel is master.
#
#   bash scripts/isolate_dev_env.sh
#   ISOLATE_SOURCE_ONLY=1 source scripts/isolate_dev_env.sh
set -euo pipefail

_isolate_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$_isolate_root/git_channel.sh"
# shellcheck source=/dev/null
source "$_isolate_root/pod_profile.sh"

PRODUCTION_HOST="${PRODUCTION_HOST:-christianaiapophatictestdomain.com}"

isolate_env_get() {
  local file="$1" key="$2" line
  [[ -f "$file" ]] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -1 || true)"
  printf '%s' "${line#*=}"
}

isolate_env_set() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp)"
  if [[ -f "$file" ]]; then
    grep -v -E "^${key}=" "$file" > "$tmp" || true
  fi
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file" 2>/dev/null || true
}

isolate_fingerprint() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    printf 'empty\n'
  else
    printf '%s\n' "${value: -4}"
  fi
}

isolate_generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
  fi
}

isolate_denylist_has() {
  local file="$1" kind="$2" value="$3"
  [[ -n "$value" && -f "$file" ]] || return 1
  grep -q -E "^${kind} ${value}$" "$file"
}

# Apply tokens.test.env onto tokens.env and config.env. Prints a report.
isolate_apply() {
  local ws="$1"
  local test_env="$ws/tokens.test.env"
  local tokens="$ws/tokens.env"
  local config="$ws/config.env"
  local report="$ws/isolation_report"
  local denylist="$ws/.isolation_denylist"
  local channel password stripe public audience folder hf_scope sender sandbox
  local key desired previous fp_before fp_after

  channel="$(pastor_git_channel "$ws")"
  if [[ "$channel" == "master" ]]; then
    echo "isolate: refusing to rewrite secrets on the master/production channel" >&2
    return 1
  fi
  [[ -f "$test_env" ]] || {
    echo "isolate: missing $test_env" >&2
    return 1
  }
  if grep -q -E '^HF_TOKEN_SCOPE=write$' "$test_env"; then
    echo "isolate: refusing a write-scoped HF_TOKEN" >&2
    return 1
  fi

  touch "$tokens" "$config"
  : > "$report"

  # Persist generated secrets in the test file so the next boot does not rotate them.
  for key in DJANGO_SECRET_KEY POSTGRES_PASSWORD; do
    if [[ -z "$(isolate_env_get "$test_env" "$key")" ]]; then
      isolate_env_set "$test_env" "$key" "$(isolate_generate_secret)"
      echo "generated $key" >> "$report"
    fi
  done

  password="$(isolate_env_get "$test_env" "DJANGO_SUPERUSER_PASSWORD")"
  if [[ -z "$password" || "$password" == "admin123" ]]; then
    echo "isolate: DJANGO_SUPERUSER_PASSWORD must be set and must not be admin123" >&2
    return 1
  fi

  stripe="$(isolate_env_get "$test_env" "STRIPE_SECRET_KEY")"
  if [[ "$stripe" == sk_live_* ]]; then
    echo "isolate: tokens.test.env STRIPE_SECRET_KEY must be a test key or empty" >&2
    return 1
  fi
  public="$(isolate_env_get "$test_env" "PUBLIC_APP_URL")"
  if [[ "$public" == *"$PRODUCTION_HOST"* ]]; then
    echo "isolate: PUBLIC_APP_URL must not be the production domain" >&2
    return 1
  fi

  audience="$(isolate_env_get "$test_env" "MAILCHIMP_AUDIENCE_ID")"
  if isolate_denylist_has "$denylist" "mailchimp_audience" "$audience"; then
    echo "isolate: MAILCHIMP_AUDIENCE_ID is the production audience" >&2
    return 1
  fi
  folder="$(isolate_env_get "$test_env" "VIMEO_FOLDER_ID")"
  if isolate_denylist_has "$denylist" "vimeo_folder" "$folder"; then
    echo "isolate: VIMEO_FOLDER_ID is the production folder" >&2
    return 1
  fi

  sender="$(isolate_env_get "$test_env" "GMAIL_SENDER")"
  sandbox="$(isolate_env_get "$test_env" "GMAIL_SANDBOX_SENDERS")"
  if [[ -n "$sender" && ",${sandbox}," != *",${sender},"* ]]; then
    echo "cleared GMAIL_SENDER (not in sandbox list)" >> "$report"
    sender=""
  fi

  # Keys taken from the test file. Empty means the live value is deleted.
  local -a managed=(
    PASTOR_ENV CPU_ONLY VLLM_MODE WHISPER_MODE
    STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET
    STRIPE_PRICE_MONTHLY STRIPE_PRICE_YEARLY PUBLIC_APP_URL
    RUNPOD_API_KEY RUNPOD_VLLM_ENDPOINT_ID RUNPOD_WHISPER_ENDPOINT_ID VLLM_URL
    DJANGO_SECRET_KEY POSTGRES_PASSWORD DJANGO_SUPERUSER_PASSWORD
    GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN
    GMAIL_SENDER GMAIL_SERVICE_ACCOUNT_JSON GMAIL_SERVICE_ACCOUNT_FILE
    EMAIL_HOST_PASSWORD EMAIL_HOST_USER
    MAILCHIMP_API_KEY MAILCHIMP_AUDIENCE_ID
    VIMEO_ACCESS_TOKEN VIMEO_FOLDER_ID VIMEO_USER_ID
    HF_TOKEN
  )
  for key in "${managed[@]}"; do
    desired="$(isolate_env_get "$test_env" "$key")"
    case "$key" in
      PASTOR_ENV) desired="development" ;;
      CPU_ONLY) desired="${desired:-1}" ;;
      VLLM_MODE) desired="${desired:-serverless}" ;;
      GMAIL_SENDER) desired="$sender" ;;
    esac
    previous="$(isolate_env_get "$tokens" "$key")"
    fp_before="$(isolate_fingerprint "$previous")"
    fp_after="$(isolate_fingerprint "$desired")"
    isolate_env_set "$tokens" "$key" "$desired"
    isolate_env_set "$config" "$key" "$desired"
    if [[ "$fp_before" == "$fp_after" ]]; then
      echo "$key unchanged …${fp_after}" >> "$report"
    elif [[ -z "$desired" ]]; then
      echo "$key cleared (was …${fp_before})" >> "$report"
    else
      echo "$key replaced …${fp_before} -> …${fp_after}" >> "$report"
    fi
  done

  # Never leave a push token or a named tunnel token in the app env.
  for key in GITHUB_TOKEN CLOUDFLARE_TUNNEL_TOKEN; do
    previous="$(isolate_env_get "$tokens" "$key")"
    isolate_env_set "$tokens" "$key" ""
    isolate_env_set "$config" "$key" ""
    echo "$key cleared (was $(isolate_fingerprint "$previous"))" >> "$report"
  done

  local endpoint vllm_url
  endpoint="$(isolate_env_get "$tokens" "RUNPOD_VLLM_ENDPOINT_ID")"
  vllm_url="$(isolate_env_get "$tokens" "VLLM_URL")"
  if isolate_denylist_has "$denylist" "endpoint" "$endpoint"; then
    echo "isolate: RUNPOD_VLLM_ENDPOINT_ID is on the production denylist" >&2
    return 1
  fi
  if [[ -f "$denylist" && -n "$vllm_url" ]]; then
    while read -r kind value; do
      [[ "$kind" == "endpoint" && -n "$value" && "$vllm_url" == *"$value"* ]] || continue
      echo "isolate: VLLM_URL contains a production endpoint id" >&2
      return 1
    done < "$denylist"
  fi

  rm -f \
    "$ws/.cloudflared/tunnel.token" \
    "$ws/.cloudflared/tunnel.token.prd-copy" \
    "$ws/tunnel.token.prd-copy"
  echo "named tunnel token files removed from $ws" >> "$report"
  echo "isolate: wrote $report"
}

if [[ "${ISOLATE_SOURCE_ONLY:-0}" != "1" && "${BASH_SOURCE[0]}" == "$0" ]]; then
  WS="${WORKSPACE_ROOT:-/workspace/pastor-ai}"
  isolate_apply "$WS"
fi
