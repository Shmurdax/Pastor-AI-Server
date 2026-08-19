"""Disk-backed queue for video/audio ingestion jobs.

Gunicorn's in-process ThreadPoolExecutor dies on ``start.sh`` / worker recycle.
Staging files plus a per-job manifest let a dedicated worker resume Whisper
after those restarts. Hash skip still avoids re-transcribing sermons already
in the catalog.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Tuple

from .ingestion_tasks import StagedUpload
from .storage_paths import video_job_staging_dir

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"


def persist_video_job_manifest(
    job_id: int,
    staged_uploads: List[StagedUpload],
    replace_existing_sources: bool,
) -> Path:
    job_dir = video_job_staging_dir(job_id)
    payload = {
        "job_id": int(job_id),
        "replace_existing_sources": bool(replace_existing_sources),
        "files": [
            {
                "original_name": item.original_name,
                "file_name": Path(item.staged_path).name,
            }
            for item in staged_uploads
        ],
    }
    path = job_dir / MANIFEST_NAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def video_job_has_staging(job_id: int) -> bool:
    job_dir = video_job_staging_dir(job_id)
    if (job_dir / MANIFEST_NAME).is_file():
        return True
    return any(path.is_file() and path.name != MANIFEST_NAME for path in job_dir.iterdir())


def load_video_job_uploads(job_id: int) -> Tuple[List[StagedUpload], bool]:
    job_dir = video_job_staging_dir(job_id)
    manifest_path = job_dir / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        uploads: List[StagedUpload] = []
        for item in data.get("files") or []:
            file_name = str(item.get("file_name") or "").strip()
            original_name = str(item.get("original_name") or file_name).strip()
            if not file_name:
                continue
            path = job_dir / file_name
            if path.is_file() and path.stat().st_size > 0:
                uploads.append(StagedUpload(original_name=original_name or file_name, staged_path=str(path)))
        return uploads, bool(data.get("replace_existing_sources"))

    uploads = []
    for path in sorted(job_dir.iterdir()):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        original = path.name
        if len(original) > 5 and original[:4].isdigit() and original[4] == "_":
            original = original[5:]
        if path.stat().st_size > 0:
            uploads.append(StagedUpload(original_name=original, staged_path=str(path)))
    return uploads, False
