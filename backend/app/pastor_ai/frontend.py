import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

from .admin_url import is_admin_request_path

# Existing Flutter web builds do not call warmup; inject a fire-and-forget ping
# so opening the homepage starts the serverless GPU while the user types.
_WARMUP_MARKER = "__pastorVllmWarmup"
_WARMUP_SCRIPT = (
    "<script>"
    "(function(){"
    "try{"
    f"if(window.{_WARMUP_MARKER})return;"
    f"window.{_WARMUP_MARKER}=1;"
    "fetch('/api/chat/warmup/',{method:'POST',"
    "headers:{'Accept':'application/json','Content-Type':'application/json'},"
    "body:'{}',credentials:'same-origin'}).catch(function(){});"
    "}catch(e){}"
    "})();"
    "</script>"
)

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


def _resolve_frontend_dir(configured_dir: Path) -> Path:
    """Accept either a Flutter project root (build/web) or a prebuilt web dir."""
    # Prefer build/web when FRONTEND_BUILD_DIR points at the Flutter project root so
    # an older copied index.html at the project root does not shadow a fresh build.
    candidates = [configured_dir / "build" / "web", configured_dir]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    raise Http404("Frontend entrypoint not found.")


def _index_html_with_warmup(file_path: Path) -> str:
    text = file_path.read_text(encoding="utf-8")
    if _WARMUP_MARKER in text:
        return text
    updated, count = re.subn(r"</body>", _WARMUP_SCRIPT + "</body>", text, count=1, flags=re.IGNORECASE)
    if count:
        return updated
    return text + _WARMUP_SCRIPT


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
            _index_html_with_warmup(file_path),
            content_type="text/html; charset=utf-8",
        )
        return _apply_cache_headers(response)

    response = FileResponse(open(file_path, "rb"), content_type=content_type or "application/octet-stream")
    _apply_cache_headers(response)
    if file_path.name == VIMEO_EMBED_FILENAME:
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response
