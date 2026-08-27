#!/usr/bin/env bash
# Token remigration: persist copy restores the named-tunnel token when the
# pastor-ai tree is wiped (the usual RunPod remigration failure).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log()  { :; }
warn() { :; }

export PERSIST_ROOT="$TMP/persistent"
export WS="$TMP/pastor-ai"
mkdir -p "$WS" "$PERSIST_ROOT"

# shellcheck disable=SC1091
source "$ROOT/persist_runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1) Live token is copied onto the persistent volume.
mkdir -p "$WS/.cloudflared"
printf 'live-token-abc\n' > "$WS/.cloudflared/tunnel.token"
got="$(resolve_cloudflare_tunnel_token_file)"
[[ "$got" == "$WS/.cloudflared/tunnel.token" ]] || fail "expected live token path, got $got"
[[ "$(cat "$PERSIST_ROOT/.cloudflared/tunnel.token")" == "live-token-abc" ]] || fail "persist copy not written"

# 2) Remigration: pastor-ai tree wiped, persist copy restores the token.
rm -rf "$WS/.cloudflared"
got="$(resolve_cloudflare_tunnel_token_file)"
[[ -s "$WS/.cloudflared/tunnel.token" ]] || fail "token was not restored into pastor-ai"
[[ "$(cat "$WS/.cloudflared/tunnel.token")" == "live-token-abc" ]] || fail "restored token mismatch"
[[ "$got" == "$WS/.cloudflared/tunnel.token" ]] || fail "resolver should print restored path"

# 3) Env var wins and refreshes both copies (token rotation).
export CLOUDFLARE_TUNNEL_TOKEN="rotated-token-xyz"
got="$(resolve_cloudflare_tunnel_token_file)"
[[ "$(cat "$WS/.cloudflared/tunnel.token")" == "rotated-token-xyz" ]] || fail "env token not written to live path"
[[ "$(cat "$PERSIST_ROOT/.cloudflared/tunnel.token")" == "rotated-token-xyz" ]] || fail "env token not written to persist path"
unset CLOUDFLARE_TUNNEL_TOKEN

# 4) Missing token prints nothing and does not crash.
rm -f "$WS/.cloudflared/tunnel.token" "$PERSIST_ROOT/.cloudflared/tunnel.token"
got="$(resolve_cloudflare_tunnel_token_file || true)"
[[ -z "$got" ]] || fail "expected empty path when token is missing, got $got"

# 5) Restore logs must not pollute stdout (start.sh captures the path).
printf 'live-token-abc\n' > "$PERSIST_ROOT/.cloudflared/tunnel.token"
rm -f "$WS/.cloudflared/tunnel.token"
log() { echo "LOG-MUST-NOT-APPEAR $*"; }
got="$(resolve_cloudflare_tunnel_token_file)"
[[ "$got" == "$WS/.cloudflared/tunnel.token" ]] || fail "stdout polluted or wrong path: $got"

echo "OK persist Cloudflare tunnel token remigration"
