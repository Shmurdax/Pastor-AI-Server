import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

from .admin_url import is_admin_request_path

VIMEO_EMBED_FILENAME = "vimeo_embed.html"
_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

# Last-resort copy of frontend/web/vimeo_embed.html. The media page iframes
# /vimeo_embed.html; sermon-sources embeds player.vimeo.com directly and does
# not need this file. Keep the two HTML copies in sync.
_VIMEO_EMBED_FALLBACK = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="referrer" content="strict-origin-when-cross-origin" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Vimeo embed</title>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background: #000;
      overflow: hidden;
    }
    iframe {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
    }
    .err {
      color: #fff;
      font-family: system-ui, sans-serif;
      padding: 24px;
      text-align: center;
    }
  </style>
</head>
<body>
  <script>
    (function () {
      var params = new URLSearchParams(window.location.search);
      var id = (params.get('id') || '').trim();
      var hash = (params.get('h') || '').trim();
      var title = params.get('title') || 'Vimeo video';
      if (!id) {
        document.body.innerHTML = '<p class="err">Missing Vimeo video id.</p>';
        return;
      }
      // Match the admin sermon-sources player: privacy hash first, then dnt.
      var q = [];
      if (hash) q.push('h=' + encodeURIComponent(hash));
      q.push('dnt=1');
      q.push('badge=0');
      q.push('autopause=0');
      q.push('player_id=0');
      q.push('app_id=58479');
      var iframe = document.createElement('iframe');
      iframe.src = 'https://player.vimeo.com/video/' + encodeURIComponent(id) + '?' + q.join('&');
      iframe.setAttribute('frameborder', '0');
      iframe.setAttribute(
        'allow',
        'autoplay; fullscreen; picture-in-picture; clipboard-write; encrypted-media; web-share'
      );
      iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      iframe.setAttribute('allowfullscreen', 'true');
      iframe.title = title;
      document.body.appendChild(iframe);
    })();
  </script>
</body>
</html>
"""


def _apply_cache_headers(response):
    for key, value in _CACHE_HEADERS.items():
        response[key] = value
    return response


def vimeo_embed_file_candidates(configured_dir: Path | None = None) -> list[Path]:
    """Resolve the media-page Vimeo relay even when a stale Flutter build omitted it."""
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path if path.is_absolute() else path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(resolved)

    if configured_dir is not None:
        add(configured_dir / VIMEO_EMBED_FILENAME)
        add(configured_dir / "web" / VIMEO_EMBED_FILENAME)
        add(configured_dir / "build" / "web" / VIMEO_EMBED_FILENAME)
        add(configured_dir.parent / VIMEO_EMBED_FILENAME)
        add(configured_dir.parent / "web" / VIMEO_EMBED_FILENAME)
        add(configured_dir.parent.parent / "web" / VIMEO_EMBED_FILENAME)

    repo_root = Path(settings.BASE_DIR).resolve().parent.parent
    add(repo_root / "frontend" / "web" / VIMEO_EMBED_FILENAME)
    add(repo_root / "frontend" / "build" / "web" / VIMEO_EMBED_FILENAME)
    return paths


def load_vimeo_embed_html(configured_dir: Path | None = None) -> str:
    for path in vimeo_embed_file_candidates(configured_dir):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return _VIMEO_EMBED_FALLBACK


def vimeo_embed_response(configured_dir: Path | None = None) -> HttpResponse:
    """Same-origin relay so Vimeo domain privacy sees this site as the referrer."""
    response = HttpResponse(
        load_vimeo_embed_html(configured_dir),
        content_type="text/html; charset=utf-8",
    )
    _apply_cache_headers(response)
    # Global X_FRAME_OPTIONS=DENY makes Chrome report "refused to connect."
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def serve_vimeo_embed(request):
    configured_dir = Path(getattr(settings, "FRONTEND_BUILD_DIR", "/frontend"))
    return vimeo_embed_response(configured_dir if configured_dir.exists() else None)


LANDING_VIDEO_RELATIVE = Path("videos") / "landing.mp4"
_LANDING_VIDEO_CACHE = "public, max-age=86400"
_BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class _BoundedReader:
    """File reader that stops after a fixed number of bytes (HTTP Range)."""

    def __init__(self, raw, remaining: int):
        self._raw = raw
        self._remaining = remaining

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        if size is None or size < 0 or size > self._remaining:
            size = self._remaining
        chunk = self._raw.read(size)
        if not chunk:
            self._remaining = 0
            return b""
        self._remaining -= len(chunk)
        return chunk

    def close(self) -> None:
        self._raw.close()


def _add_landing_video_candidate(paths: list[Path], seen: set[Path], path: Path) -> None:
    try:
        resolved = path.resolve()
    except OSError:
        return
    if resolved not in seen:
        seen.add(resolved)
        paths.append(resolved)


def _permanent_web_video(directory: Path) -> Path | None:
    """`build/web` -> sibling `web/videos/landing.mp4` (the copy Flutter rebuilds from)."""
    if directory.name == "web" and directory.parent.name == "build":
        return directory.parent.parent / "web" / LANDING_VIDEO_RELATIVE
    return None


def landing_video_candidates(configured_dir: Path, build_dir: Path) -> list[Path]:
    """Build output first, then the permanent `web/videos` source."""
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        _add_landing_video_candidate(paths, seen, path)

    add(build_dir / LANDING_VIDEO_RELATIVE)
    add(configured_dir / LANDING_VIDEO_RELATIVE)
    add(configured_dir / "web" / LANDING_VIDEO_RELATIVE)
    for directory in (build_dir, configured_dir):
        permanent = _permanent_web_video(directory)
        if permanent is not None:
            add(permanent)
    repo_root = Path(settings.BASE_DIR).resolve().parent.parent
    add(repo_root / "frontend" / "web" / LANDING_VIDEO_RELATIVE)
    add(repo_root / "frontend" / "build" / "web" / LANDING_VIDEO_RELATIVE)
    return paths


def resolve_landing_video(configured_dir: Path, build_dir: Path) -> Path | None:
    for path in landing_video_candidates(configured_dir, build_dir):
        if path.is_file():
            return path
    return None


def _byte_range(header: str | None, file_size: int) -> tuple[int, int, int]:
    """Return start, end, and status (200, 206, or 416)."""
    if file_size <= 0:
        return 0, -1, 200
    if not header:
        return 0, file_size - 1, 200
    match = _BYTE_RANGE.match(header.strip())
    if match is None:
        return 0, file_size - 1, 416
    start_s, end_s = match.group(1), match.group(2)
    if start_s == "" and end_s == "":
        return 0, file_size - 1, 416
    try:
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                return 0, file_size - 1, 416
            start = max(file_size - suffix, 0)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return 0, file_size - 1, 416
    if start < 0 or start >= file_size or end < start:
        return 0, file_size - 1, 416
    return start, min(end, file_size - 1), 206


def landing_video_response(request, file_path: Path) -> HttpResponse:
    """Stream landing.mp4 with range requests so the browser can seek a large file."""
    file_size = file_path.stat().st_size
    start, end, status = _byte_range(request.META.get("HTTP_RANGE"), file_size)
    if status == 416:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        response["Accept-Ranges"] = "bytes"
        return response

    length = 0 if end < start else end - start + 1
    handle = file_path.open("rb")
    if start:
        handle.seek(start)
    response = FileResponse(
        _BoundedReader(handle, length),
        status=status,
        content_type="video/mp4",
    )
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(length)
    response["Cache-Control"] = _LANDING_VIDEO_CACHE
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return response


def _resolve_frontend_dir(configured_dir: Path) -> Path:
    """Accept either a Flutter project root (build/web) or a prebuilt web dir."""
    # Prefer build/web when FRONTEND_BUILD_DIR points at the Flutter project root so
    # an older copied index.html at the project root does not shadow a fresh build.
    candidates = [configured_dir / "build" / "web", configured_dir]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    raise Http404("Frontend entrypoint not found.")


def serve_frontend(request, path: str = ""):
    admin_path = getattr(settings, "ADMIN_URL_PATH", "") or ""
    if admin_path and is_admin_request_path(request.path, admin_path):
        # Never fall back to the public chat UI for the private admin URL.
        raise Http404("Admin is not a frontend route.")

    configured_dir = Path(getattr(settings, "FRONTEND_BUILD_DIR", "/frontend"))
    if not configured_dir.exists():
        raise Http404("Frontend build directory not found.")
    build_dir = _resolve_frontend_dir(configured_dir)

    normalized_path = (path or "").lstrip("/")
    if Path(normalized_path).name == VIMEO_EMBED_FILENAME:
        return vimeo_embed_response(configured_dir)
    if normalized_path == LANDING_VIDEO_RELATIVE.as_posix():
        video_path = resolve_landing_video(configured_dir, build_dir)
        if video_path is None:
            raise Http404("Frontend asset not found.")
        return landing_video_response(request, video_path)

    candidate = (build_dir / normalized_path).resolve()
    build_dir_resolved = build_dir.resolve()

    # Block path traversal outside of the mounted frontend directory.
    try:
        candidate.relative_to(build_dir_resolved)
    except ValueError:
        raise Http404("Invalid path.")

    if candidate.is_file():
        file_path = candidate
    elif Path(normalized_path).suffix:
        # Missing static assets (e.g. .js/.css) should return 404 instead of index.html.
        raise Http404("Frontend asset not found.")
    else:
        file_path = build_dir / "index.html"
    if not file_path.exists():
        raise Http404("Frontend entrypoint not found.")

    content_type, _ = mimetypes.guess_type(str(file_path))
    if file_path.name.lower() == "index.html":
        response = HttpResponse(
            file_path.read_text(encoding="utf-8"),
            content_type="text/html; charset=utf-8",
        )
        _apply_cache_headers(response)
        # Express wallets (Apple Pay, Link, Amazon Pay) need Payment Request.
        response["Permissions-Policy"] = "payment=*"
        return response

    response = FileResponse(open(file_path, "rb"), content_type=content_type or "application/octet-stream")
    _apply_cache_headers(response)
    if file_path.name == VIMEO_EMBED_FILENAME:
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response
