"""Download Walk through the Word study notes from a Dropbox folder."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.utils.text import get_valid_filename

from core.ingestion_service import is_document_filename
from core.ingestion_tasks import StagedUpload, enqueue_ingestion_job
from core.models import IngestionJob, IngestionJobLog
from core.postgres_sequences import create_ingestion_job

logger = logging.getLogger(__name__)

DROPBOX_API = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT = "https://content.dropboxapi.com/2"
_YEAR_FOLDER_RE = re.compile(r"^20\d{2}$")


class DropboxNotesError(Exception):
    pass


@dataclass(frozen=True)
class DropboxNoteFile:
    name: str
    path: str
    ingest_name: str


def dropbox_notes_configured(
    *,
    token: str | None = None,
    folder: str | None = None,
    shared_url: str | None = None,
) -> bool:
    token = (token if token is not None else getattr(settings, "DROPBOX_ACCESS_TOKEN", "") or "").strip()
    folder = (folder if folder is not None else getattr(settings, "DROPBOX_NOTES_FOLDER", "") or "").strip()
    shared_url = (
        shared_url if shared_url is not None else getattr(settings, "DROPBOX_SHARED_URL", "") or ""
    ).strip()
    return bool(token) and bool(folder or shared_url)


def _normalize_folder(path: str) -> str:
    text = (path or "").strip()
    if not text or text == "/":
        return ""
    if not text.startswith("/"):
        text = f"/{text}"
    return text.rstrip("/")


def _ingest_name(dropbox_path: str, filename: str) -> str:
    parts = [part for part in (dropbox_path or "").strip("/").split("/") if part]
    year = next((part for part in parts[:-1] if _YEAR_FOLDER_RE.fullmatch(part)), None)
    if year and year not in filename:
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        return f"{stem} {year}{suffix}"
    return filename


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _raise_for_dropbox(response: requests.Response, action: str) -> None:
    if response.status_code < 400:
        return
    detail = (response.text or "")[:400]
    if response.status_code in (401, 403):
        raise DropboxNotesError(
            "Dropbox rejected the access token. Create an app token with "
            "files.content.read and files.metadata.read, then set DROPBOX_ACCESS_TOKEN."
        )
    raise DropboxNotesError(f"Dropbox {action} failed ({response.status_code}): {detail}")


def _list_folder_page(token: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        url,
        headers={**_auth_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    _raise_for_dropbox(response, "list")
    body = response.json()
    if not isinstance(body, dict):
        raise DropboxNotesError("Dropbox list_folder returned an unexpected payload.")
    return body


def list_dropbox_note_files(
    *,
    token: str | None = None,
    folder: str | None = None,
    shared_url: str | None = None,
) -> list[DropboxNoteFile]:
    token = (token if token is not None else getattr(settings, "DROPBOX_ACCESS_TOKEN", "") or "").strip()
    folder = _normalize_folder(
        folder if folder is not None else getattr(settings, "DROPBOX_NOTES_FOLDER", "") or ""
    )
    shared_url = (
        shared_url if shared_url is not None else getattr(settings, "DROPBOX_SHARED_URL", "") or ""
    ).strip()
    if not token:
        raise DropboxNotesError("DROPBOX_ACCESS_TOKEN is not configured")
    if not folder and not shared_url:
        raise DropboxNotesError("Set DROPBOX_NOTES_FOLDER or DROPBOX_SHARED_URL")

    payload: dict[str, Any] = {
        "path": folder if not shared_url else (folder or ""),
        "recursive": True,
        "include_non_downloadable_files": False,
    }
    if shared_url:
        payload["shared_link"] = {"url": shared_url}

    body = _list_folder_page(token, f"{DROPBOX_API}/files/list_folder", payload)
    entries: list[dict[str, Any]] = list(body.get("entries") or [])
    cursor = body.get("cursor") or ""
    while body.get("has_more") and cursor:
        body = _list_folder_page(
            token,
            f"{DROPBOX_API}/files/list_folder/continue",
            {"cursor": cursor},
        )
        entries.extend(body.get("entries") or [])
        cursor = body.get("cursor") or ""

    notes: list[DropboxNoteFile] = []
    for entry in entries:
        if (entry.get(".tag") or "") != "file":
            continue
        name = str(entry.get("name") or "").strip()
        path = str(entry.get("path_display") or entry.get("path_lower") or "").strip()
        if not name or not is_document_filename(name):
            continue
        notes.append(
            DropboxNoteFile(
                name=name,
                path=path or f"/{name}",
                ingest_name=_ingest_name(path, name),
            )
        )
    notes.sort(key=lambda item: item.ingest_name.lower())
    return notes


def download_dropbox_file(
    *,
    dest: Path,
    path: str,
    token: str | None = None,
    shared_url: str | None = None,
) -> None:
    token = (token if token is not None else getattr(settings, "DROPBOX_ACCESS_TOKEN", "") or "").strip()
    shared_url = (
        shared_url if shared_url is not None else getattr(settings, "DROPBOX_SHARED_URL", "") or ""
    ).strip()
    if not token:
        raise DropboxNotesError("DROPBOX_ACCESS_TOKEN is not configured")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shared_url:
        endpoint = f"{DROPBOX_CONTENT}/sharing/get_shared_link_file"
        arg: dict[str, Any] = {"url": shared_url, "path": path}
    else:
        endpoint = f"{DROPBOX_CONTENT}/files/download"
        arg = {"path": path}
    response = requests.post(
        endpoint,
        headers={
            **_auth_headers(token),
            "Dropbox-API-Arg": json.dumps(arg),
        },
        timeout=180,
    )
    _raise_for_dropbox(response, "download")
    dest.write_bytes(response.content)


def enqueue_dropbox_notes_ingest(
    *,
    started_by: str = "dropbox-notes",
    replace_existing_sources: bool = False,
    token: str | None = None,
    folder: str | None = None,
    shared_url: str | None = None,
) -> IngestionJob:
    """Download Dropbox notes, then ingest them as sermon documents."""
    notes = list_dropbox_note_files(token=token, folder=folder, shared_url=shared_url)
    if not notes:
        raise DropboxNotesError(
            "No PDF, DOCX, TXT, or Markdown files were found in that Dropbox folder."
        )

    job = create_ingestion_job(
        started_by=started_by or "dropbox-notes",
        job_kind="document",
        replace_existing_sources=replace_existing_sources,
        view_only=True,
        in_library=True,
        status="running",
        files_received=len(notes),
    )
    IngestionJobLog.objects.create(
        job=job,
        message=f"Downloading {len(notes)} Walk through the Word note file(s) from Dropbox.",
    )
    staging_dir = Path(settings.BASE_DIR) / "uploads" / "admin_ingestion_jobs" / f"job_{job.id}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged: list[StagedUpload] = []
    try:
        for idx, note in enumerate(notes):
            safe_name = get_valid_filename(note.ingest_name) or f"notes_{idx}.pdf"
            dest = staging_dir / f"{idx:04d}_{safe_name}"
            download_dropbox_file(
                dest=dest,
                path=note.path,
                token=token,
                shared_url=shared_url,
            )
            staged.append(StagedUpload(original_name=note.ingest_name, staged_path=str(dest)))
            IngestionJobLog.objects.create(job=job, message=f"Downloaded {note.ingest_name}.")
    except Exception:
        job.status = "failed"
        job.error_message = "Dropbox download failed before ingest started."
        job.save(update_fields=["status", "error_message", "updated_at"])
        raise

    enqueue_ingestion_job(
        job.id,
        staged,
        replace_existing_sources=replace_existing_sources,
    )
    logger.info("Queued Dropbox notes ingest job %s with %s files", job.id, len(staged))
    return job
