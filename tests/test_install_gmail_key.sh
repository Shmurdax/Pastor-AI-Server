#!/usr/bin/env bash
# install-gmail-key.sh must reject truncated JSON and accept a real SA key.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
mkdir -p "$DIR/secrets"
printf 'GMAIL_SERVICE_ACCOUNT_JSON={not-json\nGMAIL_SENDER=info@thenordins.org\n' > "$DIR/config.env"
export PASTOR_WORKSPACE="$DIR"
export CONFIG_ENV="$DIR/config.env"
export GMAIL_SERVICE_ACCOUNT_FILE="$DIR/secrets/gmail-sender.json"

bad="$DIR/truncated.json"
printf '{\n  "type": "service_account",\n  "project_id": "x",\n  "private_key_id": "y",\n  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE' > "$bad"
if bash "$ROOT/scripts/install-gmail-key.sh" "$bad" >/tmp/pastor-gmail-install.out 2>/tmp/pastor-gmail-install.err; then
  fail "truncated JSON should be rejected"
fi
grep -q "Not valid JSON" /tmp/pastor-gmail-install.err || fail "expected JSON error: $(cat /tmp/pastor-gmail-install.err)"

good="$DIR/good.json"
python3 - "$good" <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path
out = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as tmp:
    key_path = Path(tmp) / "key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key_path)],
        check=True,
        capture_output=True,
    )
    private_key = key_path.read_text(encoding="utf-8")
out.write_text(
    json.dumps(
        {
            "type": "service_account",
            "project_id": "nordins-ai",
            "private_key_id": "local-test-key",
            "private_key": private_key,
            "client_email": "gmail-sender@nordins-ai.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    ),
    encoding="utf-8",
)
PY

bash "$ROOT/scripts/install-gmail-key.sh" "$good" >/tmp/pastor-gmail-install.out
[[ -f "$DIR/secrets/gmail-sender.json" ]] || fail "key not installed"
python3 - "$DIR/secrets/gmail-sender.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["type"] == "service_account"
assert "BEGIN" in data["private_key"]
PY
grep -q '^GMAIL_SERVICE_ACCOUNT_JSON=$' "$DIR/config.env" || fail "leftover JSON not cleared"
grep -q "^GMAIL_SERVICE_ACCOUNT_FILE=$DIR/secrets/gmail-sender.json$" "$DIR/config.env" \
  || fail "FILE not pointed at dest: $(cat "$DIR/config.env")"

b64="$(python3 -c 'import base64,sys; print(base64.b64encode(open(sys.argv[1],"rb").read()).decode())' "$good")"
rm -f "$DIR/secrets/gmail-sender.json"
bash "$ROOT/scripts/install-gmail-key.sh" --base64 "$b64" >/tmp/pastor-gmail-install.out
[[ -f "$DIR/secrets/gmail-sender.json" ]] || fail "base64 install failed"

echo "OK"
