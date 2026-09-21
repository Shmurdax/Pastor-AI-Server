"""Match library sermon titles for simple prompts, then fetch those files by hash.

Embedding ``faith`` ranks generic pastoral chunks. Titles such as
``Faith That Moves Mountains`` name the topic; Qdrant ``file_hash`` lookup
pulls those windows even when ANN missed them. Related notes from other
files still come from body search (dual-lane), not this catalog.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9']+")
_CACHE_TTL_S = 60.0
_CATALOG_CACHE: tuple[float, tuple["CatalogEntry", ...]] | None = None

# Template / outline words that must not pick discussion-guide PDFs.
_CATALOG_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "about",
        "based",
        "can",
        "give",
        "me",
        "my",
        "on",
        "the",
        "for",
        "from",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "does",
        "do",
        "did",
        "is",
        "are",
        "pastor",
        "don",
        "susan",
        "nordin",
        "teach",
        "teaches",
        "teaching",
        "preach",
        "sermon",
        "sermons",
        "point",
        "points",
        "outline",
        "topic",
        "topics",
        "generate",
        "write",
        "please",
        "three",
        "four",
        "five",
    }
)

# Title aliases so "gratitude" still hits a Thanksgiving sermon.
TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "faith": ("faith",),
    "gratitude": ("gratitude", "grateful", "thanksgiving", "thankfulness"),
    "thankful": ("gratitude", "grateful", "thanksgiving", "thankfulness"),
    "thanksgiving": ("gratitude", "grateful", "thanksgiving", "thankfulness"),
    "prayer": ("prayer", "pray", "praying"),
    "tithing": ("tithe", "tithing", "tithes"),
    "tithe": ("tithe", "tithing", "tithes"),
    "patience": ("patience", "patient"),
    "hope": ("hope",),
    "marriage": ("marriage", "covenant"),
    "alcohol": ("alcohol", "wine", "sippin"),
    "homosexuality": ("homosexuality", "homosexual", "gay"),
    "gay": ("homosexuality", "homosexual", "gay"),
}

_BIBLE_TITLE_MARKERS = (
    "bible",
    "nkjv",
    "king james",
    "new testament",
    "old testament",
    "scripture",
)


@dataclass(frozen=True)
class CatalogEntry:
    title: str
    file_hash: str
    source_name: str = ""
    topic_title: str = ""
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogHit:
    title: str
    file_hash: str
    source_name: str
    score: float


def _title_words(text: str) -> list[str]:
    cleaned = (text or "").lower().replace("&", " ")
    cleaned = re.sub(r"[_\-./]+", " ", cleaned)
    return [
        word
        for word in _WORD_RE.findall(cleaned)
        if len(word) >= 3 and not word.isdigit()
    ]


def catalog_tokens(query: str) -> set[str]:
    """Content tokens plus title aliases for catalog matching."""
    words = {word for word in _title_words(query) if word not in _CATALOG_STOP}
    expanded: set[str] = set()
    for word in words:
        expanded.add(word)
        expanded.update(TOPIC_ALIASES.get(word, ()))
    for key, aliases in TOPIC_ALIASES.items():
        if key in words or (words & set(aliases)):
            expanded.add(key)
            expanded.update(aliases)
    return {token for token in expanded if token and token not in _CATALOG_STOP}


def _looks_like_bible_entry(entry: CatalogEntry) -> bool:
    hay = f"{entry.title} {entry.source_name} {entry.topic_title}".lower()
    return any(marker in hay for marker in _BIBLE_TITLE_MARKERS)


def score_catalog_title(entry: CatalogEntry, tokens: Iterable[str]) -> float:
    """Higher when the display title names the query word as a subject."""
    wanted = {str(token).lower() for token in tokens if str(token).strip()}
    if not wanted:
        return 0.0
    words = _title_words(entry.title) or _title_words(entry.topic_title)
    if not words:
        return 0.0
    hits = sum(1 for word in words if word in wanted)
    if hits <= 0:
        return 0.0
    score = float(hits) * 2.0
    score += hits / max(len(words), 1)
    if words[0] in wanted:
        score += 2.5
    # One weak hit in a long unrelated title is not a "major sermon".
    if hits == 1 and len(words) > 8:
        score *= 0.4
    keyword_blob = " ".join(str(item).lower() for item in entry.keywords)
    if keyword_blob and any(token in keyword_blob.split() for token in wanted):
        score += 0.25
    return score


def match_catalog_entries(
    entries: Sequence[CatalogEntry] | None,
    query: str,
    *,
    limit: int = 3,
) -> list[CatalogHit]:
    """Return the best title matches for a simple or topical prompt."""
    tokens = catalog_tokens(query)
    if not tokens or not entries:
        return []
    ranked: list[CatalogHit] = []
    for entry in entries:
        if not (entry.file_hash or "").strip():
            continue
        if _looks_like_bible_entry(entry):
            continue
        score = score_catalog_title(entry, tokens)
        if score <= 0:
            continue
        ranked.append(
            CatalogHit(
                title=(entry.title or entry.topic_title or entry.source_name).strip(),
                file_hash=entry.file_hash.strip(),
                source_name=entry.source_name,
                score=score,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.title.lower()))
    seen: set[str] = set()
    unique: list[CatalogHit] = []
    for hit in ranked:
        key = hit.file_hash.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
        if len(unique) >= max(1, limit):
            break
    return unique


def catalog_title_queries(hits: Iterable[CatalogHit] | None) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for hit in hits or []:
        title = " ".join((hit.title or "").split())
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(title)
        queries.append(f"Pastor Don Nordin {title}")
    return queries


def load_catalog_entries() -> tuple[CatalogEntry, ...]:
    """Library titles from Postgres. Safe to call from chat; cached briefly."""
    global _CATALOG_CACHE
    now = time.monotonic()
    if _CATALOG_CACHE is not None and (now - _CATALOG_CACHE[0]) < _CACHE_TTL_S:
        return _CATALOG_CACHE[1]
    try:
        from .models import IngestedDocument
    except Exception:
        logger.debug("Catalog load skipped; Django models unavailable", exc_info=True)
        return ()
    rows: list[CatalogEntry] = []
    try:
        documents = IngestedDocument.objects.all().only(
            "title",
            "file_hash",
            "source_name",
            "topic_metadata",
        )
        for document in documents:
            meta = document.topic_metadata or {}
            keywords = meta.get("keywords") or ()
            if not isinstance(keywords, (list, tuple)):
                keywords = ()
            rows.append(
                CatalogEntry(
                    title=str(document.title or "").strip(),
                    file_hash=str(document.file_hash or "").strip(),
                    source_name=str(document.source_name or "").strip(),
                    topic_title=str(meta.get("topic_title") or "").strip(),
                    keywords=tuple(str(item).strip() for item in keywords if str(item).strip()),
                )
            )
    except Exception:
        logger.exception("Failed loading sermon catalog from IngestedDocument")
        return ()
    cached = tuple(rows)
    _CATALOG_CACHE = (now, cached)
    return cached


def match_library_catalog(query: str, *, limit: int = 3) -> list[CatalogHit]:
    return match_catalog_entries(load_catalog_entries(), query, limit=limit)


def _payload_of(point: Any) -> dict:
    payload = getattr(point, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _point_to_doc(point: Any) -> Optional[Any]:
    payload = _payload_of(point)
    if not payload:
        return None
    metadata = dict(payload.get("metadata") or {})
    for key, value in payload.items():
        if key == "metadata":
            continue
        metadata.setdefault(key, value)
    text = str(payload.get("text") or metadata.get("text") or "").strip()
    if not text:
        return None
    return SimpleNamespace(page_content=text, metadata=metadata)


def lookup_chunks_by_file_hashes(
    client: Any,
    collection_name: str,
    file_hashes: Iterable[str],
    *,
    limit_per_file: int = 8,
) -> list[Any]:
    """Fetch note windows for catalog-matched PDFs via the file_hash payload index."""
    if client is None:
        return []
    hashes = []
    seen: set[str] = set()
    for raw in file_hashes or []:
        value = str(raw or "").strip()
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        hashes.append(value)
    if not hashes:
        return []

    from qdrant_client.http import models as qdrant_models

    found: list[Any] = []
    seen_text: set[str] = set()
    for file_hash in hashes[:6]:
        try:
            points, _offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="file_hash",
                            match=qdrant_models.MatchValue(value=file_hash),
                        ),
                    ]
                ),
                limit=max(4, limit_per_file),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            logger.debug("Catalog file_hash lookup failed for %s", file_hash[:12], exc_info=True)
            points = []
        matched = 0
        for point in points or []:
            doc = _point_to_doc(point)
            if doc is None:
                continue
            key = " ".join((doc.page_content or "").split()).lower()[:240]
            if not key or key in seen_text:
                continue
            kind = str((doc.metadata or {}).get("chunk_kind") or "").lower()
            if kind == "bible_verse":
                continue
            seen_text.add(key)
            found.append(doc)
            matched += 1
            if matched >= limit_per_file:
                break
    return found
