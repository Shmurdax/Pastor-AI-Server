"""Sync Daily Devotionals from a Vimeo Folder (project) into MediaVideo rows."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .models import MediaVideo

logger = logging.getLogger(__name__)

VIMEO_API_BASE = "https://api.vimeo.com"
VIMEO_ACCEPT = "application/vnd.vimeo.*+json;version=3.4"


class VimeoSyncError(Exception):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": VIMEO_ACCEPT,
    }


def _extract_vimeo_id_and_hash(uri: str) -> tuple[str, str]:
    """Parse `/videos/123` or unlisted `/videos/123:privacyhash`."""
    parts = (uri or "").rstrip("/").split("/")
    if not parts:
        raise VimeoSyncError(f"Could not parse Vimeo id from uri={uri!r}")
    segment = parts[-1]
    video_id, _, privacy_hash = segment.partition(":")
    if video_id.isdigit():
        return video_id, privacy_hash
    match = re.search(r"/videos/(\d+)(?::([0-9a-fA-F]+))?", uri or "")
    if not match:
        raise VimeoSyncError(f"Could not parse Vimeo id from uri={uri!r}")
    return match.group(1), match.group(2) or ""


def privacy_hash_from_video(video: dict[str, Any], uri_hash: str = "") -> str:
    """Prefer the URI hash, then player embed / watch URLs (`?h=` or `/id/hash`)."""
    if uri_hash:
        return uri_hash
    sources: list[str] = [
        str(video.get("player_embed_url") or ""),
        str(video.get("link") or ""),
    ]
    embed = video.get("embed")
    if isinstance(embed, dict):
        sources.append(str(embed.get("html") or ""))
        sources.append(str(embed.get("url") or ""))
    elif embed:
        sources.append(str(embed))
    for source in sources:
        match = re.search(r"[?&]h=([0-9a-fA-F]+)", source)
        if match:
            return match.group(1)
        match = re.search(r"vimeo\.com/\d+/([0-9a-fA-F]+)", source)
        if match:
            return match.group(1)
    return ""




def _best_thumbnail(pictures: dict[str, Any] | None) -> str:
    if not pictures:
        return ""
    sizes = pictures.get("sizes") or []
    if not sizes:
        return ""
    best = max(sizes, key=lambda s: int(s.get("width") or 0))
    return (best.get("link") or "").strip()


def _parse_published_at(video: dict[str, Any]) -> datetime:
    raw = (
        video.get("release_time")
        or video.get("created_time")
        or video.get("modified_time")
        or ""
    )
    parsed = parse_datetime(raw) if raw else None
    if parsed is None:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _resolve_user_id(token: str, user_id: str | None) -> str:
    if user_id and user_id.strip():
        return user_id.strip()
    me = requests.get(f"{VIMEO_API_BASE}/me", headers=_headers(token), timeout=30)
    me.raise_for_status()
    user_uri = (me.json().get("uri") or "").rstrip("/")
    resolved = user_uri.split("/")[-1]
    if not resolved.isdigit():
        raise VimeoSyncError("Could not resolve Vimeo user id from /me")
    return resolved


def _fetch_folder_page(token: str, url: str) -> requests.Response:
    return requests.get(url, headers=_headers(token), timeout=60)


def _fetch_folder_videos(
    token: str,
    folder_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch videos from a Vimeo Folder (API name: project)."""
    resolved_user = _resolve_user_id(token, user_id)
    videos: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    while True:
        qs = urlencode(
            {"page": page, "per_page": per_page, "sort": "date", "direction": "desc"}
        )
        candidates = [
            f"{VIMEO_API_BASE}/users/{resolved_user}/projects/{folder_id}/videos?{qs}",
            f"{VIMEO_API_BASE}/me/projects/{folder_id}/videos?{qs}",
        ]
        res = None
        last_error = ""
        for url in candidates:
            attempt = _fetch_folder_page(token, url)
            if attempt.status_code < 400:
                res = attempt
                break
            last_error = f"{attempt.status_code}: {attempt.text[:500]}"
            # 404 on one path — try next; other errors still try fallback once
            if attempt.status_code not in (403, 404):
                continue
        if res is None:
            raise VimeoSyncError(f"Vimeo folder API error {last_error}")

        payload = res.json()
        batch = payload.get("data") or []
        videos.extend(batch)
        paging = payload.get("paging") or {}
        if not paging.get("next") or not batch:
            break
        page += 1
        if page > 100:
            break
    return videos


def sync_vimeo_media(
    *,
    token: str | None = None,
    folder_id: str | None = None,
    user_id: str | None = None,
    free_preview_id: str | None = None,
) -> dict[str, int]:
    token = (token if token is not None else settings.VIMEO_ACCESS_TOKEN or "").strip()
    folder_id = (
        folder_id if folder_id is not None else getattr(settings, "VIMEO_FOLDER_ID", "") or ""
    ).strip()
    # Back-compat: older configs used VIMEO_SHOWCASE_ID for the collection id.
    if not folder_id:
        folder_id = (getattr(settings, "VIMEO_SHOWCASE_ID", "") or "").strip()
    user_id = (
        user_id if user_id is not None else getattr(settings, "VIMEO_USER_ID", "") or ""
    ).strip() or None
    free_preview_id = (
        free_preview_id
        if free_preview_id is not None
        else settings.VIMEO_FREE_PREVIEW_ID or ""
    ).strip()

    if not token:
        raise VimeoSyncError("VIMEO_ACCESS_TOKEN is not configured")
    if not folder_id:
        raise VimeoSyncError("VIMEO_FOLDER_ID is not configured")

    remote = _fetch_folder_videos(token, folder_id, user_id=user_id)
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()
    created = updated = 0

    for video in remote:
        try:
            vimeo_id, uri_hash = _extract_vimeo_id_and_hash(video.get("uri") or "")
        except VimeoSyncError:
            logger.warning("Skipping Vimeo row without id: %s", video.get("uri"))
            continue
        seen_ids.add(vimeo_id)
        privacy_hash = privacy_hash_from_video(video, uri_hash)

        defaults = {
            "title": (video.get("name") or f"Vimeo {vimeo_id}").strip()[:300],
            "description": (video.get("description") or "").strip(),
            "published_at": _parse_published_at(video),
            "duration_seconds": int(video.get("duration") or 0),
            "thumbnail_url": _best_thumbnail(video.get("pictures")),
            "privacy_hash": privacy_hash,
            "is_published": True,
            "synced_at": now,
        }

        obj, was_created = MediaVideo.objects.update_or_create(
            vimeo_id=vimeo_id,
            defaults=defaults,
        )
        if not obj.access_tier_manual:
            desired = (
                MediaVideo.AccessTier.FREE_PREVIEW
                if free_preview_id and vimeo_id == free_preview_id
                else MediaVideo.AccessTier.PREMIUM
            )
            if obj.access_tier != desired:
                obj.access_tier = desired
                obj.save(update_fields=["access_tier", "updated_at"])

        if was_created:
            created += 1
        else:
            updated += 1

    # Soft-hide videos removed from the folder
    unpublished = 0
    for row in MediaVideo.objects.filter(is_published=True).exclude(vimeo_id__in=seen_ids):
        row.is_published = False
        row.synced_at = now
        row.save(update_fields=["is_published", "synced_at", "updated_at"])
        unpublished += 1

    return {
        "fetched": len(remote),
        "created": created,
        "updated": updated,
        "unpublished": unpublished,
    }


# Back-compat alias
sync_vimeo_showcase = sync_vimeo_media
