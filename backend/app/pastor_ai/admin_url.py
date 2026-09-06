"""Private Django admin URL path.

The public ``/admin/`` route is a well-known scanner target. Staff reach the
control panel at ``/{ADMIN_URL_PATH}/`` instead. Override with
``DJANGO_ADMIN_URL`` in ``config.env`` (letters and numerals only).
"""

from __future__ import annotations

import os
import re

# Keep this out of README / robots.txt. Share the full URL privately.
DEFAULT_ADMIN_URL_PATH = "rB4zKwO2wTBCD3pAxRIdTWsvw0w8"

RESERVED_ADMIN_URL_PATHS = frozenset(
    {
        "admin",
        "api",
        "static",
        "chat",
        "sermons",
        "media",
        "login",
        "register",
        "robots",
        "favicon",
    }
)

_FRONTEND_EXCLUDED_PREFIXES = ("api/", "static/", "chat/", "sermons/")


def normalize_admin_url_path(raw: str | None) -> str:
    """Return a letters-and-numerals admin slug, or the built-in default."""
    candidate = (raw or "").strip().strip("/")
    cleaned = "".join(ch for ch in candidate if ch.isalnum())
    if not cleaned:
        return DEFAULT_ADMIN_URL_PATH
    if cleaned.lower() in RESERVED_ADMIN_URL_PATHS:
        raise ValueError(
            f"DJANGO_ADMIN_URL cannot be a reserved public path ({cleaned!r})."
        )
    if len(cleaned) < 12:
        raise ValueError("DJANGO_ADMIN_URL must be at least 12 alphanumeric characters.")
    return cleaned


def admin_url_path_from_env() -> str:
    return normalize_admin_url_path(os.getenv("DJANGO_ADMIN_URL", ""))


def frontend_catch_all_pattern(admin_path: str) -> str:
    """Regex that serves Flutter for every path except admin/API/static/chat/sermons."""
    escaped = re.escape(admin_path)
    prefixes = "|".join((f"{escaped}/", f"{escaped}$", *_FRONTEND_EXCLUDED_PREFIXES))
    return rf"^(?!{prefixes})(?P<path>.*)$"


def is_admin_request_path(path: str, admin_path: str) -> bool:
    """True for the secret admin tree and the public ``/admin/`` decoy."""
    normalized = path or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    slug = (admin_path or DEFAULT_ADMIN_URL_PATH).strip("/")
    return (
        normalized == "/admin"
        or normalized.startswith("/admin/")
        or normalized == f"/{slug}"
        or normalized.startswith(f"/{slug}/")
    )
