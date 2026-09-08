"""Match ingested sermon audio to Vimeo embeds for the admin player page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .models import IngestedDocument
from .storage_paths import admin_video_ingestion_dir
from .transcript_normalize import format_timestamp
from .video_ingestion import MEDIA_EXTENSIONS

# Numeric stems from Vimeo downloads (e.g. 1217796650.m4a).
VIMEO_ID_RE = re.compile(r"^(\d{6,12})$")
COPY_OF_RE = re.compile(r"(?i)^copy\s+of\s+")
MONTH_NAMES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
SERMON_DATE_RE = re.compile(
    r"(?i)(?:copy\s+of\s+)?"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[\s_\-]+(\d{1,2})(?:st|nd|rd|th)?(?!\d)"
)

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
class CatalogEntry:
    vimeo_id: str
    title: str
    privacy_hash: str = ""
    watch_url: str = ""
    featured: bool = False
    published_at: Optional[datetime] = None


@dataclass
class _MatchState:
    entry: CatalogEntry
    document: Optional[IngestedDocument] = None
    media_path: Optional[Path] = None
    sidecar_path: Optional[Path] = None


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
    matched_by_date: bool = False
    document_title: Optional[str] = None
    sidecar_title: Optional[str] = None
    whisper_model: Optional[str] = None
    transcript_source: Optional[str] = None
    segments: list[TranscriptSegmentView] = field(default_factory=list)

    @property
    def embed_src(self) -> str:
        return _url_with_query(self.embed_url, dnt="1")


def parse_vimeo_id(value: str) -> Optional[str]:
    text = (value or "").strip()
    match = VIMEO_ID_RE.fullmatch(text)
    return match.group(1) if match else None


def parse_vimeo_id_from_filename(name: str) -> Optional[str]:
    stem = Path(name or "").stem
    if stem.endswith(".transcript"):
        stem = stem[: -len(".transcript")]
    return parse_vimeo_id(stem)


def sermon_date_key(value: str) -> Optional[str]:
    """Stable month-day key from Vimeo titles or download names like april_10_v1_240p."""
    match = SERMON_DATE_RE.search(value or "")
    if not match:
        return None
    month = MONTH_NAMES.get(match.group(1).lower())
    if not month:
        return None
    day = int(match.group(2))
    if day < 1 or day > 31:
        return None
    return f"{month:02d}-{day:02d}"


def is_copy_title(title: str) -> bool:
    return bool(COPY_OF_RE.match((title or "").strip()))


def vimeo_watch_url(
    vimeo_id: str,
    featured_urls: Optional[dict[str, str]] = None,
    privacy_hash: str = "",
) -> str:
    featured = featured_urls if featured_urls is not None else _featured_watch_urls()
    if vimeo_id in featured:
        return featured[vimeo_id]
    hash_value = (privacy_hash or "").strip()
    if hash_value:
        return f"https://vimeo.com/{vimeo_id}/{hash_value}"
    return f"https://vimeo.com/{vimeo_id}"


def vimeo_embed_url(vimeo_id: str, privacy_hash: str = "") -> str:
    url = f"https://player.vimeo.com/video/{vimeo_id}"
    hash_value = (privacy_hash or "").strip()
    if hash_value:
        return f"{url}?h={hash_value}"
    return url


def _url_with_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        query[key] = [value]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


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


def _sidecar_stem(name: str) -> str:
    text = name or ""
    suffix = ".transcript.json"
    if text.endswith(suffix):
        return text[: -len(suffix)]
    return Path(text).stem


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
            vimeo_id = parse_vimeo_id(_sidecar_stem(name))
            if vimeo_id and vimeo_id not in sidecars:
                sidecars[vimeo_id] = path
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        vimeo_id = parse_vimeo_id_from_filename(name)
        if vimeo_id and vimeo_id not in media:
            media[vimeo_id] = path
    return media, sidecars


def find_media_for_vimeo_id(
    vimeo_id: str,
    upload_dir: Path,
    *,
    catalog_title: str = "",
) -> Optional[Path]:
    stems = lookup_stems_for_vimeo_id(vimeo_id)
    for stem in stems:
        for ext in sorted(MEDIA_EXTENSIONS):
            candidate = upload_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    wanted = set(stems)
    date_wanted = sermon_date_key(catalog_title)
    dated: Optional[Path] = None
    for path in _iter_media_files(upload_dir):
        if parse_vimeo_id_from_filename(path.name) in wanted:
            return path
        if date_wanted and dated is None and sermon_date_key(path.name) == date_wanted:
            dated = path
    return dated


def find_sidecar_for_vimeo_id(
    vimeo_id: str,
    upload_dir: Path,
    media_path: Optional[Path] = None,
    catalog_title: str = "",
) -> Optional[Path]:
    candidates = []
    if media_path is not None:
        candidates.append(media_path.with_name(f"{media_path.stem}.transcript.json"))
    for stem in lookup_stems_for_vimeo_id(vimeo_id):
        candidates.append(upload_dir / f"{stem}.transcript.json")
    date_wanted = sermon_date_key(catalog_title)
    if date_wanted and upload_dir.is_dir():
        for path in upload_dir.iterdir():
            if path.is_file() and path.name.endswith(".transcript.json"):
                if sermon_date_key(_sidecar_stem(path.name)) == date_wanted:
                    candidates.append(path)
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


def _load_catalog() -> tuple[dict[str, CatalogEntry], dict[str, list[CatalogEntry]]]:
    catalog: dict[str, CatalogEntry] = {}
    for item in FEATURED_VIMEO_VIDEOS:
        vimeo_id = str(item.get("vimeo_id") or "").strip()
        if not vimeo_id:
            continue
        catalog[vimeo_id] = CatalogEntry(
            vimeo_id=vimeo_id,
            title=str(item.get("fallback_title") or f"Vimeo {vimeo_id}"),
            watch_url=str(item.get("watch_url") or ""),
            featured=True,
        )
    try:
        from api.models import MediaVideo
    except ImportError:
        rows = []
    else:
        rows = list(MediaVideo.objects.all())
    for row in rows:
        vimeo_id = str(row.vimeo_id or "").strip()
        if not vimeo_id:
            continue
        existing = catalog.get(vimeo_id)
        title = (row.title or "").strip() or (existing.title if existing else f"Vimeo {vimeo_id}")
        privacy_hash = (row.privacy_hash or "").strip() or (existing.privacy_hash if existing else "")
        catalog[vimeo_id] = CatalogEntry(
            vimeo_id=vimeo_id,
            title=title,
            privacy_hash=privacy_hash,
            watch_url=(existing.watch_url if existing else ""),
            featured=bool(existing and existing.featured),
            published_at=row.published_at,
        )
        if not catalog[vimeo_id].watch_url:
            catalog[vimeo_id].watch_url = vimeo_watch_url(vimeo_id, privacy_hash=privacy_hash)

    date_index: dict[str, list[CatalogEntry]] = {}
    for entry in catalog.values():
        key = sermon_date_key(entry.title)
        if not key:
            continue
        date_index.setdefault(key, []).append(entry)
    return catalog, date_index


def _pick_catalog_video(candidates: list[CatalogEntry]) -> CatalogEntry:
    if len(candidates) == 1:
        return candidates[0]
    featured = [item for item in candidates if item.featured]
    if featured:
        return featured[0]
    non_copy = [item for item in candidates if not is_copy_title(item.title)]
    pool = non_copy or candidates

    def sort_key(item: CatalogEntry) -> tuple:
        published = item.published_at or datetime.min
        try:
            numeric_id = int(item.vimeo_id)
        except (TypeError, ValueError):
            numeric_id = 0
        return (published, numeric_id)

    return max(pool, key=sort_key)


def match_source_to_catalog(
    name: str,
    catalog: dict[str, CatalogEntry],
    date_index: dict[str, list[CatalogEntry]],
) -> Optional[CatalogEntry]:
    stem = Path(name or "").stem
    if stem.endswith(".transcript"):
        stem = stem[: -len(".transcript")]
    featured_stems = _featured_match_stems()
    for vimeo_id, mapped in featured_stems.items():
        if stem == mapped and vimeo_id in catalog:
            return catalog[vimeo_id]
    numeric = parse_vimeo_id(stem)
    if numeric:
        if numeric in catalog:
            return catalog[numeric]
        return CatalogEntry(
            vimeo_id=numeric,
            title=f"Vimeo {numeric}",
            watch_url=vimeo_watch_url(numeric),
        )
    key = sermon_date_key(name) or sermon_date_key(stem)
    if not key:
        return None
    candidates = date_index.get(key) or []
    if not candidates:
        return None
    return _pick_catalog_video(candidates)


def _documents_by_vimeo_id() -> dict[str, IngestedDocument]:
    found: dict[str, IngestedDocument] = {}
    catalog, date_index = _load_catalog()
    for document in IngestedDocument.objects.filter(source_kind="video"):
        entry = match_source_to_catalog(document.source_name, catalog, date_index)
        if not entry:
            entry = match_source_to_catalog(document.title, catalog, date_index)
        if not entry or entry.vimeo_id in found:
            continue
        found[entry.vimeo_id] = document
    return found


def _collect_matches(upload_dir: Path) -> dict[str, _MatchState]:
    catalog, date_index = _load_catalog()
    matches: dict[str, _MatchState] = {}

    def ensure(entry: CatalogEntry) -> _MatchState:
        current = matches.get(entry.vimeo_id)
        if current is None:
            current = _MatchState(entry=entry)
            matches[entry.vimeo_id] = current
        elif entry.featured and not current.entry.featured:
            current.entry = entry
        return current

    for entry in catalog.values():
        if entry.featured:
            ensure(entry)

    for document in IngestedDocument.objects.filter(source_kind="video"):
        entry = match_source_to_catalog(document.source_name, catalog, date_index)
        if not entry:
            entry = match_source_to_catalog(document.title, catalog, date_index)
        if not entry:
            continue
        state = ensure(entry)
        if state.document is None:
            state.document = document

    if upload_dir.is_dir():
        for path in upload_dir.iterdir():
            if not path.is_file():
                continue
            if path.name.endswith(".transcript.json"):
                entry = match_source_to_catalog(path.name, catalog, date_index)
                if not entry:
                    continue
                state = ensure(entry)
                if state.sidecar_path is None:
                    state.sidecar_path = path
                continue
            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            entry = match_source_to_catalog(path.name, catalog, date_index)
            if not entry:
                continue
            state = ensure(entry)
            if state.media_path is None:
                state.media_path = path

    for state in matches.values():
        if state.media_path is None:
            state.media_path = find_media_for_vimeo_id(
                state.entry.vimeo_id,
                upload_dir,
                catalog_title=state.entry.title,
            )
        if state.sidecar_path is None:
            state.sidecar_path = find_sidecar_for_vimeo_id(
                state.entry.vimeo_id,
                upload_dir,
                state.media_path,
                catalog_title=state.entry.title,
            )
    return matches


def _build_embedded_video(
    vimeo_id: str,
    *,
    upload_dir: Path,
    documents: dict[str, IngestedDocument],
    featured: bool = False,
    include_segments: bool = False,
    media_path: Optional[Path] = None,
    sidecar_path: Optional[Path] = None,
    catalog_entry: Optional[CatalogEntry] = None,
) -> EmbeddedVideo:
    entry = catalog_entry
    if media_path is None:
        media_path = find_media_for_vimeo_id(
            vimeo_id,
            upload_dir,
            catalog_title=entry.title if entry else "",
        )
    if sidecar_path is None:
        sidecar_path = find_sidecar_for_vimeo_id(
            vimeo_id,
            upload_dir,
            media_path,
            catalog_title=entry.title if entry else "",
        )
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
    if document is None:
        document = documents.get(vimeo_id)
    sidecar_title = str(payload.get("title") or "").strip() if payload else ""
    document_title = (document.title or "").strip() if document else ""
    fallback_title = _featured_fallback_titles().get(vimeo_id, f"Vimeo {vimeo_id}")
    catalog_title = (entry.title if entry else "").strip()
    rejected_titles = set(lookup_stems_for_vimeo_id(vimeo_id))
    rejected_titles.add(vimeo_id)
    if featured:
        title_candidates = (
            document_title,
            sidecar_title,
            fallback_title,
            catalog_title,
        )
    else:
        title_candidates = (
            catalog_title if catalog_title and not is_copy_title(catalog_title) else "",
            document_title,
            sidecar_title,
            catalog_title,
            fallback_title,
        )
    title = next(
        (
            candidate
            for candidate in title_candidates
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
    privacy_hash = (entry.privacy_hash if entry else "") or ""
    watch_url = (
        (entry.watch_url if entry and entry.watch_url else "")
        or vimeo_watch_url(vimeo_id, privacy_hash=privacy_hash)
    )
    matched_by_date = bool(
        source_name and sermon_date_key(source_name) and not parse_vimeo_id_from_filename(source_name)
    )
    video = EmbeddedVideo(
        vimeo_id=vimeo_id,
        watch_url=watch_url,
        embed_url=vimeo_embed_url(vimeo_id, privacy_hash),
        title=title,
        source_name=source_name,
        media_name=media_path.name if media_path else None,
        has_media=media_path is not None,
        has_transcript=has_transcript,
        transcript_segment_count=len(segments),
        featured=featured,
        matched_by_date=matched_by_date,
        document_title=document_title or None,
        sidecar_title=sidecar_title or None,
        whisper_model=str(payload.get("whisper_model") or "") or None if payload else None,
        transcript_source=sidecar_path.name if sidecar_path and has_transcript else None,
        segments=segments,
    )
    return video


def list_embedded_videos(upload_dir: Optional[Path] = None) -> list[EmbeddedVideo]:
    root = (upload_dir or admin_video_ingestion_dir()).resolve()
    matches = _collect_matches(root)
    documents = {vimeo_id: state.document for vimeo_id, state in matches.items() if state.document}
    # Keep numeric-stem lookups used by featured mapped transcripts.
    documents.update(_documents_by_vimeo_id())
    videos = [
        _build_embedded_video(
            state.entry.vimeo_id,
            upload_dir=root,
            documents=documents,
            featured=state.entry.featured,
            media_path=state.media_path,
            sidecar_path=state.sidecar_path,
            catalog_entry=state.entry,
        )
        for state in matches.values()
        if state.entry.featured or state.document or state.media_path or state.sidecar_path
    ]
    videos.sort(
        key=lambda item: (
            not item.featured,
            sermon_date_key(item.title) or "99-99",
            item.title.lower(),
            item.vimeo_id,
        ),
    )
    return videos


def get_embedded_video(vimeo_id: str, upload_dir: Optional[Path] = None) -> Optional[EmbeddedVideo]:
    parsed = parse_vimeo_id(vimeo_id)
    if not parsed:
        return None
    root = (upload_dir or admin_video_ingestion_dir()).resolve()
    matches = _collect_matches(root)
    state = matches.get(parsed)
    featured_ids = {item["vimeo_id"] for item in FEATURED_VIMEO_VIDEOS if item.get("vimeo_id")}
    documents = {key: value.document for key, value in matches.items() if value.document}
    documents.update(_documents_by_vimeo_id())
    if state is None:
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
            media_path=media_path,
            sidecar_path=sidecar_path,
        )
    if (
        not state.entry.featured
        and state.document is None
        and state.media_path is None
        and state.sidecar_path is None
    ):
        return None
    return _build_embedded_video(
        parsed,
        upload_dir=root,
        documents=documents,
        featured=state.entry.featured,
        include_segments=True,
        media_path=state.media_path,
        sidecar_path=state.sidecar_path,
        catalog_entry=state.entry,
    )
