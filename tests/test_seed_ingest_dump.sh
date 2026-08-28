#!/usr/bin/env bash
# The git seed dump is the ingested catalog only (no users/sessions/tokens).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="$ROOT/seed/ingested_catalog.dump"

fail() { echo "FAIL: $*" >&2; exit 1; }
[[ -s "$DUMP" ]] || fail "missing $DUMP"
python3 - <<PY
from pathlib import Path
p = Path("$DUMP")
data = p.read_bytes()
if not data.startswith(b"PGDMP"):
    raise SystemExit("FAIL: not a Postgres custom dump")
if b"core_ingesteddocument" not in data:
    raise SystemExit("FAIL: dump missing core_ingesteddocument")
if b"core_ingestedchunk" not in data:
    raise SystemExit("FAIL: dump missing core_ingestedchunk")
# Full-app dump tables that must not be in this seed.
for banned in (b"auth_user", b"authtoken_token", b"django_session", b"core_chatmessage"):
    if banned in data:
        raise SystemExit(f"FAIL: seed dump contains {banned.decode()}")
print("OK seed ingested catalog dump", p.stat().st_size, "bytes")
PY
