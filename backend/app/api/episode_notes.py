"""Import dated study-note PDFs and attach them to Walk through the Word videos.

The PDFs stay in their own directory and in ``EpisodeNote`` rows. This module
does not create ``IngestedDocument`` rows, chunks, or Qdrant points.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from django.db import DataError, connection, transaction
from django.utils import timezone

from core.embedded_videos import parse_episode_date, sermon_date_key
from core.storage_paths import episode_notes_dir

from .models import EpisodeNote, MediaVideo

logger = logging.getLogger(__name__)

_PAGE_MARKER_RE = re.compile(r"(?i)^--\s*\d+\s+of\s+\d+\s*--$")
_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{2,})")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']{3,}")
_DAY_HEADING_RE = re.compile(r"(?i)\bday\s+\d+\b")

# Series boilerplate and function words. Kept out of topic chips so a search
# for "Sheba" or a hashtag is not crowded out by the header on every PDF.
_TOPIC_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "did",
        "for",
        "from",
        "had",
        "has",
        "have",
        "her",
        "him",
        "his",
        "how",
        "into",
        "its",
        "not",
        "our",
        "she",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "was",
        "were",
        "what",
        "when",
        "with",
        "you",
        "your",
        "about",
        "after",
        "also",
        "because",
        "been",
        "before",
        "being",
        "bible",
        "books",
        "children",
        "chronological",
        "daily",
        "developed",
        "don",
        "gmnonline",
        "lagard",
        "lord",
        "need",
        "needs",
        "note",
        "notes",
        "nordin",
        "ordered",
        "other",
        "pages",
        "penned",
        "reading",
        "resource",
        "resources",
        "smith",
        "studied",
        "susan",
        "these",
        "through",
        "today",
        "tools",
        "visit",
        "walk",
        "word",
        "would",
        "your",
    }
)

_BOILERPLATE_HASHTAGS = frozenset({"walkthroughtheword"})


def reflow_note_text(raw: str) -> str:
    """Unwrap PDF line breaks into paragraphs, bullets, and hashtag lines."""
    blocks: list[str] = []
    current: list[str] = []
    bullet = False

    def flush() -> None:
        nonlocal bullet
        if not current:
            bullet = False
            return
        text = re.sub(r"\s+", " ", " ".join(current)).strip()
        current.clear()
        if not text:
            bullet = False
            return
        if bullet:
            text = text.lstrip("•-* ").strip()
            if text:
                blocks.append(f"• {text}")
        else:
            blocks.append(text)
        bullet = False

    for line in (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or _PAGE_MARKER_RE.match(stripped):
            flush()
            continue
        if stripped in {"•", "-", "*"}:
            flush()
            bullet = True
            continue
        if stripped.startswith("•"):
            flush()
            bullet = True
            current.append(stripped.lstrip("•").strip())
            continue
        if stripped.startswith("#") and " " not in stripped:
            flush()
            blocks.append(stripped)
            continue
        current.append(stripped)
    flush()
    return "\n\n".join(blocks)


def extract_note_topics(text: str, *, limit: int = 12) -> list[str]:
    """Hashtags first, then repeated keywords from the day's study body."""
    topics: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        cleaned = label.strip().lstrip("#")
        key = cleaned.lower()
        if not cleaned or key in seen or key in _BOILERPLATE_HASHTAGS:
            return
        seen.add(key)
        topics.append(cleaned)

    for match in _HASHTAG_RE.finditer(text or ""):
        add(match.group(1))
        if len(topics) >= limit:
            return topics

    body = text or ""
    day = _DAY_HEADING_RE.search(body)
    if day:
        body = body[day.start() :]
    counts: dict[str, int] = {}
    for match in _WORD_RE.finditer(body):
        word = match.group(0).lower().strip("'")
        if len(word) < 4 or word in _TOPIC_STOPWORDS or word in seen:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    for word, count in ranked:
        if count < 2 and len(topics) >= 6:
            break
        add(word)
        if len(topics) >= limit:
            break
    return topics


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def match_video_for_episode_date(episode_date: date) -> Optional[MediaVideo]:
    """Published video whose title has this month and day and whose year matches."""
    month_day = f"{episode_date.month:02d}-{episode_date.day:02d}"
    candidates: list[MediaVideo] = []
    for video in MediaVideo.objects.filter(is_published=True).order_by("id"):
        if sermon_date_key(video.title) != month_day:
            continue
        if _published_year(video) != episode_date.year:
            continue
        candidates.append(video)
    if not candidates:
        return None

    def sort_key(video: MediaVideo) -> tuple[int, int]:
        published = video.published_at
        if timezone.is_aware(published):
            published = timezone.localtime(published)
        delta = abs((published.date() - episode_date).days)
        return (delta, video.pk)

    candidates.sort(key=sort_key)
    return candidates[0]


def import_episode_notes(directory: Path) -> dict:
    """Read PDFs from ``directory`` and upsert ``EpisodeNote`` rows.

    Files are copied under the episode-notes directory, never the sermon
    ingestion folder. Undated filenames are skipped.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Notes folder does not exist: {root}")

    created = 0
    updated = 0
    unlinked: list[str] = []
    undated: list[str] = []
    for path in sorted(item for item in root.iterdir() if item.is_file()):
        if path.suffix.lower() != ".pdf" or path.name.startswith("."):
            continue
        episode_date = parse_episode_date(path.name)
        if episode_date is None:
            undated.append(path.name)
            continue
        outcome = _upsert_note_file(path, episode_date)
        if outcome == "created":
            created += 1
        else:
            updated += 1
        note = EpisodeNote.objects.get(episode_date=episode_date)
        if note.media_video_id is None:
            unlinked.append(path.name)

    from core.persist_db import dump_persistent_postgres

    dump_persistent_postgres()
    return {
        "created": created,
        "updated": updated,
        "unlinked": unlinked,
        "undated": undated,
    }


def _upsert_note_file(path: Path, episode_date: date) -> str:
    data = path.read_bytes()
    content_hash = hashlib.sha256(data).hexdigest()
    raw_text = extract_pdf_text(path)
    search_text = reflow_note_text(raw_text)
    topics = extract_note_topics(search_text or raw_text)
    stored_filename = f"{episode_date.isoformat()}.pdf"
    dest = _note_path(stored_filename)
    dest.write_bytes(data)

    video = match_video_for_episode_date(episode_date)
    with transaction.atomic():
        note = EpisodeNote.objects.filter(episode_date=episode_date).first()
        created = note is None
        if note is None:
            note = EpisodeNote(episode_date=episode_date)
        if video is not None:
            others = EpisodeNote.objects.filter(media_video=video)
            if note.pk:
                others = others.exclude(pk=note.pk)
            others.update(media_video=None)
        note.media_video = video
        note.original_filename = path.name[:255]
        note.stored_filename = stored_filename
        note.search_text = search_text
        note.topics = topics
        note.content_hash = content_hash
        note.save()
    return "created" if created else "updated"


def note_file_path(note: EpisodeNote) -> Path:
    return _note_path(note.stored_filename)


def _note_path(stored_filename: str) -> Path:
    root = episode_notes_dir()
    path = (root / Path(stored_filename).name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Episode note path escapes the notes directory.")
    return path


def _published_year(video: MediaVideo) -> int:
    published = video.published_at
    if timezone.is_aware(published):
        published = timezone.localtime(published)
    return published.year


def topic_label(value: str) -> str:
    return (value or "").strip().lstrip("#")


def note_has_topic(note: EpisodeNote, topic: str) -> bool:
    wanted = topic_label(topic).lower()
    if not wanted:
        return False
    for item in note.topics or []:
        if topic_label(str(item)).lower() == wanted:
            return True
    return False


def full_text_note_ids(query: str) -> set[int]:
    """Postgres full-text hits. Empty on other databases and on bad queries."""
    cleaned = (query or "").strip()
    if not cleaned or connection.vendor != "postgresql":
        return set()
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

    try:
        vector = SearchVector("search_text", config="english")
        search = SearchQuery(cleaned, config="english", search_type="websearch")
        return set(
            EpisodeNote.objects.annotate(_rank=SearchRank(vector, search))
            .filter(_rank__gt=0)
            .values_list("pk", flat=True)
        )
    except (ValueError, DataError):
        logger.warning("Episode note full-text query failed for %r", cleaned, exc_info=True)
        return set()


def note_matches_query(note: EpisodeNote, query: str, *, fts_ids: Optional[set[int]] = None) -> bool:
    cleaned = (query or "").strip()
    if not cleaned:
        return False
    if fts_ids and note.pk in fts_ids:
        return True
    needle = cleaned.lower()
    if needle in (note.search_text or "").lower():
        return True
    for item in note.topics or []:
        if needle in topic_label(str(item)).lower():
            return True
    return False


def video_matches_query(video: MediaVideo, query: str) -> bool:
    needle = (query or "").strip().lower()
    if not needle:
        return False
    return needle in (video.title or "").lower() or needle in (video.description or "").lower()


def make_snippet(text: str, query: str, *, radius: int = 80) -> str:
    body = re.sub(r"\s+", " ", (text or "")).strip()
    if not body:
        return ""
    needle = (query or "").strip()
    if not needle:
        return body[: radius * 2].strip()
    index = body.lower().find(needle.lower())
    if index < 0:
        return body[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(body), index + len(needle) + radius)
    piece = body[start:end].strip()
    if start > 0:
        piece = f"…{piece}"
    if end < len(body):
        piece = f"{piece}…"
    return piece


def list_media_topics(*, limit: int = 40) -> list[str]:
    """Topics for filter chips. Hashtags stay ahead of everyday keywords."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    notes = EpisodeNote.objects.filter(media_video__is_published=True)
    for note in notes:
        for item in note.topics or []:
            label = topic_label(str(item))
            key = label.lower()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, label)
    ranked = sorted(counts, key=lambda key: (-counts[key], key))
    hashtags = [display[key] for key in ranked if any(char.isupper() for char in display[key])]
    keywords = [display[key] for key in ranked if not any(char.isupper() for char in display[key])]
    return (hashtags + keywords)[:limit]


def search_published_media(*, query: str = "", topic: str = "") -> list[dict]:
    """Published videos, optionally filtered by keyword and one topic."""
    query = (query or "").strip()
    topic = topic_label(topic)
    videos = list(MediaVideo.objects.filter(is_published=True).order_by("-published_at", "title"))
    notes_by_video = {
        note.media_video_id: note
        for note in EpisodeNote.objects.exclude(media_video=None)
        if note.media_video_id is not None
    }
    fts_ids = full_text_note_ids(query) if query else set()
    results: list[dict] = []
    for video in videos:
        note = notes_by_video.get(video.id)
        if topic and (note is None or not note_has_topic(note, topic)):
            continue
        snippet = ""
        if query:
            note_hit = note is not None and note_matches_query(note, query, fts_ids=fts_ids)
            title_hit = video_matches_query(video, query)
            if not note_hit and not title_hit:
                continue
            if note_hit and note is not None:
                snippet = make_snippet(note.search_text, query)
            elif title_hit:
                snippet = make_snippet(video.description, query)
        results.append(
            {
                "video": video,
                "note": note_summary(note, snippet=snippet),
            }
        )
    return results


def note_summary(note: Optional[EpisodeNote], *, snippet: str = "") -> Optional[dict]:
    if note is None:
        return None
    payload = {
        "id": note.pk,
        "episode_date": note.episode_date.isoformat(),
        "topics": [str(item) for item in (note.topics or []) if str(item).strip()],
        "has_notes": True,
    }
    if snippet:
        payload["snippet"] = snippet
    return payload


def visible_note(note_id: int) -> Optional[EpisodeNote]:
    return (
        EpisodeNote.objects.select_related("media_video")
        .filter(pk=note_id, media_video__is_published=True)
        .first()
    )
