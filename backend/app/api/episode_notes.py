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

from core.embedded_videos import MONTH_NAMES, parse_episode_date, sermon_date_key
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


def _text_for_database(value: str) -> str:
    """Return text Postgres can store as UTF-8.

    PDF extractors sometimes leave UTF-16 surrogate code points in the
    string. A real pair is an emoji split into two characters and is joined
    back together. A lone surrogate cannot be encoded, so it is replaced.
    """
    if not value:
        return ""
    encoded = value.encode("utf-16", "surrogatepass")
    try:
        value = encoded.decode("utf-16")
    except UnicodeDecodeError:
        value = encoded.decode("utf-16", "replace")
    return value.encode("utf-8", "replace").decode("utf-8")


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [_text_for_database(page.extract_text() or "") for page in reader.pages]
    return _text_for_database("\n".join(pages))


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
    search_text = _text_for_database(reflow_note_text(raw_text))
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
        note.original_filename = _text_for_database(path.name)[:255]
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


_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")


def _title_word(word: str) -> str:
    if not word:
        return word
    return word[0].upper() + word[1:]


def _fallback_topic_phrase(topic: str) -> str:
    """Split CamelCase when the note never writes the phrase out."""
    label = topic_label(topic)
    if not label:
        return ""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return " ".join(_title_word(word) for word in spaced.split())


def topic_phrase(topic: str, text: str) -> str:
    """Read a stored topic back from the note in the words the note uses.

    ``wontHedoIt`` becomes ``Wont He Do It`` when the note says
    ``Wont He do it``. A single smashed token stays a CamelCase fallback.
    """
    target = _compact_label(topic_label(topic))
    fallback = _fallback_topic_phrase(topic)
    if not target or not text:
        return fallback
    words = _WORD_TOKEN_RE.findall(text)
    compacts = [_compact_label(word) for word in words]
    best: Optional[tuple[int, int]] = None
    for start, _word in enumerate(words):
        acc = ""
        for end in range(start, len(words)):
            piece = compacts[end]
            if not piece:
                break
            acc += piece
            if len(acc) > len(target) or not target.startswith(acc):
                break
            if acc == target:
                if best is None or (end - start) > (best[1] - best[0]):
                    best = (start, end)
                break
    if best is None or best[1] == best[0]:
        return fallback
    return " ".join(_title_word(word) for word in words[best[0] : best[1] + 1])


def display_topics(note: EpisodeNote) -> list[str]:
    text = note.search_text or ""
    labels: list[str] = []
    seen: set[str] = set()
    for item in note.topics or []:
        phrase = topic_phrase(str(item), text)
        key = _compact_label(phrase)
        if not phrase or key in seen:
            continue
        seen.add(key)
        labels.append(phrase)
    return labels


def note_has_topic(note: EpisodeNote, topic: str) -> bool:
    wanted = _compact_label(topic)
    if not wanted:
        return False
    for item in note.topics or []:
        if _compact_label(str(item)) == wanted:
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


def _compact_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _query_months(query: str) -> set[int]:
    """Months named by the whole search, such as ``January`` or ``March 10``.

    A longer phrase that merely contains a month word is left as a keyword.
    """
    words = re.findall(r"[A-Za-z]+", query or "")
    if not words:
        return set()
    months = {MONTH_NAMES[word.lower()] for word in words if word.lower() in MONTH_NAMES}
    other_words = [word for word in words if word.lower() not in MONTH_NAMES]
    if other_words or not months:
        return set()
    return months


def _published_month(video: MediaVideo) -> int:
    published = video.published_at
    if timezone.is_aware(published):
        published = timezone.localtime(published)
    return published.month


def _title_match_rank(video: MediaVideo, query: str, months: set[int]) -> Optional[int]:
    """0 when the title contains the search, 1 when the publish month matches."""
    needle = (query or "").strip().lower()
    if needle and needle in (video.title or "").lower():
        return 0
    if months and _published_month(video) in months:
        return 1
    return None


def _topic_match(note: Optional[EpisodeNote], query: str) -> bool:
    needle = (query or "").strip().lower()
    compact = _compact_label(needle)
    if note is None or not needle:
        return False
    for item in note.topics or []:
        label = topic_label(str(item))
        if not label:
            continue
        if needle in label.lower() or (compact and compact in _compact_label(label)):
            return True
    return False


def _keyword_match(
    video: MediaVideo,
    note: Optional[EpisodeNote],
    query: str,
    *,
    fts_ids: set[int],
) -> bool:
    needle = (query or "").strip().lower()
    if not needle:
        return False
    if needle in (video.description or "").lower():
        return True
    if note is None:
        return False
    if note.pk in fts_ids:
        return True
    return needle in (note.search_text or "").lower()


# Title, then the publish month, then a topic, then a keyword in the notes.
_TITLE_RANK = 0
_MONTH_RANK = 1
_TOPIC_RANK = 2
_KEYWORD_RANK = 3


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
    """Topics for filter chips, worded the way the notes write them."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    raw: dict[str, str] = {}
    phrase_words: dict[str, int] = {}
    notes = EpisodeNote.objects.filter(media_video__is_published=True)
    for note in notes:
        text = note.search_text or ""
        for item in note.topics or []:
            label = topic_label(str(item))
            key = _compact_label(label)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            raw.setdefault(key, label)
            phrase = topic_phrase(label, text)
            words = len(phrase.split())
            if key not in display or words > phrase_words[key]:
                display[key] = phrase
                phrase_words[key] = words
    ranked = sorted(counts, key=lambda key: (-counts[key], key))
    hashtags = [display[key] for key in ranked if any(char.isupper() for char in raw[key])]
    keywords = [display[key] for key in ranked if not any(char.isupper() for char in raw[key])]
    return (hashtags + keywords)[:limit]


def search_published_media(*, query: str = "", topic: str = "") -> list[dict]:
    """Published videos, optionally filtered by keyword and one topic.

    A search is ordered the way the box is labeled: title, then topic, then
    keyword. ``January`` also matches videos published in January, ahead of
    notes that only mention the word.
    """
    query = (query or "").strip()
    topic = topic_label(topic)
    videos = list(MediaVideo.objects.filter(is_published=True).order_by("-published_at", "title"))
    notes_by_video = {
        note.media_video_id: note
        for note in EpisodeNote.objects.exclude(media_video=None)
        if note.media_video_id is not None
    }
    fts_ids = full_text_note_ids(query) if query else set()
    months = _query_months(query)
    results: list[dict] = []
    for video in videos:
        note = notes_by_video.get(video.id)
        if topic and (note is None or not note_has_topic(note, topic)):
            continue
        snippet = ""
        rank = _TITLE_RANK
        if query:
            title_rank = _title_match_rank(video, query, months)
            topic_hit = _topic_match(note, query)
            keyword_hit = _keyword_match(video, note, query, fts_ids=fts_ids)
            if title_rank is None and not topic_hit and not keyword_hit:
                continue
            if title_rank is not None:
                rank = title_rank
            elif topic_hit:
                rank = _TOPIC_RANK
            else:
                rank = _KEYWORD_RANK
            if keyword_hit and note is not None:
                snippet = make_snippet(note.search_text, query)
            elif title_rank is not None:
                snippet = make_snippet(video.description or video.title, query)
        results.append(
            {
                "video": video,
                "note": note_summary(note, snippet=snippet),
                "match_rank": rank,
            }
        )
    results.sort(key=lambda item: (item["match_rank"],))
    return results


def note_summary(note: Optional[EpisodeNote], *, snippet: str = "") -> Optional[dict]:
    if note is None:
        return None
    payload = {
        "id": note.pk,
        "episode_date": note.episode_date.isoformat(),
        "topics": display_topics(note),
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
