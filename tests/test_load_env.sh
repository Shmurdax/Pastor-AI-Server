#!/usr/bin/env bash
# Env loader + apply-tokens must survive Nordin's apostrophe.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/load_env.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

cat > "$DIR/broken.env" <<'EOF'
GMAIL_SENDER=info@thenordins.org
DEFAULT_FROM_EMAIL=Nordin's AI <info@thenordins.org>
GMAIL_SERVICE_ACCOUNT_FILE=/workspace/pastor-ai/secrets/gmail-sender.json
EOF

unset GMAIL_SENDER DEFAULT_FROM_EMAIL GMAIL_SERVICE_ACCOUNT_FILE
pastor_load_env_file "$DIR/broken.env"
[[ "$GMAIL_SENDER" == "info@thenordins.org" ]] || fail "sender: $GMAIL_SENDER"
[[ "$DEFAULT_FROM_EMAIL" == "Nordin's AI <info@thenordins.org>" ]] || fail "from: $DEFAULT_FROM_EMAIL"

quoted="$(pastor_env_quoted_assignment DEFAULT_FROM_EMAIL "$DEFAULT_FROM_EMAIL")"
[[ "$quoted" == "DEFAULT_FROM_EMAIL=\"Nordin's AI <info@thenordins.org>\"" ]] \
  || fail "quoted assignment: $quoted"

# bash source of the quoted assignment must work
unset DEFAULT_FROM_EMAIL
eval "$quoted"
[[ "$DEFAULT_FROM_EMAIL" == "Nordin's AI <info@thenordins.org>" ]] || fail "eval quoted from"

# config.env.example itself must be bash-sourceable after the quoting fix
bash -c "set -a; source '$ROOT/config.env.example'; set +a; test \"\$GMAIL_SENDER\" = info@thenordins.org" \
  || fail "config.env.example cannot be sourced by bash"

# apply-tokens copies apostrophe values into quoted config.env lines
cat > "$DIR/tokens.env" <<'EOF'
GMAIL_SENDER=info@thenordins.org
DEFAULT_FROM_EMAIL=Nordin's AI <info@thenordins.org>
GMAIL_SERVICE_ACCOUNT_FILE=/tmp/gmail-sender.json
EOF
cat > "$DIR/config.env" <<'EOF'
GMAIL_SENDER=noreply@thenordins.org
DEFAULT_FROM_EMAIL=Nordin's AI <noreply@thenordins.org>
GMAIL_SERVICE_ACCOUNT_FILE=
EOF
TOKENS_FILE="$DIR/tokens.env" CONFIG_ENV="$DIR/config.env" bash "$ROOT/apply-tokens.sh" \
  || fail "apply-tokens.sh should succeed with apostrophe From: name"

grep -q 'GMAIL_SENDER="info@thenordins.org"' "$DIR/config.env" \
  || fail "apply-tokens did not quote GMAIL_SENDER: $(cat "$DIR/config.env")"
grep -q "DEFAULT_FROM_EMAIL=\"Nordin's AI <info@thenordins.org>\"" "$DIR/config.env" \
  || fail "apply-tokens did not quote DEFAULT_FROM_EMAIL"

bash -c "set -a; source '$DIR/config.env'; set +a" \
  || fail "quoted config.env still cannot be sourced"

echo "OK"
