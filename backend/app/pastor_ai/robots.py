"""robots.txt and crawl/index policy helpers."""

from django.http import HttpResponse

# User-agent: * applies to every crawler that follows the robots.txt standard
# (Google, Bing, DuckDuckGo, Yandex, Baidu, etc.).
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
    return (
        normalized == "/admin"
        or normalized.startswith("/admin/")
        or normalized == "/api"
        or normalized.startswith("/api/")
    )


def robots_txt_view(_request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain; charset=utf-8")
