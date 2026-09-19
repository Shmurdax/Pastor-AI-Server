"""Public Daily Devotionals catalog for GET /api/media/.

The Flutter media page historically only listed `MediaVideo` rows created by
`sync_vimeo_media` (Vimeo Folder API). Admin **Embedded Videos** already builds
playable `player.vimeo.com` links from ingested sermon downloads. This module
unions those two catalogs so Premium members see the same Vimeo embeds.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.fields import DateTimeField

from api.models import MediaVideo
from api.serializers import MediaVideoSerializer
from core.embedded_videos import EmbeddedVideo, list_embedded_videos

VIMEO_FOLDER_CATALOG_PATH = (
    Path(__file__).resolve().parent / "data" / "vimeo_folder_24205069.json"
)


def duration_label(seconds: int) -> str:
    total = int(seconds or 0)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _aware(dt: datetime | None) -> datetime:
    if dt is None:
        return timezone.now()
    if timezone.is_naive(dt):
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt


def embedded_video_to_media_payload(video: EmbeddedVideo) -> dict[str, Any]:
    published = _aware(video.published_at)
    duration = int(video.duration_seconds or 0)
    access = (video.access_tier or MediaVideo.AccessTier.PREMIUM).strip()
    if access not in {choice.value for choice in MediaVideo.AccessTier}:
        access = MediaVideo.AccessTier.PREMIUM
    return {
        "id": video.vimeo_id,
        "vimeo_id": video.vimeo_id,
        "privacy_hash": video.privacy_hash or "",
        "title": video.title,
        "description": video.description or "",
        "published_at": DateTimeField().to_representation(published),
        "duration_seconds": duration,
        "duration_label": duration_label(duration),
        "thumbnail_url": video.thumbnail_url or "",
        "access_tier": access,
        "is_published": True,
    }


def _payload_from_row(row: MediaVideo, *, force_published: bool = False) -> dict[str, Any]:
    data = MediaVideoSerializer(row).data
    if force_published:
        data["is_published"] = True
    return data


def public_media_catalog() -> list[dict[str, Any]]:
    """Published folder videos plus every admin Embedded Videos Vimeo embed."""
    rows = {row.vimeo_id: row for row in MediaVideo.objects.all()}
    payload_by_id: dict[str, dict[str, Any]] = {}

    for video in list_embedded_videos():
        row = rows.get(video.vimeo_id)
        if row is not None:
            data = _payload_from_row(row, force_published=True)
            if not (data.get("privacy_hash") or "").strip() and video.privacy_hash:
                data["privacy_hash"] = video.privacy_hash
            payload_by_id[video.vimeo_id] = data
            continue
        payload_by_id[video.vimeo_id] = embedded_video_to_media_payload(video)

    for row in rows.values():
        if not row.is_published or row.vimeo_id in payload_by_id:
            continue
        payload_by_id[row.vimeo_id] = _payload_from_row(row)

    payload = list(payload_by_id.values())
    payload.sort(key=lambda item: (item.get("title") or "").lower())
    payload.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return payload


def ensure_media_videos_from_embedded() -> dict[str, int]:
    """Create missing MediaVideo rows for admin Embedded Videos (idempotent)."""
    existing = set(MediaVideo.objects.values_list("vimeo_id", flat=True))
    created = 0
    videos = list_embedded_videos()
    now = timezone.now()
    for video in videos:
        if video.vimeo_id in existing:
            continue
        MediaVideo.objects.create(
            vimeo_id=video.vimeo_id,
            privacy_hash=video.privacy_hash or "",
            title=(video.title or f"Vimeo {video.vimeo_id}")[:300],
            description=video.description or "",
            published_at=_aware(video.published_at),
            duration_seconds=int(video.duration_seconds or 0),
            thumbnail_url=video.thumbnail_url or "",
            access_tier=(
                video.access_tier
                if video.access_tier in {choice.value for choice in MediaVideo.AccessTier}
                else MediaVideo.AccessTier.PREMIUM
            ),
            is_published=True,
            synced_at=now,
        )
        created += 1
        existing.add(video.vimeo_id)
    return {"embedded": len(videos), "created": created}


def load_committed_vimeo_folder_catalog(path: Path | None = None) -> dict[str, int]:
    """Upsert MediaVideo rows from the committed Vimeo folder embed dump."""
    catalog_path = path or VIMEO_FOLDER_CATALOG_PATH
    empty = {"loaded": 0, "created": 0, "updated": 0}
    if not catalog_path.is_file():
        return empty
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    videos = payload.get("videos") or payload.get("results") or []
    if not isinstance(videos, list):
        return empty
    now = timezone.now()
    created = updated = 0
    for item in videos:
        if not isinstance(item, dict):
            continue
        vimeo_id = str(item.get("vimeo_id") or "").strip()
        if not vimeo_id:
            continue
        published = parse_datetime(str(item.get("published_at") or "")) or now
        defaults = {
            "privacy_hash": str(item.get("privacy_hash") or "").strip(),
            "title": (str(item.get("title") or f"Vimeo {vimeo_id}").strip() or f"Vimeo {vimeo_id}")[:300],
            "description": str(item.get("description") or ""),
            "published_at": _aware(published),
            "duration_seconds": int(item.get("duration_seconds") or 0),
            "thumbnail_url": str(item.get("thumbnail_url") or "").strip()[:200],
            "is_published": True,
            "synced_at": now,
        }
        access = str(item.get("access_tier") or MediaVideo.AccessTier.PREMIUM).strip()
        obj, was_created = MediaVideo.objects.update_or_create(
            vimeo_id=vimeo_id,
            defaults=defaults,
        )
        if not obj.access_tier_manual and access in {
            choice.value for choice in MediaVideo.AccessTier
        }:
            if obj.access_tier != access:
                obj.access_tier = access
                obj.save(update_fields=["access_tier", "updated_at"])
        if was_created:
            created += 1
        else:
            updated += 1
    return {"loaded": len(videos), "created": created, "updated": updated}
