"""Durable on-disk paths for admin ingestion PDFs and videos.

On RunPod the network volume survives container recreate; the git-synced
``backend/app/uploads`` tree does not (install.sh rsync --delete). Prefer
``INGESTION_UPLOAD_DIR`` (typically ``/workspace/persistent/uploads/admin_ingestion``)
and ``VIDEO_INGESTION_UPLOAD_DIR`` for original video files.
"""
from __future__ import annotations

import os
from pathlib import Path


def admin_ingestion_dir() -> Path:
    raw = (os.getenv("INGESTION_UPLOAD_DIR") or "").strip()
    if raw:
        path = Path(raw)
    else:
        from django.conf import settings

        path = Path(settings.BASE_DIR) / "uploads" / "admin_ingestion"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def admin_video_ingestion_dir() -> Path:
    raw = (os.getenv("VIDEO_INGESTION_UPLOAD_DIR") or "").strip()
    if raw:
        path = Path(raw)
    else:
        from django.conf import settings

        path = Path(settings.BASE_DIR) / "uploads" / "admin_video_ingestion"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def ingested_media_path(source_name: str, source_kind: str = "document") -> Path:
    filename = Path(source_name).name
    root = admin_video_ingestion_dir() if source_kind == "video" else admin_ingestion_dir()
    return (root / filename).resolve()
