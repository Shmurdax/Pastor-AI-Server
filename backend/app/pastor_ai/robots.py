"""robots.txt and crawl/index policy helpers."""

from django.conf import settings
from django.http import HttpResponse

from .admin_url import DEFAULT_ADMIN_URL_PATH, is_admin_request_path

# User-agent: * applies to every crawler that follows the robots.txt standard
# (Google, Bing, DuckDuckGo, Yandex, Baidu, etc.).
# Keep Disallow: /admin/ as a decoy. Do not list the private admin slug here —
# robots.txt is public and would advertise that path to anyone who reads it.
ROBOTS_TXT = """\
User-agent: *
Disallow: /admin/
Disallow: /api/
"""

NOINDEX_HEADER_VALUE = "noindex, nofollow, nosnippet, noarchive"


def path_requires_noindex(path: str) -> bool:
    """True for admin and API surfaces that must not appear in search indexes."""
    normalized = path or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    admin_path = getattr(settings, "ADMIN_URL_PATH", DEFAULT_ADMIN_URL_PATH)
    return (
        is_admin_request_path(normalized, admin_path)
        or normalized == "/api"
        or normalized.startswith("/api/")
    )


def robots_txt_view(_request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain; charset=utf-8")
