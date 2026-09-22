#!/usr/bin/env python3
"""One-shot browser upload for the Gmail JSON key (avoids terminal paste).

Stop Django first so this can bind the public site port (8000), then open the
printed URL on your laptop and choose the downloaded JSON file:

  screen -S django -X quit
  pkill -9 -f pastor_ai.wsgi || true
  python3 /workspace/pastor-ai/scripts/receive-gmail-key.py
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEST = Path(os.environ.get("GMAIL_SERVICE_ACCOUNT_FILE") or "/workspace/pastor-ai/secrets/gmail-sender.json")
PORT = int(os.environ.get("GMAIL_UPLOAD_PORT") or "8000")
TOKEN = secrets.token_urlsafe(12)
PUBLIC_URL_FILE = Path("/workspace/pastor-ai/public_url.txt")
FORM = """<!doctype html>
<title>Install Gmail key</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<body style="font-family:sans-serif;max-width:40rem;margin:2rem auto;line-height:1.4">
<h1>Install Gmail key</h1>
<p>Choose the JSON file Google Cloud downloaded, for example
<code>nth-weft-509218-e0-34dcebbd6db0.json</code>.</p>
<form method="post" action="?t={token}" enctype="multipart/form-data">
<p><input type="file" name="file" accept=".json,application/json" required></p>
<p><button>Install key</button></p>
</form>
</body>
"""


def _extract_file(body: bytes, content_type: str) -> bytes:
    if "multipart/form-data" not in content_type or "boundary=" not in content_type:
        raise ValueError("Upload the JSON with the form file picker.")
    boundary = content_type.split("boundary=", 1)[1].strip().encode("utf-8")
    marker = b"--" + boundary
    for part in body.split(marker):
        if b"name=\"file\"" not in part and b"name=file" not in part:
            continue
        _header, sep, payload = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        data = payload.rsplit(b"\r\n", 1)[0]
        return data
    raise ValueError("No file was attached.")


def _install(raw: bytes) -> str:
    if len(raw) > 16_384:
        raise ValueError("File is too large to be a Google JSON key.")
    data = json.loads(raw.decode("utf-8"))
    if data.get("type") != "service_account":
        raise ValueError("type must be service_account")
    if "BEGIN" not in str(data.get("private_key") or ""):
        raise ValueError("private_key is missing or truncated")
    email = str(data.get("client_email") or "")
    if "@" not in email:
        raise ValueError("client_email is missing")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(raw)
    os.chmod(DEST, 0o600)
    persist = Path(os.environ.get("PERSIST_ROOT") or "/workspace/persistent") / "secrets" / "gmail-sender.json"
    try:
        persist.parent.mkdir(parents=True, exist_ok=True)
        persist.write_bytes(raw)
        os.chmod(persist, 0o600)
    except OSError:
        pass
    return f"ok {len(raw)} bytes as {email} at {DEST}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _ok(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _deny(self) -> None:
        body = b"Missing upload token"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self) -> bool:
        token = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        return bool(token) and secrets.compare_digest(token, TOKEN)

    def do_GET(self):
        if not self._token_ok():
            self._deny()
            return
        self._ok(FORM.format(token=TOKEN).encode("utf-8"))

    def do_POST(self):
        if not self._token_ok():
            self._deny()
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type") or ""
        try:
            message = _install(_extract_file(body, content_type))
        except Exception as exc:
            text = f"Upload failed: {exc}".encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(text)
            return
        self._ok(message.encode("utf-8"), "text/plain; charset=utf-8")
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def _public_base() -> str:
    try:
        text = PUBLIC_URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    return text.rstrip("/")


def main() -> None:
    ThreadingHTTPServer.allow_reuse_address = True
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(
            f"Port {PORT} is still in use (Django is running).\n"
            "Stop it first, then run this script again:\n"
            "  screen -S django -X quit\n"
            "  pkill -9 -f pastor_ai.wsgi\n"
            "  sleep 1",
            flush=True,
        )
        raise SystemExit(1)
    print(f"Listening on port {PORT}", flush=True)
    base = _public_base()
    if base:
        print(f"Open this on your laptop:\n  {base}/?t={TOKEN}", flush=True)
    else:
        print(f"Open:\n  http://127.0.0.1:{PORT}/?t={TOKEN}", flush=True)
    print("Choose the JSON file in the browser. Leave this terminal open until it prints ok.", flush=True)
    server.serve_forever()
    print("Gmail key installed. Run: bash /workspace/pastor-ai/start.sh", flush=True)


if __name__ == "__main__":
    main()
