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
from email.utils import formataddr, parseaddr
from pathlib import Path

import requests
from django.conf import settings
from google.auth.exceptions import RefreshError
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
    name, addr = parseaddr(address)
    return formataddr((name or GMAIL_FROM_NAME, addr or address))


HARDCODED_GMAIL_FILES = (
    Path("/workspace/pastor-ai/secrets/gmail-sender.json"),
    Path("/workspace/persistent/secrets/gmail-sender.json"),
)


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
            *HARDCODED_GMAIL_FILES,
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


def _looks_like_service_account(info: dict) -> bool:
    private_key = str(info.get("private_key") or "")
    client_email = str(info.get("client_email") or "")
    return (
        info.get("type") == "service_account"
        and "BEGIN" in private_key
        and "@" in client_email
    )


def _parse_service_account_info(raw: str, *, source: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    if not text.startswith("{"):
        try:
            text = base64.b64decode(text).decode("utf-8")
        except Exception:
            logger.warning("Gmail credentials from %s are not JSON or base64.", source)
            return None
    try:
        info = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Gmail credentials from %s are not valid JSON (%s bytes).",
            source,
            len(text.encode("utf-8")),
        )
        return None
    if not isinstance(info, dict):
        logger.warning("Gmail credentials from %s are not a JSON object.", source)
        return None
    if not _looks_like_service_account(info):
        logger.warning(
            "Gmail credentials from %s are not a service-account key "
            "(type=%s client_email=%s private_key=%s).",
            source,
            info.get("type"),
            bool(info.get("client_email")),
            bool(info.get("private_key")),
        )
        return None
    return info


def _service_account_info() -> dict | None:
    """Load the Workspace service-account key. On-disk JSON wins over env paste."""
    seen_files: list[Path] = []
    for file_path in _service_account_files():
        if not file_path.is_file():
            continue
        seen_files.append(file_path)
        try:
            raw = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read Gmail service account file %s: %s", file_path, exc)
            continue
        info = _parse_service_account_info(raw, source=str(file_path))
        if info:
            return info
    raw = _setting("GMAIL_SERVICE_ACCOUNT_JSON")
    if raw:
        info = _parse_service_account_info(raw, source="GMAIL_SERVICE_ACCOUNT_JSON")
        if info:
            return info
    if seen_files:
        logger.error(
            "Gmail JSON key was found but is not a usable service-account key: %s",
            ", ".join(str(path) for path in seen_files),
        )
    return None


def gmail_is_configured() -> bool:
    try:
        if _service_account_info() and gmail_sender():
            return True
    except Exception:
        logger.exception("Gmail configuration check failed")
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
    try:
        if not getattr(creds, "valid", False) or not getattr(creds, "token", None):
            creds.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        raise GmailSendError(
            "Google rejected sending as info@thenordins.org. That address must be a real "
            "Workspace user (not a Group), and domain-wide delegation must allow gmail.send."
        ) from exc
    token = getattr(creds, "token", None)
    if not token:
        raise GmailSendError("Google OAuth did not return an access token.")
    return token


def build_raw_message(*, sender: str, to_email: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = to_email
    name, addr = parseaddr(sender)
    message["From"] = formataddr((name or GMAIL_FROM_NAME, addr or sender))
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
        body = (response.text or "").lower()
        if "failedprecondition" in body or "delegation" in body or "unauthorized_client" in body:
            raise GmailSendError(
                "Google rejected sending as info@thenordins.org. That address must be a real "
                "Workspace user (not a Group), and domain-wide delegation must allow gmail.send."
            )
        raise GmailSendError("Google could not send the verification email.")
    payload = response.json() if response.content else {}
    message_id = str(payload.get("id") or "")
    logger.info("Gmail API sent verification email to %s id=%s", to_email, message_id)
    return message_id
