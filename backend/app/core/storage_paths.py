"""Durable on-disk paths for admin ingestion PDFs and videos.

On RunPod the network volume survives container recreate; the git-synced
``backend/app/uploads`` tree does not (install.sh rsync --delete). Prefer
``INGESTION_UPLOAD_DIR`` (typically ``/workspace/persistent/uploads/admin_ingestion``)
and ``VIDEO_INGESTION_UPLOAD_DIR`` for original video files.

In-flight Whisper jobs and Cloudflare chunk assemblies must use the same
persistent volume. Otherwise a ``start.sh`` / rsync deploy deletes the queue
and the sermons have to be uploaded again.
"""
from __future__ import annotations

import os
from pathlib import Path


def _settings_upload(subdir: str) -> Path:
    from django.conf import settings

    return Path(settings.BASE_DIR) / "uploads" / subdir


def _dir_from_env(env_name: str, fallback_subdir: str) -> Path:
    raw = (os.getenv(env_name) or "").strip()
    path = Path(raw) if raw else _settings_upload(fallback_subdir)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def admin_ingestion_dir() -> Path:
    return _dir_from_env("INGESTION_UPLOAD_DIR", "admin_ingestion")


def admin_video_ingestion_dir() -> Path:
    return _dir_from_env("VIDEO_INGESTION_UPLOAD_DIR", "admin_video_ingestion")


def admin_video_ingestion_jobs_dir() -> Path:
    return _dir_from_env("VIDEO_INGESTION_JOBS_DIR", "admin_video_ingestion_jobs")


def admin_video_ingestion_chunks_dir() -> Path:
    return _dir_from_env("VIDEO_INGESTION_CHUNKS_DIR", "admin_video_ingestion_chunks")


def video_job_staging_dir(job_id: int) -> Path:
    path = admin_video_ingestion_jobs_dir() / f"job_{int(job_id)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingested_media_path(source_name: str, source_kind: str = "document") -> Path:
    filename = Path(source_name).name
    root = admin_video_ingestion_dir() if source_kind == "video" else admin_ingestion_dir()
    return (root / filename).resolve()
