"""Map ingested Vimeo file IDs to the titles shown on the Vimeo folder page.

Downloaded files are often named ``461937715.m4a``. Ingest then stores that
numeric stem as ``IngestedDocument.title``. The Vimeo folder still has the
human sermon names; this module fetches them with a personal access token
(the folder is not readable anonymously) and writes them onto existing rows.

Chat citations already prefer ``IngestedDocument.title`` over the filename.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from .models import IngestedChunk, IngestedDocument
from .qdrant_utils import get_collection_name, get_qdrant_url
from .storage_paths import admin_video_ingestion_dir

DEFAULT_VIMEO_FOLDER_URL = (
    "https://vimeo.com/user/21759939/folder/24205069"
)
VIMEO_API_ROOT = "https://api.vimeo.com"
_FOLDER_URL_RE = re.compile(
    r"/user(?:s)?/(?P<user>\d+)/(?:folder|folders|projects)/(?P<folder>\d+)",
    re.IGNORECASE,
)
_VIDEO_URI_RE = re.compile(r"/videos/(?P<id>\d+)")
_NUMERIC_STEM_RE = re.compile(r"^\d{5,}$")
_TITLE_MAX_LEN = 300


class VimeoTitleError(RuntimeError):
    """Raised when the Vimeo API cannot be used to load titles."""


@dataclass
class TitleApplyResult:
    updated: int = 0
    already_matched: int = 0
    unmatched: int = 0
    qdrant_updated: int = 0
    sidecars_updated: int = 0
    sample_updates: list[tuple[str, str, str]] = field(default_factory=list)
    unmatched_ids: list[str] = field(default_factory=list)


def vimeo_id_from_source_name(source_name: str) -> Optional[str]:
    stem = Path(source_name or "").stem.strip()
    if _NUMERIC_STEM_RE.match(stem):
        return stem
    return None


def parse_vimeo_folder_url(url: str) -> tuple[Optional[str], str]:
    text = (url or "").strip()
    match = _FOLDER_URL_RE.search(text)
    if not match:
        raise VimeoTitleError(
            "Folder URL must look like "
            "https://vimeo.com/user/21759939/folder/24205069"
        )
    return match.group("user"), match.group("folder")


def _truncate_title(title: str) -> str:
    cleaned = " ".join((title or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= _TITLE_MAX_LEN:
        return cleaned
    return cleaned[: _TITLE_MAX_LEN - 1].rstrip() + "…"


def _vimeo_request(path_or_url: str, token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise VimeoTitleError("A Vimeo access token is required to read folder titles.")
    url = path_or_url if path_or_url.startswith("http") else f"{VIMEO_API_ROOT}{path_or_url}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.vimeo.*+json;version=3.4",
            "User-Agent": "Pastor-AI-Server/vimeo-titles",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        if exc.code in (401, 403):
            raise VimeoTitleError(
                "Vimeo rejected the access token. Create a personal token with "
                "the public and private scopes, then try again."
            ) from exc
        raise VimeoTitleError(f"Vimeo API {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise VimeoTitleError(f"Could not reach Vimeo: {exc.reason}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise VimeoTitleError("Vimeo API returned non-JSON.") from exc
    if not isinstance(data, dict):
        raise VimeoTitleError("Vimeo API returned an unexpected payload.")
    return data


def _video_id_and_title(item: Mapping) -> Optional[tuple[str, str]]:
    uri = str(item.get("uri") or "")
    match = _VIDEO_URI_RE.search(uri)
    video_id = match.group("id") if match else ""
    if not video_id:
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        nested_uri = str(video.get("uri") or "")
        match = _VIDEO_URI_RE.search(nested_uri)
        video_id = match.group("id") if match else ""
        title = _truncate_title(str(video.get("name") or item.get("name") or ""))
    else:
        title = _truncate_title(str(item.get("name") or ""))
    if not video_id or not title:
        return None
    return video_id, title


def _paginate_videos(path: str, token: str) -> Dict[str, str]:
    titles: Dict[str, str] = {}
    params = {"per_page": 100, "fields": "uri,name,video.uri,video.name"}
    next_url = f"{path}?{urlencode(params)}"
    while next_url:
        payload = _vimeo_request(next_url, token)
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            parsed = _video_id_and_title(item)
            if parsed:
                titles[parsed[0]] = parsed[1]
        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        next_url = str(paging.get("next") or "")
    return titles


def fetch_folder_titles(folder_url: str, token: str) -> Dict[str, str]:
    user_id, folder_id = parse_vimeo_folder_url(folder_url)
    candidates = [
        f"/users/{user_id}/projects/{folder_id}/videos",
        f"/users/{user_id}/projects/{folder_id}/items",
        f"/me/projects/{folder_id}/videos",
        f"/me/projects/{folder_id}/items",
    ]
    last_error: Optional[VimeoTitleError] = None
    for path in candidates:
        try:
            titles = _paginate_videos(path, token)
        except VimeoTitleError as exc:
            last_error = exc
            continue
        if titles:
            return titles
    if last_error:
        raise last_error
    return {}


def fetch_video_title(video_id: str, token: str) -> Optional[str]:
    try:
        payload = _vimeo_request(f"/videos/{video_id}", token)
    except VimeoTitleError:
        return None
    parsed = _video_id_and_title(payload)
    return parsed[1] if parsed else _truncate_title(str(payload.get("name") or "")) or None


def titles_for_video_ids(
    video_ids: Iterable[str],
    *,
    token: str,
    folder_url: str = DEFAULT_VIMEO_FOLDER_URL,
) -> Dict[str, str]:
    wanted = {str(item) for item in video_ids if str(item).strip()}
    titles: Dict[str, str] = {}
    if folder_url:
        try:
            titles.update(fetch_folder_titles(folder_url, token))
        except VimeoTitleError as exc:
            if "rejected the access token" in str(exc):
                raise
            # Folder listing can 404 for some tokens; try per-video lookups.
    missing = [video_id for video_id in wanted if video_id not in titles]
    for video_id in missing:
        name = fetch_video_title(video_id, token)
        if name:
            titles[video_id] = name
    return {video_id: titles[video_id] for video_id in wanted if video_id in titles}


def resolve_ingest_title(original_name: str, *, token: Optional[str] = None) -> str:
    """Filename stem, or the Vimeo folder title when the stem is a video ID."""
    from .ingestion_service import _safe_upload_stem

    stem = _safe_upload_stem(original_name)
    token = (token if token is not None else os.getenv("VIMEO_ACCESS_TOKEN", "")).strip()
    video_id = vimeo_id_from_source_name(original_name)
    if not token or not video_id:
        return stem
    folder_url = os.getenv("VIMEO_FOLDER_URL", DEFAULT_VIMEO_FOLDER_URL)
    mapping = titles_for_video_ids([video_id], token=token, folder_url=folder_url)
    return mapping.get(video_id) or stem


def _update_sidecar_title(source_name: str, title: str) -> bool:
    upload_dir = admin_video_ingestion_dir()
    video_path = upload_dir / source_name
    sidecar = video_path.with_suffix(".transcript.json")
    if not sidecar.is_file():
        return False
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("title") == title:
        return False
    payload["title"] = title
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _update_qdrant_titles(document: IngestedDocument, title: str) -> int:
    point_ids = list(
        IngestedChunk.objects.filter(document=document).values_list("qdrant_point_id", flat=True)
    )
    if not point_ids:
        return 0
    try:
        from qdrant_client import QdrantClient
    except Exception:
        return 0
    url = os.getenv("QDRANT_URL") or getattr(settings, "QDRANT_URL", "") or get_qdrant_url()
    collection = os.getenv("QDRANT_COLLECTION") or get_collection_name()
    client = QdrantClient(url=url, timeout=20)
    client.set_payload(
        collection_name=collection,
        payload={"title": title},
        points=point_ids,
    )
    return len(point_ids)


def apply_vimeo_titles(
    mapping: Mapping[str, str],
    *,
    dry_run: bool = False,
    update_qdrant: bool = True,
    update_sidecars: bool = True,
) -> TitleApplyResult:
    result = TitleApplyResult()
    documents = IngestedDocument.objects.filter(source_kind="video")
    for document in documents.iterator():
        video_id = vimeo_id_from_source_name(document.source_name)
        if not video_id or video_id not in mapping:
            if video_id:
                result.unmatched += 1
                if len(result.unmatched_ids) < 20:
                    result.unmatched_ids.append(video_id)
            continue
        new_title = mapping[video_id]
        if (document.title or "").strip() == new_title:
            result.already_matched += 1
            continue
        if len(result.sample_updates) < 8:
            result.sample_updates.append((document.source_name, document.title, new_title))
        if dry_run:
            result.updated += 1
            continue
        document.title = new_title
        document.save(update_fields=["title", "updated_at"])
        result.updated += 1
        if update_sidecars and _update_sidecar_title(document.source_name, new_title):
            result.sidecars_updated += 1
        if update_qdrant:
            result.qdrant_updated += _update_qdrant_titles(document, new_title)
    return result


def apply_titles_from_vimeo_folder(
    *,
    folder_url: str,
    token: str,
    dry_run: bool = False,
    update_qdrant: bool = True,
) -> tuple[Dict[str, str], TitleApplyResult]:
    documents = list(IngestedDocument.objects.filter(source_kind="video"))
    video_ids = [
        video_id
        for video_id in (vimeo_id_from_source_name(doc.source_name) for doc in documents)
        if video_id
    ]
    mapping = titles_for_video_ids(video_ids, token=token, folder_url=folder_url)
    result = apply_vimeo_titles(
        mapping,
        dry_run=dry_run,
        update_qdrant=update_qdrant and not dry_run,
    )
    return mapping, result
