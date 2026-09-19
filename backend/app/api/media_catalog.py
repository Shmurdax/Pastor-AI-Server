"""Public Daily Devotionals catalog for GET /api/media/.

The Flutter media page historically only listed `MediaVideo` rows created by
`sync_vimeo_media` (Vimeo Folder API). Admin **Embedded Videos** already builds
playable `player.vimeo.com` links from ingested sermon downloads. This module
unions those two catalogs so Premium members see the same Vimeo embeds.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone
from rest_framework.fields import DateTimeField

from api.models import MediaVideo
from api.serializers import MediaVideoSerializer
from core.embedded_videos import EmbeddedVideo, list_embedded_videos


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
