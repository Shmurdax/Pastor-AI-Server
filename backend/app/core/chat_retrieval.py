"""Chat RAG retrieval: multi-query search, source diversity, and quote novelty.

Follow-up turns used to re-hit the same high-similarity sermon/Bible cluster, so
the model repeated one Pastor Don line and one verse. This module:

- expands a user question into a few search queries (raw, keywords, prior turn)
- merges Qdrant hits across those queries
- selects a source-diverse mix (sermon vs Bible) with MMR-style ranking
- down-ranks chunks that already appeared as quotes or verses in this chat
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_BIBLE_SOURCE_MARKERS = (
    "bible",
    "nkjv",
    "king james",
    "new testament",
    "old testament",
    "scripture",
)

_FOLLOWUP_RE = re.compile(
    r"\b("
    r"clarif(?:y|ied|ication)|further|expand(?:ing)?|elaborat(?:e|ion)|"
    r"what do you mean|go (?:deeper|further)|say more|more (?:about|detail|on)|"
    r"that (?:guidance|answer|point|teaching|quote)|in other words"
    r")\b",
    re.IGNORECASE,
)

_QUESTION_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "further",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "say",
        "should",
        "someone",
        "that",
        "the",
        "their",
        "them",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would",
        "you",
        "your",
    }
)

# Longest names first so "1 john" wins over "john", "song of solomon" over "song".
_BIBLE_BOOKS = tuple(
    sorted(
        (
            "song of solomon",
            "1 corinthians",
            "2 corinthians",
            "1 thessalonians",
            "2 thessalonians",
            "1 timothy",
            "2 timothy",
            "1 peter",
            "2 peter",
            "1 john",
            "2 john",
            "3 john",
            "1 samuel",
            "2 samuel",
            "1 kings",
            "2 kings",
            "1 chronicles",
            "2 chronicles",
            "genesis",
            "exodus",
            "leviticus",
            "numbers",
            "deuteronomy",
            "joshua",
            "judges",
            "ruth",
            "ezra",
            "nehemiah",
            "esther",
            "job",
            "psalm",
            "psalms",
            "proverbs",
            "ecclesiastes",
            "isaiah",
            "jeremiah",
            "lamentations",
            "ezekiel",
            "daniel",
            "hosea",
            "joel",
            "amos",
            "obadiah",
            "jonah",
            "micah",
            "nahum",
            "habakkuk",
            "zephaniah",
            "haggai",
            "zechariah",
            "malachi",
            "matthew",
            "mark",
            "luke",
            "john",
            "acts",
            "romans",
            "galatians",
            "ephesians",
            "philippians",
            "colossians",
            "titus",
            "philemon",
            "hebrews",
            "james",
            "jude",
            "revelation",
        ),
        key=len,
        reverse=True,
    )
)

_QUOTE_RE = re.compile(r"[\"“](.{12,400}?)[\"”]")
_VERSE_RE = re.compile(
    r"\b((?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z][A-Za-z]+)?)\s+(\d+):(\d+)"
    r"(?:\s*[-–]\s*\d+)?",
)
_TOKEN_RE = re.compile(r"[a-z0-9']{3,}")


def bible_source_markers() -> tuple[str, ...]:
    raw = os.environ.get("BIBLE_SOURCE_MARKERS", "")
    if not raw.strip():
        return DEFAULT_BIBLE_SOURCE_MARKERS
    parsed = tuple(marker.strip().lower() for marker in raw.split(",") if marker.strip())
    return parsed or DEFAULT_BIBLE_SOURCE_MARKERS


def is_bible_source(source_name: str, markers: Optional[Iterable[str]] = None) -> bool:
    normalized = (source_name or "").lower()
    used = tuple(markers) if markers is not None else bible_source_markers()
    return any(marker in normalized for marker in used)


_VIDEO_SOURCE_EXTS = (
    ".mp4",
    ".m4v",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".3gp",
    ".ogv",
    ".ts",
    ".mts",
    ".m2ts",
    ".m4a",
    ".mp3",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
)


def is_video_chunk(doc: Any) -> bool:
    """True for Whisper/video transcript chunks (not PDF sermon notes)."""
    metadata = getattr(doc, "metadata", None) or {}
    content_type = str(
        metadata.get("content_type") or metadata.get("media_type") or ""
    ).lower()
    chunk_kind = str(metadata.get("chunk_kind") or "").lower()
    if "video" in content_type or chunk_kind.startswith("video"):
        return True
    for key in ("source", "source_name", "file_name", "filename"):
        raw = str(metadata.get(key) or "").lower()
        if any(raw.endswith(ext) for ext in _VIDEO_SOURCE_EXTS):
            return True
    return False


def metadata_source_hint(doc: Any) -> str:
    metadata = getattr(doc, "metadata", None) or {}
    parts = [
        metadata.get("title"),
        metadata.get("source"),
        metadata.get("source_name"),
        metadata.get("file_name"),
        metadata.get("filename"),
        metadata.get("path"),
    ]
    return " ".join(str(part) for part in parts if part)


def chunk_source_key(doc: Any) -> str:
    metadata = getattr(doc, "metadata", None) or {}
    for key in ("file_hash", "source", "source_name", "title", "file_name", "filename"):
        value = metadata.get(key)
        if value:
            return str(value)
    return str(id(doc))


def chunk_text(doc: Any) -> str:
    return (getattr(doc, "page_content", None) or "").strip()


def chunk_fingerprint(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    return collapsed[:400]


def looks_like_followup(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    # Greetings are not follow-ups even when short / after prior turns.
    from .chat_system_prompt import looks_like_brief_social

    if looks_like_brief_social(text):
        return False
    if _FOLLOWUP_RE.search(text):
        return True
    return len(text.split()) <= 8


def keyword_search_query(text: str) -> str:
    terms = [
        token
        for token in re.findall(r"[A-Za-z']{3,}", text or "")
        if token.lower() not in _QUESTION_STOPWORDS
    ]
    return " ".join(terms).strip()


def query_focus_tokens(text: str) -> frozenset[str]:
    """Distinctive query words used for topical overlap (not generic pastoral vocabulary)."""
    return frozenset(
        token.lower()
        for token in keyword_search_query(text).split()
        if len(token) >= 4
    )


def source_stem_key(label: str) -> str:
    """Collapse timestamped clips of the same sermon into one source identity."""
    stem = re.sub(
        r"\s*\[[0-9:]{4,8}[–-][0-9:]{4,8}\]\s*$",
        "",
        (label or "").strip(),
    )
    stem = re.sub(r"\s*\([^)]*\)\s*$", "", stem).strip()
    return stem.lower()


def _metadata_search_blob(doc: Any) -> str:
    metadata = getattr(doc, "metadata", None) or {}
    parts: list[str] = [chunk_text(doc)]
    for key in ("topic_title", "title", "original_title", "summary"):
        value = metadata.get(key)
        if value:
            parts.append(str(value))
    for key in ("topics", "keywords", "scripture_refs"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def topic_overlap_score(doc: Any, query_tokens: Iterable[str]) -> float:
    tokens = [str(token).lower() for token in query_tokens if str(token).strip()]
    if not tokens:
        return 0.0
    hay = _metadata_search_blob(doc)
    if not hay:
        return 0.0
    hits = sum(1 for token in tokens if token in hay)
    return hits / len(tokens)


def filter_hits_by_topic(
    scored_hits: list[tuple[Any, float]],
    query: str,
    *,
    retrieval_k: int,
) -> list[tuple[Any, float]]:
    """Drop embedding-only matches that share no distinctive query words.

    Vector search is already ANN (not a slow scan). Extra *time* does not help;
    extra *candidates + lexical overlap* does. Keep the full list if too few
    chunks mention the question's own terms.
    """
    tokens = query_focus_tokens(query)
    if len(tokens) < 2 or not scored_hits:
        return scored_hits
    ranked = []
    for doc, score in scored_hits:
        overlap = topic_overlap_score(doc, tokens)
        ranked.append((doc, score, overlap))
    on_topic = [(doc, score) for doc, score, overlap in ranked if overlap > 0]
    min_keep = max(6, retrieval_k)
    if len(on_topic) >= min_keep:
        return on_topic
    # Prefer any overlap, then original rank.
    ranked.sort(key=lambda item: (item[2], item[1]), reverse=True)
    return [(doc, score) for doc, score, _overlap in ranked]


def expand_search_queries(
    current: str,
    prior_user_queries: Optional[Iterable[str]] = None,
    prior_ai_texts: Optional[Iterable[str]] = None,
    *,
    limit: int = 5,
) -> list[str]:
    """Build distinct Qdrant queries, anchoring follow-ups to prior turns."""
    queries: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = " ".join((value or "").split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            return
        seen.add(key)
        queries.append(cleaned)

    current_q = (current or "").strip()
    prior = [str(item).strip() for item in (prior_user_queries or []) if str(item).strip()]
    last_prior = ""
    for item in reversed(prior):
        if item.lower() != current_q.lower():
            last_prior = item
            break
    followup = bool(last_prior) and looks_like_followup(current_q)

    # For follow-ups, lead with topic-carrying rewrites so retrieval stays on
    # the prior pastoral question instead of a vague "clarify those steps".
    if followup and last_prior:
        add(f"{last_prior} {current_q}")
        prior_keywords = keyword_search_query(f"{last_prior} {current_q}")
        if prior_keywords:
            add(prior_keywords)
        last_ai = ""
        for item in reversed(list(prior_ai_texts or [])):
            text = str(item or "").strip()
            if text:
                last_ai = text
                break
        if last_ai:
            # Prefer headings / bold step labels from the prior answer.
            step_bits = re.findall(
                r"\*\*([^*]{3,60})\*\*|^(?:[-*]\s+)?([A-Z][A-Za-z' ]{2,40}):",
                last_ai,
                flags=re.MULTILINE,
            )
            step_text = " ".join(part for pair in step_bits for part in pair if part)
            ai_keywords = keyword_search_query((step_text + " " + last_ai[:900]).strip())
            if ai_keywords:
                add(f"{ai_keywords} {current_q}")
                add(f"{last_prior} {ai_keywords}")

    add(current_q)
    if last_prior and not followup:
        add(f"{last_prior} {current_q}")

    keywords = keyword_search_query(current_q)
    if keywords and keywords.lower() != current_q.lower():
        add(keywords)

    if last_prior and looks_like_followup(current_q):
        add(keyword_search_query(f"{last_prior} {current_q}"))

    if not last_prior and keywords:
        add(f"Pastor Don Nordin sermon {keywords}")

    return queries[: max(1, limit)]


def extract_used_quotes(texts: Iterable[str], *, limit: int = 10) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _QUOTE_RE.finditer(text or ""):
            quote = " ".join(match.group(1).split()).strip()
            key = quote.lower()
            if len(quote) < 12 or key in seen:
                continue
            # Skip short Scripture fragments that verse extraction covers.
            seen.add(key)
            found.append(quote)
            if len(found) >= limit:
                return found
    return found


def extract_used_verse_refs(texts: Iterable[str], *, limit: int = 12) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _VERSE_RE.finditer(text or ""):
            book = re.sub(r"\s+", " ", match.group(1)).strip()
            if book.lower() not in {b.lower() for b in _BIBLE_BOOKS}:
                continue
            ref = f"{book} {match.group(2)}:{match.group(3)}"
            key = ref.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(ref)
            if len(found) >= limit:
                return found
    return found


def bible_book_key(text: str) -> str:
    lowered = (text or "").lower()
    window = lowered[:800]
    for book in _BIBLE_BOOKS:
        if book in window:
            return f"bible:{book}"
    return "bible:unknown"


def _token_set(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall((text or "").lower()))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    if not union:
        return 0.0
    return len(left & right) / union


def _novelty_penalty(text: str, used_quotes: Iterable[str], used_verses: Iterable[str]) -> float:
    lowered = (text or "").lower()
    penalty = 0.0
    for quote in used_quotes:
        snippet = (quote or "").strip().lower()
        if len(snippet) >= 12 and snippet[:80] in lowered:
            penalty += 0.4
    for verse in used_verses:
        if verse and verse.lower() in lowered:
            penalty += 0.35
    return min(penalty, 0.9)


@dataclass
class ScoredChunk:
    doc: Any
    score: float
    source_key: str
    is_bible: bool
    fingerprint: str
    text: str
    tokens: frozenset[str] = field(default_factory=frozenset)
    book_key: str = ""
    novelty: float = 0.0
    is_video: bool = False
    topic_overlap: float = 0.0


def merge_scored_hits(
    batches: Iterable[Iterable[Any]],
    *,
    higher_is_better: bool = True,
) -> list[tuple[Any, float]]:
    """Dedupe hits from several queries; keep the best score per chunk fingerprint."""
    merged: dict[str, tuple[Any, float]] = {}
    for batch in batches:
        for item in batch or []:
            if isinstance(item, tuple) and len(item) >= 2:
                doc, raw_score = item[0], item[1]
            else:
                doc, raw_score = item, 0.0
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 0.0
            fp = chunk_fingerprint(chunk_text(doc))
            if not fp:
                continue
            previous = merged.get(fp)
            if previous is None:
                merged[fp] = (doc, score)
                continue
            better = score > previous[1] if higher_is_better else score < previous[1]
            if better:
                merged[fp] = (doc, score)
    ranked = list(merged.values())
    ranked.sort(key=lambda pair: pair[1], reverse=higher_is_better)
    return ranked


def search_queries_on_store(
    vectorstore: Any,
    queries: Iterable[str],
    *,
    k_per_query: int,
) -> list[tuple[Any, float]]:
    batches: list[list[Any]] = []
    for query in queries:
        q = (query or "").strip()
        if not q:
            continue
        hits: list[Any] = []
        try:
            hits = list(vectorstore.similarity_search_with_score(q, k=k_per_query) or [])
        except TypeError:
            try:
                docs = list(vectorstore.similarity_search(q, k=k_per_query) or [])
                hits = [(doc, 1.0 - (index * 0.01)) for index, doc in enumerate(docs)]
            except Exception:
                logger.exception("Retrieval search failed for query %r", q[:120])
                continue
        except Exception:
            logger.exception("Retrieval score-search failed for query %r", q[:120])
            try:
                docs = list(vectorstore.similarity_search(q, k=k_per_query) or [])
                hits = [(doc, 1.0 - (index * 0.01)) for index, doc in enumerate(docs)]
            except Exception:
                logger.exception("Retrieval fallback search failed for query %r", q[:120])
                continue
        batches.append(hits)
    return merge_scored_hits(batches)


def _as_scored_chunks(
    scored_docs: Iterable[tuple[Any, float]],
    *,
    is_bible: Callable[[Any], bool],
    source_key: Callable[[Any], str],
    used_quotes: Iterable[str],
    used_verses: Iterable[str],
    is_video: Optional[Callable[[Any], bool]] = None,
    query_tokens: Optional[Iterable[str]] = None,
) -> list[ScoredChunk]:
    chunks: list[ScoredChunk] = []
    quotes = list(used_quotes)
    verses = list(used_verses)
    video_fn = is_video or is_video_chunk
    focus = list(query_tokens or ())
    for doc, score in scored_docs:
        text = chunk_text(doc)
        if not text:
            continue
        bible = bool(is_bible(doc))
        chunks.append(
            ScoredChunk(
                doc=doc,
                score=float(score),
                source_key=source_key(doc),
                is_bible=bible,
                fingerprint=chunk_fingerprint(text),
                text=text,
                tokens=_token_set(text),
                book_key=bible_book_key(text) if bible else "",
                novelty=_novelty_penalty(text, quotes, verses),
                is_video=False if bible else bool(video_fn(doc)),
                topic_overlap=topic_overlap_score(doc, focus),
            )
        )
    return chunks


def apply_retrieval_threshold(
    scored_hits: list[tuple[Any, float]],
    *,
    threshold: float,
    retrieval_k: int,
) -> list[tuple[Any, float]]:
    """Keep only strong matches when the threshold is high enough to be useful.

    Soft escape: if almost nothing clears a high threshold, keep the ranked list
    so the model still has *some* context. At >=0.7 we only need one strong hit.
    """
    if threshold <= 0 or not scored_hits:
        return scored_hits
    if len(scored_hits) <= retrieval_k and threshold < 0.7:
        return scored_hits
    above = [pair for pair in scored_hits if pair[1] >= threshold]
    min_keep = 1 if threshold >= 0.7 else max(6, retrieval_k // 2)
    if len(above) >= min_keep:
        return above
    return scored_hits


def sources_cited_in_answer(
    docs: Iterable[Any],
    answer: str,
    source_label: Callable[[Any], str],
    *,
    limit: int = 8,
) -> list[str]:
    """Prefer source labels the model actually referenced in the answer text."""
    text = answer or ""
    text_l = text.lower()
    if not text.strip():
        return []

    cited: list[str] = []
    seen: set[str] = set()
    for index, doc in enumerate(docs, start=1):
        label = (source_label(doc) or "").strip()
        if not label or label == "Unknown":
            continue
        key = label.lower()
        if key in seen:
            continue
        matched = False
        if re.search(rf"\bnote\s*{index}\b", text_l):
            matched = True
        else:
            # Strip timestamp suffix for stem matching.
            stem = re.sub(
                r"\s*\[[0-9:]{4,8}[–-][0-9:]{4,8}\]\s*$",
                "",
                label,
            ).strip()
            # Drop parenthetical date: "Faith (May 23)" -> "Faith"
            stem_core = re.sub(r"\s*\([^)]*\)\s*$", "", stem).strip()
            candidates = [stem, stem_core]
            meta = getattr(doc, "metadata", {}) or {}
            for extra in (
                meta.get("topic_title"),
                meta.get("title"),
                meta.get("original_title"),
            ):
                if extra:
                    candidates.append(str(extra).strip())
            ts = str(meta.get("timestamp") or "").strip()
            if ts and ts in text:
                matched = True
            if not matched:
                for candidate in candidates:
                    if len(candidate) < 4:
                        continue
                    if candidate.lower() in text_l:
                        matched = True
                        break
        if matched:
            seen.add(key)
            cited.append(label)
            if len(cited) >= limit:
                break
    return cited


def select_diverse_docs(
    scored_docs: Iterable[tuple[Any, float]],
    *,
    k: int,
    bible_ratio: float = 0.40,
    video_ratio: float = 0.45,
    max_per_source: int = 4,
    max_per_bible_book: int = 2,
    used_quotes: Optional[Iterable[str]] = None,
    used_verses: Optional[Iterable[str]] = None,
    is_bible: Optional[Callable[[Any], bool]] = None,
    is_video: Optional[Callable[[Any], bool]] = None,
    source_key: Optional[Callable[[Any], str]] = None,
    relevance: float = 0.72,
    query: str = "",
) -> list[Any]:
    """Pick ``k`` chunks that stay relevant while spreading across sermons, videos, and books.

    Non-Bible sermon slots are split between written notes and video transcripts whenever
    both media types are available in the candidate pool (informational teaching mix).
    """
    if k <= 0:
        return []
    bible_fn = is_bible or (lambda doc: is_bible_source(metadata_source_hint(doc)))
    video_fn = is_video or is_video_chunk
    source_fn = source_key or chunk_source_key
    chunks = _as_scored_chunks(
        scored_docs,
        is_bible=bible_fn,
        source_key=source_fn,
        used_quotes=used_quotes or (),
        used_verses=used_verses or (),
        is_video=video_fn,
        query_tokens=query_focus_tokens(query),
    )
    if not chunks:
        return []

    if k <= 1:
        bible_target = 0
    else:
        bible_target = max(1, min(k - 1, int(round(k * bible_ratio))))
    sermon_target = k - bible_target

    has_video = any(not item.is_bible and item.is_video for item in chunks)
    has_document = any(not item.is_bible and not item.is_video for item in chunks)
    if sermon_target <= 1 or not (has_video and has_document):
        video_target = sermon_target if has_video and not has_document else 0
        document_target = sermon_target - video_target
    else:
        # Keep at least one written note and one video among sermon slots.
        video_target = max(1, min(sermon_target - 1, int(round(sermon_target * video_ratio))))
        document_target = sermon_target - video_target
        if document_target < 1:
            document_target = 1
            video_target = max(1, sermon_target - document_target)

    selected: list[ScoredChunk] = []
    selected_fps: set[str] = set()
    per_source: dict[str, int] = {}
    per_book: dict[str, int] = {}
    selected_tokens: list[frozenset[str]] = []

    def can_take(
        chunk: ScoredChunk,
        *,
        prefer_bible: Optional[bool],
        prefer_video: Optional[bool] = None,
    ) -> bool:
        if chunk.fingerprint in selected_fps:
            return False
        if per_source.get(chunk.source_key, 0) >= max_per_source:
            return False
        if prefer_bible is True and not chunk.is_bible:
            return False
        if prefer_bible is False and chunk.is_bible:
            return False
        if prefer_video is True and (chunk.is_bible or not chunk.is_video):
            return False
        if prefer_video is False and (chunk.is_bible or chunk.is_video):
            return False
        if query and not chunk.is_bible and chunk.topic_overlap <= 0:
            has_topical = any(
                (not other.is_bible)
                and other.topic_overlap > 0
                and other.fingerprint not in selected_fps
                and per_source.get(other.source_key, 0) < max_per_source
                for other in chunks
            )
            if has_topical:
                return False
        if chunk.is_bible and chunk.book_key:
            if per_book.get(chunk.book_key, 0) >= max_per_bible_book and any(
                item.is_bible for item in chunks if item.fingerprint not in selected_fps
            ):
                # Allow a second chunk from the same book only after other books are exhausted.
                unused_other_books = any(
                    other.is_bible
                    and other.fingerprint not in selected_fps
                    and other.book_key != chunk.book_key
                    and per_source.get(other.source_key, 0) < max_per_source
                    for other in chunks
                )
                if unused_other_books:
                    return False
        if chunk.novelty >= 0.35:
            has_fresh = any(
                other.novelty < 0.35
                and other.fingerprint not in selected_fps
                and per_source.get(other.source_key, 0) < max_per_source
                for other in chunks
            )
            if has_fresh:
                return False
        return True

    def best_candidate(
        prefer_bible: Optional[bool],
        *,
        prefer_video: Optional[bool] = None,
    ) -> Optional[ScoredChunk]:
        best: Optional[ScoredChunk] = None
        best_value = float("-inf")
        for chunk in chunks:
            if not can_take(chunk, prefer_bible=prefer_bible, prefer_video=prefer_video):
                continue
            overlap = max((_jaccard(chunk.tokens, tokens) for tokens in selected_tokens), default=0.0)
            source_pen = 0.14 * per_source.get(chunk.source_key, 0)
            topic_boost = 0.40 * chunk.topic_overlap
            value = (
                (relevance * chunk.score)
                - ((1.0 - relevance) * overlap)
                - chunk.novelty
                - source_pen
                + topic_boost
            )
            if value > best_value:
                best_value = value
                best = chunk
        return best

    def take(chunk: ScoredChunk) -> None:
        selected.append(chunk)
        selected_fps.add(chunk.fingerprint)
        per_source[chunk.source_key] = per_source.get(chunk.source_key, 0) + 1
        if chunk.book_key:
            per_book[chunk.book_key] = per_book.get(chunk.book_key, 0) + 1
        selected_tokens.append(chunk.tokens)

    def fill(count: int, *, prefer_bible: Optional[bool], prefer_video: Optional[bool] = None) -> None:
        while len(selected) < k and count > 0:
            picked = best_candidate(prefer_bible, prefer_video=prefer_video)
            if picked is None:
                break
            take(picked)
            count -= 1

    # Written sermon notes and video transcripts first, then Bible, then leftovers.
    fill(document_target, prefer_bible=False, prefer_video=False)
    fill(video_target, prefer_bible=False, prefer_video=True)
    while len(selected) < sermon_target:
        picked = best_candidate(prefer_bible=False)
        if picked is None:
            break
        take(picked)
    fill(bible_target, prefer_bible=True)
    while len(selected) < k:
        picked = best_candidate(prefer_bible=None)
        if picked is None:
            break
        take(picked)
    return [item.doc for item in selected]


def ensure_source_media_mix(
    preferred_labels: Iterable[str],
    docs: Iterable[Any],
    source_label: Callable[[Any], str],
    *,
    is_video: Optional[Callable[[Any], bool]] = None,
    limit: int = 5,
    min_count: int = 3,
    query: str = "",
) -> list[str]:
    """Return 3–5 distinct sermon/video sources, mixed when both media types exist.

    Citations are preferred, then remaining retrieved docs ranked by topical overlap.
    Multiple timestamps from the same sermon count as one source.
    """
    video_fn = is_video or is_video_chunk
    max_count = max(1, min(int(limit), 5))
    want = max(1, min(int(min_count), max_count))
    focus = query_focus_tokens(query)

    labeled: list[tuple[Any, str, str, float]] = []
    for doc in list(docs or []):
        label = (source_label(doc) or "").strip()
        if not label or label == "Unknown":
            continue
        labeled.append((doc, label, source_stem_key(label), topic_overlap_score(doc, focus)))

    def _is_note(doc: Any) -> bool:
        return (not video_fn(doc)) and (not is_bible_source(metadata_source_hint(doc)))

    by_stem: dict[str, tuple[Any, str, float]] = {}
    for doc, label, stem, overlap in labeled:
        previous = by_stem.get(stem)
        if previous is None or overlap > previous[2]:
            by_stem[stem] = (doc, label, overlap)

    ordered: list[tuple[Any, str, float]] = []
    seen_stems: set[str] = set()
    for label in preferred_labels:
        stem = source_stem_key(label)
        if not stem or stem in seen_stems:
            continue
        if stem in by_stem:
            ordered.append(by_stem[stem])
        else:
            cleaned = (label or "").strip()
            if cleaned and cleaned != "Unknown":
                ordered.append((None, cleaned, 0.0))
        seen_stems.add(stem)

    leftovers = sorted(
        (item for stem, item in by_stem.items() if stem not in seen_stems),
        key=lambda row: row[2],
        reverse=True,
    )
    # Prefer topical leftovers, then any remaining unique sermons (skip extra Bible fills).
    topical = [row for row in leftovers if row[2] > 0]
    rest = [row for row in leftovers if row[2] <= 0]
    for row in topical + rest:
        doc, _label, _overlap = row
        if doc is not None and is_bible_source(metadata_source_hint(doc)) and len(ordered) >= want:
            continue
        ordered.append(row)

    picked: list[tuple[Any, str, float]] = []
    picked_stems: set[str] = set()
    for row in ordered:
        stem = source_stem_key(row[1])
        if not stem or stem in picked_stems:
            continue
        overlap = row[2]
        if len(picked) >= want and overlap <= 0:
            continue
        picked.append(row)
        picked_stems.add(stem)
        if len(picked) >= max_count:
            break

    def _inject(predicate: Callable[[Any], bool]) -> None:
        if any(doc is not None and predicate(doc) for doc, _label, _overlap in picked):
            return
        for row in ordered:
            doc, label, overlap = row
            if doc is None or not predicate(doc):
                continue
            stem = source_stem_key(label)
            if stem in picked_stems:
                continue
            if len(picked) < max_count:
                picked.append(row)
                picked_stems.add(stem)
            else:
                picked[-1] = row
                picked_stems.add(stem)
            return

    if by_stem:
        _inject(_is_note)
        _inject(video_fn)

    while len(picked) < min(want, len(by_stem)):
        added = False
        for row in ordered:
            stem = source_stem_key(row[1])
            if stem in picked_stems:
                continue
            picked.append(row)
            picked_stems.add(stem)
            added = True
            break
        if not added:
            break

    return [label for _doc, label, _overlap in picked[:max_count]]


def format_reference_notes(
    docs: Iterable[Any],
    source_label: Callable[[Any], str],
    *,
    max_chars: int,
) -> str:
    """Join chunks with source labels so the model can quote across sermons."""
    blocks: list[str] = []
    used = 0
    for index, doc in enumerate(docs, start=1):
        label = source_label(doc) or "Unknown"
        text = chunk_text(doc)
        if not text:
            continue
        block = f"[Note {index} | {label}]\n{text}"
        extra = (2 if blocks else 0) + len(block)
        if used + extra > max_chars:
            remain = max_chars - used - (2 if blocks else 0)
            if remain > 80:
                blocks.append(block[:remain].rstrip())
            break
        blocks.append(block)
        used += extra
    return "\n\n".join(blocks)


def uniqueness_instruction(
    used_quotes: Iterable[str],
    used_verses: Iterable[str],
    *,
    is_followup: bool = False,
    prior_user_query: str = "",
) -> str:
    quotes = [item.strip() for item in used_quotes if item and item.strip()]
    verses = [item.strip() for item in used_verses if item and item.strip()]
    lines = ["<uniqueness>"]
    if is_followup:
        topic = " ".join((prior_user_query or "").split())
        if len(topic) > 160:
            topic = topic[:157] + "..."
        lines.extend(
            [
                "This is a follow-up in the SAME chat. Stay on the same pastoral topic as the prior turn.",
                "Clarify or expand the previous answer's steps; do not switch to an unrelated sermon theme.",
                "You may use fresh quotations and different NKJV verses, but they must serve THIS same topic.",
            ]
        )
        if topic:
            lines.append(f'Prior user question to stay anchored to: "{topic}"')
    else:
        lines.extend(
            [
                "Each reply must be unique. Do not restate the previous answer, recycle the same outline, "
                "or reuse the same Pastor Don/Susan quotation or the same NKJV verse across turns.",
                "Answer THIS user question with different notes, a different quotation, and different Scripture "
                "than earlier turns. Quote from more than one labeled source in REFERENCE NOTES when they fit.",
            ]
        )
    lines.append(
        "If a follow-up asks to clarify or apply the last answer, deepen those same steps with new wording—"
        "do not abandon them for a different subject."
    )
    if quotes:
        lines.append("Already-used quotations (do not repeat):")
        for quote in quotes[:8]:
            clipped = quote if len(quote) <= 180 else quote[:177] + "..."
            lines.append(f'- "{clipped}"')
    if verses:
        lines.append(
            "Already-used Scripture references (choose different NKJV passages on the same topic): "
            + ", ".join(verses[:12])
        )
    lines.append("</uniqueness>")
    return "\n".join(lines) + "\n"
