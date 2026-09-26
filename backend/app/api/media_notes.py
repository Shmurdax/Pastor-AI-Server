"""Attach ingested study notes to Walk through the Word MediaVideo rows.

Matching is conservative: a notes PDF is linked when its title/filename is
date-led (``January 4``, ``Copy of April 10 Teaching Notes``), names the
Vimeo id, or clearly labels Walk through the Word notes. Topical sermons
without a leading date are left for staff to attach in admin.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from core.embedded_videos import COPY_OF_RE, SERMON_DATE_RE, parse_vimeo_id, sermon_date_key
from core.models import IngestedDocument

from .models import MediaVideo

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_NOTE_HINTS = (
    "walk through the word",
    "walkthrough the word",
    "walk thru the word",
    "wttw",
    "teaching notes",
    "sermon notes",
    "study notes",
    "pastor notes",
    "pastors notes",
    "pastor's notes",
    "full notes",
    "speaker notes",
    "handout",
    "outline",
)
_STRIP_PHRASES = (
    "teaching notes",
    "sermon notes",
    "study notes",
    "pastor notes",
    "pastors notes",
    "pastor's notes",
    "full notes",
    "speaker notes",
    "walk through the word",
    "walkthrough the word",
    "walk thru the word",
    "the nordins",
    "the nordin's",
    "nordin's",
    "nordins",
    "handout",
    "outline",
    "notes",
)
_MIN_AUTO_SCORE = 70


def _clean_title(value: str) -> str:
    text = COPY_OF_RE.sub("", value or "").strip()
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;")


def _title_year(value: str) -> Optional[int]:
    match = _YEAR_RE.search(value or "")
    return int(match.group(1)) if match else None


def _strip_note_phrases(value: str) -> str:
    text = f" {(value or '').lower()} "
    for phrase in sorted(_STRIP_PHRASES, key=len, reverse=True):
        text = text.replace(f" {phrase} ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _starts_with_date(value: str) -> bool:
    cleaned = _clean_title(value)
    return bool(SERMON_DATE_RE.match(cleaned))


def _vimeo_id_from_name(value: str) -> Optional[str]:
    stem = Path(value or "").stem
    parsed = parse_vimeo_id(stem)
    if parsed:
        return parsed
    match = re.search(r"\b(\d{6,12})\b", value or "")
    if not match:
        return None
    return parse_vimeo_id(match.group(1))


def notes_match_score(
    document_title: str,
    source_name: str = "",
    video_title: str = "",
) -> int:
    """Return 0–100. Scores below ``_MIN_AUTO_SCORE`` must not auto-attach."""
    title = _clean_title(document_title or "")
    source = _clean_title(Path(source_name or "").stem)
    haystacks = [item for item in (title, source) if item]
    if not haystacks:
        return 0

    video_clean = _clean_title(video_title or "")
    if video_clean:
        for item in haystacks:
            if item.lower() == video_clean.lower():
                return 95

    blob = " ".join(haystacks).lower()
    has_hint = any(hint in blob for hint in _NOTE_HINTS)
    date_key = next((sermon_date_key(item) for item in haystacks if sermon_date_key(item)), None)
    starts_with_date = any(_starts_with_date(item) for item in haystacks)

    remainder = _strip_note_phrases(SERMON_DATE_RE.sub(" ", _YEAR_RE.sub(" ", title or source)))
    remainder = re.sub(r"[^a-z0-9\s]", " ", remainder.lower())
    remainder = re.sub(r"\s+", " ", remainder).strip()

    if date_key and not remainder:
        return 90
    if date_key and starts_with_date:
        return 85
    if date_key and has_hint:
        return 80
    if has_hint and not remainder:
        return 60
    return 0


def _candidate_documents() -> list[IngestedDocument]:
    return list(
        IngestedDocument.objects.filter(source_kind="document").order_by("id")
    )


def _videos_for_date_key(key: str, year: Optional[int]) -> list[MediaVideo]:
    matched: list[MediaVideo] = []
    for video in MediaVideo.objects.filter(is_published=True):
        if sermon_date_key(video.title or "") != key:
            continue
        if year is not None and video.published_at is not None:
            if video.published_at.year != year:
                continue
        matched.append(video)
    return matched


def attach_notes_to_media_videos() -> dict[str, int]:
    """Link date-led / Vimeo-id notes PDFs onto published MediaVideo rows."""
    documents = _candidate_documents()
    videos_by_id = {
        str(video.vimeo_id): video
        for video in MediaVideo.objects.filter(is_published=True)
    }
    best: dict[int, tuple[int, IngestedDocument]] = {}

    for document in documents:
        vimeo_id = _vimeo_id_from_name(document.source_name) or _vimeo_id_from_name(
            document.title or ""
        )
        if vimeo_id and vimeo_id in videos_by_id:
            video = videos_by_id[vimeo_id]
            score = max(notes_match_score(document.title, document.source_name, video.title), 100)
            current = best.get(video.id)
            if current is None or score > current[0]:
                best[video.id] = (score, document)
            continue

        date_key = sermon_date_key(document.title or "") or sermon_date_key(
            document.source_name or ""
        )
        if not date_key:
            continue
        year = _title_year(document.title or "") or _title_year(document.source_name or "")
        for video in _videos_for_date_key(date_key, year):
            score = notes_match_score(document.title, document.source_name, video.title)
            if score < _MIN_AUTO_SCORE:
                continue
            current = best.get(video.id)
            if current is None or score > current[0]:
                best[video.id] = (score, document)

    attached = updated = skipped_manual = 0
    for video in MediaVideo.objects.filter(is_published=True):
        choice = best.get(video.id)
        if choice is None:
            continue
        _score, document = choice
        if video.notes_document_id == document.id:
            continue
        if video.notes_document_manual:
            skipped_manual += 1
            continue
        was_empty = video.notes_document_id is None
        video.notes_document = document
        video.save(update_fields=["notes_document", "updated_at"])
        if was_empty:
            attached += 1
        else:
            updated += 1
        logger.info(
            "Attached notes %s to Walk through the Word video %s (%s)",
            document.source_name,
            video.vimeo_id,
            video.title,
        )

    return {
        "considered": len(documents),
        "attached": attached,
        "updated": updated,
        "skipped_manual": skipped_manual,
        "matched_videos": len(best),
    }
