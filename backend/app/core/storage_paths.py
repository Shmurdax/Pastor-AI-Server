"""Durable on-disk paths for admin ingestion PDFs.

On RunPod the network volume survives container recreate; the git-synced
``backend/app/uploads`` tree does not (install.sh rsync --delete). Prefer
``INGESTION_UPLOAD_DIR`` (typically ``/workspace/persistent/uploads/admin_ingestion``).
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
