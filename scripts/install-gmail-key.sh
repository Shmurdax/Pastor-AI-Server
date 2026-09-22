#!/usr/bin/env bash
# Install a Google Workspace service-account JSON for Gmail send.
# Do not paste the pretty-printed JSON into nano — that truncates the private key.
#
# Usage:
#   bash scripts/install-gmail-key.sh /path/to/downloaded.json
#   cat downloaded.json | bash scripts/install-gmail-key.sh
#   bash scripts/install-gmail-key.sh --base64 'eyJ0eXBlIjoic2VydmljZV9hY2NvdW50Ii...'
set -euo pipefail

WS="${PASTOR_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEST="${GMAIL_SERVICE_ACCOUNT_FILE:-$WS/secrets/gmail-sender.json}"
CONFIG="${CONFIG_ENV:-$WS/config.env}"
SRC=""
B64=""

usage() {
  sed -n '2,9p' "$0"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --base64)
      B64="${2:-}"
      [[ -n "$B64" ]] || { echo "Missing base64 value" >&2; exit 1; }
      shift 2
      ;;
    --base64=*)
      B64="${1#--base64=}"
      shift
      ;;
    -)
      SRC="-"
      shift
      ;;
    *)
      SRC="$1"
      shift
      ;;
  esac
done

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if [[ -n "$B64" ]]; then
  python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode("".join(sys.argv[1].split())))' "$B64" > "$tmp"
elif [[ -z "$SRC" || "$SRC" == "-" ]]; then
  if [[ -t 0 ]]; then
    echo "Pass a downloaded JSON file, stdin, or --base64. See --help." >&2
    exit 1
  fi
  cat > "$tmp"
else
  [[ -f "$SRC" ]] || { echo "Missing JSON file: $SRC" >&2; exit 1; }
  cat "$SRC" > "$tmp"
fi

client_email="$(
python3 - "$tmp" <<'PY'
import json, sys
path = sys.argv[1]
raw = open(path, "rb").read()
text = raw.decode("utf-8")
try:
    data = json.loads(text)
except json.JSONDecodeError as exc:
    raise SystemExit(
        f"Not valid JSON ({len(raw)} bytes, {exc}). "
        "Re-download the key from Google Cloud and copy the file; "
        "do not paste it into nano."
    ) from exc
if not isinstance(data, dict):
    raise SystemExit("JSON is not an object")
if data.get("type") != "service_account":
    raise SystemExit(f"type={data.get('type')!r}; expected service_account")
if "BEGIN" not in str(data.get("private_key") or ""):
    raise SystemExit("private_key is missing or truncated")
if "@" not in str(data.get("client_email") or ""):
    raise SystemExit("client_email is missing")
print(data["client_email"])
PY
)"

mkdir -p "$(dirname "$DEST")"
cp -f "$tmp" "$DEST"
chmod 600 "$DEST"
bytes="$(wc -c < "$DEST" | tr -d ' ')"
echo "Installed $DEST ($bytes bytes) as $client_email"

if [[ -f "$CONFIG" ]]; then
  tmp_env="$(mktemp)"
  awk -v dest="$DEST" '
    index($0, "GMAIL_SERVICE_ACCOUNT_JSON=") == 1 { print "GMAIL_SERVICE_ACCOUNT_JSON="; next }
    index($0, "GMAIL_SERVICE_ACCOUNT_FILE=") == 1 { print "GMAIL_SERVICE_ACCOUNT_FILE=" dest; next }
    { print }
  ' "$CONFIG" > "$tmp_env"
  if ! grep -q '^GMAIL_SERVICE_ACCOUNT_FILE=' "$tmp_env"; then
    printf 'GMAIL_SERVICE_ACCOUNT_FILE=%s\n' "$DEST" >> "$tmp_env"
  fi
  if ! grep -q '^GMAIL_SERVICE_ACCOUNT_JSON=' "$tmp_env"; then
    printf 'GMAIL_SERVICE_ACCOUNT_JSON=\n' >> "$tmp_env"
  fi
  mv "$tmp_env" "$CONFIG"
  echo "Pointed $CONFIG at $DEST and cleared GMAIL_SERVICE_ACCOUNT_JSON"
fi

echo "Restart with: bash $WS/start.sh"
