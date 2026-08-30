"""Match ingested sermon audio to Vimeo embeds for the admin player page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .models import IngestedDocument
from .storage_paths import admin_video_ingestion_dir
from .transcript_normalize import format_timestamp
from .video_ingestion import MEDIA_EXTENSIONS

# Numeric stems from Vimeo downloads (e.g. 1217796650.m4a).
VIMEO_ID_RE = re.compile(r"^(\d{6,12})$")

# Known Vimeo pages to embed even before a local file exists.
# match_source_stem: older ingested audio/transcript whose words are this video
# (same sermon re-uploaded to a new Vimeo id).
FEATURED_VIMEO_VIDEOS = (
    {
        "vimeo_id": "1217796650",
        "watch_url": "https://vimeo.com/1217796650?fl=ip&fe=ec",
        "fallback_title": "Walk Through the Word — January 4",
        # Live ingest of the January 4 session (Genesis 11 / Tower of Babel).
        # Vimeo title for 1217796650 is "Copy of January 4".
        "match_source_stem": "382080991",
    },
)


@dataclass
class TranscriptSegmentView:
    start: float
    end: float
    text: str
    start_label: str
    end_label: str

    @property
    def range_label(self) -> str:
        return f"{self.start_label}–{self.end_label}"


@dataclass
class EmbeddedVideo:
    vimeo_id: str
    watch_url: str
    embed_url: str
    title: str
    source_name: Optional[str] = None
    media_name: Optional[str] = None
    has_media: bool = False
    has_transcript: bool = False
    transcript_segment_count: int = 0
    featured: bool = False
    document_title: Optional[str] = None
    sidecar_title: Optional[str] = None
    whisper_model: Optional[str] = None
    transcript_source: Optional[str] = None
    segments: list[TranscriptSegmentView] = field(default_factory=list)

    @property
    def embed_src(self) -> str:
        return f"{self.embed_url}?dnt=1"


def parse_vimeo_id(value: str) -> Optional[str]:
    text = (value or "").strip()
    match = VIMEO_ID_RE.fullmatch(text)
    return match.group(1) if match else None


def parse_vimeo_id_from_filename(name: str) -> Optional[str]:
    stem = Path(name or "").stem
    return parse_vimeo_id(stem)


def vimeo_watch_url(vimeo_id: str, featured_urls: Optional[dict[str, str]] = None) -> str:
    featured = featured_urls if featured_urls is not None else _featured_watch_urls()
    return featured.get(vimeo_id, f"https://vimeo.com/{vimeo_id}")


def vimeo_embed_url(vimeo_id: str) -> str:
    return f"https://player.vimeo.com/video/{vimeo_id}"


def _featured_watch_urls() -> dict[str, str]:
    return {
        item["vimeo_id"]: item["watch_url"]
        for item in FEATURED_VIMEO_VIDEOS
        if item.get("vimeo_id") and item.get("watch_url")
    }


def _featured_fallback_titles() -> dict[str, str]:
    return {
        item["vimeo_id"]: item.get("fallback_title") or f"Vimeo {item['vimeo_id']}"
        for item in FEATURED_VIMEO_VIDEOS
        if item.get("vimeo_id")
    }


def _featured_match_stems() -> dict[str, str]:
    return {
        item["vimeo_id"]: str(item["match_source_stem"]).strip()
        for item in FEATURED_VIMEO_VIDEOS
        if item.get("vimeo_id") and item.get("match_source_stem")
    }


def lookup_stems_for_vimeo_id(vimeo_id: str) -> list[str]:
    """Filenames to try: the embed id, then any mapped older ingest stem."""
    stems = [vimeo_id]
    mapped = _featured_match_stems().get(vimeo_id)
    if mapped and mapped not in stems:
        stems.append(mapped)
    return stems


def _iter_media_files(upload_dir: Path) -> Iterable[Path]:
    if not upload_dir.is_dir():
        return
    for path in upload_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        yield path


def _index_media_and_sidecars(upload_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    media: dict[str, Path] = {}
    sidecars: dict[str, Path] = {}
    if not upload_dir.is_dir():
        return media, sidecars
    for path in upload_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".transcript.json"):
            vimeo_id = parse_vimeo_id(name[: -len(".transcript.json")])
            if vimeo_id and vimeo_id not in sidecars:
                sidecars[vimeo_id] = path
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        vimeo_id = parse_vimeo_id_from_filename(name)
        if vimeo_id and vimeo_id not in media:
            media[vimeo_id] = path
    return media, sidecars


def find_media_for_vimeo_id(vimeo_id: str, upload_dir: Path) -> Optional[Path]:
    stems = lookup_stems_for_vimeo_id(vimeo_id)
    for stem in stems:
        for ext in sorted(MEDIA_EXTENSIONS):
            candidate = upload_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    wanted = set(stems)
    for path in _iter_media_files(upload_dir):
        if parse_vimeo_id_from_filename(path.name) in wanted:
            return path
    return None


def find_sidecar_for_vimeo_id(vimeo_id: str, upload_dir: Path, media_path: Optional[Path] = None) -> Optional[Path]:
    candidates = []
    if media_path is not None:
        candidates.append(media_path.with_suffix(".transcript.json"))
    for stem in lookup_stems_for_vimeo_id(vimeo_id):
        candidates.append(upload_dir / f"{stem}.transcript.json")
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _float_or_zero(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def segments_from_sidecar_payload(payload: dict) -> list[TranscriptSegmentView]:
    raw = payload.get("segments_normalized") or payload.get("segments_raw") or []
    segments: list[TranscriptSegmentView] = []
    if not isinstance(raw, list):
        return segments
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        start = _float_or_zero(item.get("start"))
        end = _float_or_zero(item.get("end"))
        if not text and start == 0 and end == 0:
            continue
        segments.append(
            TranscriptSegmentView(
                start=start,
                end=end,
                text=text,
                start_label=format_timestamp(start),
                end_label=format_timestamp(end),
            )
        )
    return segments


def load_sidecar_payload(sidecar_path: Path) -> Optional[dict]:
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _documents_by_vimeo_id() -> dict[str, IngestedDocument]:
    found: dict[str, IngestedDocument] = {}
    for document in IngestedDocument.objects.filter(source_kind="video"):
        vimeo_id = parse_vimeo_id_from_filename(document.source_name)
        if not vimeo_id or vimeo_id in found:
            continue
        found[vimeo_id] = document
    return found


def _build_embedded_video(
    vimeo_id: str,
    *,
    upload_dir: Path,
    documents: dict[str, IngestedDocument],
    featured: bool = False,
    include_segments: bool = False,
    media_path: Optional[Path] = None,
    sidecar_path: Optional[Path] = None,
) -> EmbeddedVideo:
    if media_path is None:
        media_path = find_media_for_vimeo_id(vimeo_id, upload_dir)
    if sidecar_path is None:
        sidecar_path = find_sidecar_for_vimeo_id(vimeo_id, upload_dir, media_path)
    payload = None
    segments: list[TranscriptSegmentView] = []
    if include_segments and sidecar_path:
        payload = load_sidecar_payload(sidecar_path)
        segments = segments_from_sidecar_payload(payload) if payload else []
    document = None
    for stem in lookup_stems_for_vimeo_id(vimeo_id):
        document = documents.get(stem)
        if document:
            break
    sidecar_title = str(payload.get("title") or "").strip() if payload else ""
    document_title = (document.title or "").strip() if document else ""
    fallback_title = _featured_fallback_titles().get(vimeo_id, f"Vimeo {vimeo_id}")
    rejected_titles = set(lookup_stems_for_vimeo_id(vimeo_id))
    title = next(
        (
            candidate
            for candidate in (document_title, sidecar_title, fallback_title)
            if candidate and candidate not in rejected_titles
        ),
        fallback_title,
    )
    source_name = None
    if payload and payload.get("source_name"):
        source_name = str(payload["source_name"])
    elif document:
        source_name = document.source_name
    elif media_path:
        source_name = media_path.name
    has_transcript = bool(segments) if include_segments else sidecar_path is not None
    video = EmbeddedVideo(
        vimeo_id=vimeo_id,
        watch_url=vimeo_watch_url(vimeo_id),
        embed_url=vimeo_embed_url(vimeo_id),
        title=title,
        source_name=source_name,
        media_name=media_path.name if media_path else None,
        has_media=media_path is not None,
        has_transcript=has_transcript,
        transcript_segment_count=len(segments),
        featured=featured,
        document_title=document_title or None,
        sidecar_title=sidecar_title or None,
        whisper_model=str(payload.get("whisper_model") or "") or None if payload else None,
        transcript_source=sidecar_path.name if sidecar_path and has_transcript else None,
        segments=segments,
    )
    return video


def list_embedded_videos(upload_dir: Optional[Path] = None) -> list[EmbeddedVideo]:
    root = (upload_dir or admin_video_ingestion_dir()).resolve()
    documents = _documents_by_vimeo_id()
    featured_ids = [item["vimeo_id"] for item in FEATURED_VIMEO_VIDEOS if item.get("vimeo_id")]
    media_index, sidecar_index = _index_media_and_sidecars(root)
    discovered: set[str] = set(featured_ids)
    discovered.update(documents.keys())
    discovered.update(media_index.keys())
    discovered.update(sidecar_index.keys())

    videos = [
        _build_embedded_video(
            vimeo_id,
            upload_dir=root,
            documents=documents,
            featured=vimeo_id in featured_ids,
            media_path=media_index.get(vimeo_id),
            sidecar_path=sidecar_index.get(vimeo_id),
        )
        for vimeo_id in discovered
    ]
    videos.sort(
        key=lambda item: (not item.featured, item.title.lower(), item.vimeo_id),
    )
    return videos


def get_embedded_video(vimeo_id: str, upload_dir: Optional[Path] = None) -> Optional[EmbeddedVideo]:
    parsed = parse_vimeo_id(vimeo_id)
    if not parsed:
        return None
    root = (upload_dir or admin_video_ingestion_dir()).resolve()
    featured_ids = {item["vimeo_id"] for item in FEATURED_VIMEO_VIDEOS if item.get("vimeo_id")}
    documents = _documents_by_vimeo_id()
    media_path = find_media_for_vimeo_id(parsed, root)
    sidecar_path = find_sidecar_for_vimeo_id(parsed, root, media_path)
    if parsed not in featured_ids and parsed not in documents and media_path is None and sidecar_path is None:
        return None
    return _build_embedded_video(
        parsed,
        upload_dir=root,
        documents=documents,
        featured=parsed in featured_ids,
        include_segments=True,
    )
