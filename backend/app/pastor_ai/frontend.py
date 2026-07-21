import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404


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
    configured_dir = Path(getattr(settings, "FRONTEND_BUILD_DIR", "/frontend"))
    if not configured_dir.exists():
        raise Http404("Frontend build directory not found.")
    build_dir = _resolve_frontend_dir(configured_dir)

    normalized_path = (path or "").lstrip("/")
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
    response = FileResponse(open(file_path, "rb"), content_type=content_type or "application/octet-stream")
    # Prevent caching to ensure fresh frontend deployments
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response
