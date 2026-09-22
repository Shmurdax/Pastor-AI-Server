"""Send mail through the live Gmail API (gmail.googleapis.com).

Uses Google's OAuth 2.0 token endpoint and Gmail users.messages.send.
A Workspace service account with domain-wide delegation is the production
path; a user OAuth refresh token is also supported.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from email.message import EmailMessage
from pathlib import Path

import requests
from django.conf import settings
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import credentials as oauth_credentials
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_SENDER = "info@thenordins.org"
GMAIL_FROM_NAME = "Nordin's AI"


class GmailSendError(Exception):
    pass


def _setting(name: str, default: str = "") -> str:
    value = getattr(settings, name, None)
    if value is None:
        value = os.environ.get(name, default)
    return str(value or "").strip()


def gmail_sender() -> str:
    raw = _setting("GMAIL_SENDER") or _setting("DEFAULT_FROM_EMAIL") or DEFAULT_GMAIL_SENDER
    if "<" in raw and ">" in raw:
        return raw[raw.rfind("<") + 1 : raw.rfind(">")].strip()
    return raw


def formatted_from_header(sender: str | None = None) -> str:
    """From: line for verification mail. Display name lives in code, not bash env."""
    address = (sender or gmail_sender()).strip()
    if not address:
        return ""
    if "<" in address and ">" in address:
        return address
    return f"{GMAIL_FROM_NAME} <{address}>"


def _workspace_root() -> Path:
    hint = _setting("WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT", "")
    if hint:
        return Path(hint)
    try:
        return Path(__file__).resolve().parents[3]
    except IndexError:
        return Path("/workspace/pastor-ai")


def _service_account_files() -> list[Path]:
    paths: list[Path] = []
    configured = _setting("GMAIL_SERVICE_ACCOUNT_FILE") or _setting("GOOGLE_APPLICATION_CREDENTIALS")
    if configured:
        paths.append(Path(configured))
    ws = _workspace_root()
    persist = Path(os.environ.get("PERSIST_ROOT") or "/workspace/persistent")
    paths.extend(
        [
            ws / "secrets" / "gmail-sender.json",
            persist / "secrets" / "gmail-sender.json",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path if path.is_absolute() else (ws / path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _service_account_info() -> dict | None:
    raw = _setting("GMAIL_SERVICE_ACCOUNT_JSON")
    if raw:
        if not raw.startswith("{"):
            try:
                raw = base64.b64decode(raw).decode("utf-8")
            except Exception as exc:
                raise GmailSendError("GMAIL_SERVICE_ACCOUNT_JSON is not valid JSON or base64.") from exc
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GmailSendError("GMAIL_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
        if isinstance(info, dict):
            return info
    last_error: GmailSendError | None = None
    for file_path in _service_account_files():
        if not file_path.is_file():
            continue
        try:
            info = json.loads(file_path.read_text(encoding="utf-8"))
        except OSError as exc:
            last_error = GmailSendError(f"Could not read Gmail service account file: {file_path}")
            last_error.__cause__ = exc
            continue
        except json.JSONDecodeError as exc:
            raise GmailSendError("Gmail service account file is not valid JSON.") from exc
        if isinstance(info, dict):
            return info
    configured = _setting("GMAIL_SERVICE_ACCOUNT_FILE") or _setting("GOOGLE_APPLICATION_CREDENTIALS")
    if configured and last_error is not None:
        raise last_error
    return None


def gmail_is_configured() -> bool:
    try:
        if _service_account_info() and gmail_sender():
            return True
    except GmailSendError:
        return False
    client_id = _setting("GOOGLE_CLIENT_ID")
    client_secret = _setting("GOOGLE_CLIENT_SECRET")
    refresh_token = _setting("GOOGLE_REFRESH_TOKEN")
    return bool(client_id and client_secret and refresh_token)


def email_delivery_mode() -> str:
    if gmail_is_configured():
        return "gmail_api"
    if _setting("EMAIL_HOST"):
        return "smtp"
    return "console"


def _credentials():
    info = _service_account_info()
    sender = gmail_sender()
    if info:
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=[GMAIL_SEND_SCOPE],
        )
        if sender:
            creds = creds.with_subject(sender)
        return creds
    client_id = _setting("GOOGLE_CLIENT_ID")
    client_secret = _setting("GOOGLE_CLIENT_SECRET")
    refresh_token = _setting("GOOGLE_REFRESH_TOKEN")
    if client_id and client_secret and refresh_token:
        return oauth_credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[GMAIL_SEND_SCOPE],
        )
    raise GmailSendError("Gmail API is not configured.")


def _access_token(creds) -> str:
    if not getattr(creds, "valid", False) or not getattr(creds, "token", None):
        creds.refresh(GoogleAuthRequest())
    token = getattr(creds, "token", None)
    if not token:
        raise GmailSendError("Google OAuth did not return an access token.")
    return token


def build_raw_message(*, sender: str, to_email: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def send_via_gmail_api(*, to_email: str, subject: str, body: str) -> str:
    """Send one message through Gmail. Returns the Gmail message id."""
    sender = formatted_from_header()
    if not gmail_sender():
        raise GmailSendError("Set GMAIL_SENDER or DEFAULT_FROM_EMAIL for the Gmail API.")
    creds = _credentials()
    token = _access_token(creds)
    raw = build_raw_message(sender=sender, to_email=to_email, subject=subject, body=body)
    response = requests.post(
        GMAIL_SEND_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={"raw": raw},
        timeout=20,
    )
    if response.status_code < 200 or response.status_code >= 300:
        logger.error("Gmail API send failed: HTTP %s %s", response.status_code, response.text[:500])
        raise GmailSendError("Google could not send the verification email.")
    payload = response.json() if response.content else {}
    message_id = str(payload.get("id") or "")
    logger.info("Gmail API sent verification email to %s id=%s", to_email, message_id)
    return message_id
