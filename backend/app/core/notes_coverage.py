"""Choose which retrieved windows become REFERENCE NOTES and source chips.

Does not rewrite the generated answer. Embeddings and the reranker still pick
the shortlist; this only drops clearly off-topic hits and flags nearest-neighbor
notes that do not mention the asked subject.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable, Optional

from .chat_retrieval import (
    chunk_source_key,
    chunk_text,
    is_bible_source,
    metadata_source_hint,
)
from .quote_chunking import split_sentences
from .grounding import looks_like_scripture_blob, normalize_grounding_text
from .note_priority import looks_like_deck_junk, looks_like_kjv_diction
from .teaching_claims import _WEAK_QUERY_WORDS, distinctive_query_tokens, query_topic_tokens

logger = logging.getLogger(__name__)

COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_NONE = "none"

_FILLER_SUBJECT_TOKENS = frozenset(
    {
        "real",
        "true",
        "give",
        "tell",
        "story",
        "notes",
        "outside",
        "inside",
        "question",
        "about",
        "help",
        "please",
        "would",
        "could",
        "should",
        "create",
        "explain",
        "write",
        "walk",
        "show",
        "describe",
        "according",
        "actually",
        "really",
    }
)


def notes_coverage_min_score(env: Optional[dict] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get("NOTES_COVERAGE_MIN_SCORE", "0.12") or "0.12").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.12


def notes_partial_limit(env: Optional[dict] = None, *, default: int = 8) -> int:
    source = env if env is not None else os.environ
    raw = str(source.get("NOTES_PARTIAL_LIMIT", str(default)) or str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


_LAYOUT_TOKENS = frozenset(
    {
        "sermon",
        "sermons",
        "point",
        "points",
        "outline",
        "topic",
        "topics",
        "week",
        "note",
        "notes",
    }
)


def coverage_subject_tokens(query: str) -> set[str]:
    """Distinctive topic words used to tell on-topic notes from nearest neighbors.

    Generic identity words (Jesus, Bible, Christian) stay out unless they are
    the only topic, which distinctive_query_tokens already handles. Filler
    words such as real or outside do not count as coverage. Request words
    such as "tell the story" must not hide the topic word behind them.
    """
    raw = query_topic_tokens(query)
    distinctive = distinctive_query_tokens(raw)
    strong = {token for token in distinctive if token not in _WEAK_QUERY_WORDS}
    distinctive = strong or distinctive

    def _usable(tokens: set[str]) -> set[str]:
        return {
            token
            for token in tokens
            if token not in _FILLER_SUBJECT_TOKENS
            and token not in _LAYOUT_TOKENS
            and len(token) >= 3
        }

    kept = _usable(distinctive)
    if kept:
        return kept
    return _usable(raw)


def _blob_has_subject(text: str, tokens: set[str]) -> bool:
    if not tokens:
        return True
    blob = normalize_grounding_text(text)
    if not blob:
        return False
    return any(token in blob for token in tokens)


def _combined_text(docs: Iterable[Any]) -> str:
    parts = [chunk_text(doc) for doc in docs]
    return " ".join(part for part in parts if part)


def select_reference_notes(
    query: str,
    scored_hits: Iterable[tuple[Any, float]],
    *,
    limit: int = 24,
    min_score: Optional[float] = None,
    partial_limit: Optional[int] = None,
) -> tuple[list[Any], str]:
    """Return (docs, coverage) for prompting and source chips.

    ``full``: notes mention the asked subject, or the query has no distinctive
    subject words (faith, greetings).
    ``partial``: nearest windows scored high enough but do not mention the
    distinctive subject; keep a shorter list so the model can teach what is
    actually there without a 24-window dump.
    ``none``: no hits, or every score is below the floor. Empty docs so chat
    uses EMPTY_REFERENCE_NOTES and no sermon chips.
    """
    hits = []
    for item in scored_hits or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        doc, raw_score = item[0], item[1]
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        hits.append((doc, score))
    cap = max(1, int(limit))
    hits = hits[:cap]
    if not hits:
        return [], COVERAGE_NONE

    floor = notes_coverage_min_score() if min_score is None else float(min_score)
    best = max(score for _doc, score in hits)
    # Fail open when scores are missing or on an unknown scale.
    if best <= 0.0 or best > 1.0:
        kept = [doc for doc, _score in hits]
        subject = coverage_subject_tokens(query)
        if _blob_has_subject(_combined_text(kept), subject):
            return kept, COVERAGE_FULL
        adjacent = notes_partial_limit() if partial_limit is None else max(1, int(partial_limit))
        return kept[:adjacent], COVERAGE_PARTIAL

    passing = [(doc, score) for doc, score in hits if score >= floor]
    if not passing:
        return [], COVERAGE_NONE

    kept = [doc for doc, _score in passing]
    subject = coverage_subject_tokens(query)
    if _blob_has_subject(_combined_text(kept), subject):
        return kept, COVERAGE_FULL
    adjacent = notes_partial_limit() if partial_limit is None else max(1, int(partial_limit))
    return kept[:adjacent], COVERAGE_PARTIAL


_VERSE_LEAK_RE = re.compile(
    r"(?i)(\(nkjv\)|\(kjv\)|\(niv\)|\(nasb\)|\(lb\)|\d+\s*[“\"']|\d+for\b)"
)


def _is_bible_doc(doc: Any) -> bool:
    meta = getattr(doc, "metadata", None) or {}
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    return is_bible_source(metadata_source_hint(doc))


def _token_count(words: list[str], token: str) -> int:
    """Count a topic word, including alcoholic/drinking style variants."""
    if not token:
        return 0
    if len(token) >= 5:
        return sum(1 for word in words if word == token or word.startswith(token))
    return words.count(token)


def _subject_hits(text: str, subject: set[str]) -> tuple[int, int]:
    words = normalize_grounding_text(text).split()
    if not words or not subject:
        return 0, 0
    present = 0
    hits = 0
    for token in subject:
        count = _token_count(words, token)
        if count:
            present += 1
            hits += count
    return present, hits


def sermon_rerank_min_margin(env: Optional[dict] = None) -> float:
    """How far the best sermon must lead the next one.

    Unrelated questions produce a cluster of low, similar scores. A sermon that
    actually teaches the question leads the next file. Zero disables the check.
    """
    source = env if env is not None else os.environ
    raw = str(source.get("SERMON_RERANK_MIN_MARGIN", "0") or "0").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.0


def sermon_rerank_min_score(env: Optional[dict] = None) -> float:
    """Lowest rerank score that still counts as teaching the question.

    The default is a placeholder until a dev-pod run records the score of a
    hope sermon on a hope question and the score of the best sermon on a
    question the library does not cover. NOTES_COVERAGE_MIN_SCORE is a
    different scale and is not this cutoff.
    """
    source = env if env is not None else os.environ
    raw = str(source.get("SERMON_RERANK_MIN_SCORE", "0.01") or "0.01").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.01


def _passage_rerank_score(doc: Any) -> Optional[float]:
    meta = getattr(doc, "metadata", None) or {}
    raw = meta.get("rerank_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def choose_sermon_by_rerank(
    scored_hits: Iterable[tuple[Any, float]] | None,
    *,
    min_score: Optional[float] = None,
) -> tuple[list[Any], str, float]:
    """Keep the one sermon whose best passage the reranker scored highest.

    Passages are grouped by sermon file. A lower-scored illustration loses to
    the sermon the reranker ranks as the match. A weak best score returns no
    sermon. Hits without a rerank score are ignored so embedding scores on a
    different scale cannot win.
    """
    floor = sermon_rerank_min_score() if min_score is None else float(min_score)
    groups: dict[str, list[tuple[float, Any]]] = {}
    for item in scored_hits or []:
        if not isinstance(item, tuple) or not item:
            continue
        doc = item[0]
        if doc is None or _is_bible_doc(doc):
            continue
        score = _passage_rerank_score(doc)
        if score is None:
            continue
        groups.setdefault(chunk_source_key(doc), []).append((score, doc))
    if not groups:
        return [], COVERAGE_NONE, 0.0
    ranked_groups = sorted(
        groups.items(),
        key=lambda item: max(score for score, _doc in item[1]),
        reverse=True,
    )
    best_key = ranked_groups[0][0]
    ranked = sorted(groups[best_key], key=lambda item: item[0], reverse=True)
    best_score = ranked[0][0]
    second_score = 0.0
    if len(ranked_groups) > 1:
        second_score = max(score for score, _doc in ranked_groups[1][1])
    # A weak cluster of unrelated sermons sits near the same score. A real match
    # pulls ahead of the next sermon. The absolute floor alone cannot separate
    # those two cases when both land near 0.5.
    margin = best_score - second_score
    logger.warning(
        "Rerank candidates best=%.3f second=%.3f margin=%.3f",
        best_score,
        second_score,
        margin,
    )
    if margin < sermon_rerank_min_margin() and second_score > 0:
        return [], COVERAGE_NONE, best_score
    if best_score < floor:
        return [], COVERAGE_NONE, best_score
    return [doc for _score, doc in ranked], COVERAGE_FULL, best_score


def query_changes_locked_sermon(query: str, opening_query: str, sermon_text: str) -> bool:
    """True when a later turn names a subject the locked sermon does not teach.

    Short follow-ups stay. A new subject is a majority of the question's topic
    words, each long enough to be a topic, and absent from both the sermon and
    the opening question. This is the same rule for every story.
    """
    tokens = coverage_subject_tokens(query)
    if not tokens or not (sermon_text or "").strip():
        return False
    sermon_words = normalize_grounding_text(sermon_text).split()
    opening_words = normalize_grounding_text(opening_query).split()
    novel = [
        token
        for token in tokens
        if not _token_count(sermon_words, token) and not _token_count(opening_words, token)
    ]
    topical = [token for token in novel if len(token) >= 5]
    if not topical:
        return False
    return len(topical) / len(tokens) >= 0.6


def focus_retrieved_notes(
    query: str,
    docs: Iterable[Any] | None,
    *,
    max_sources: int = 2,
    max_docs: int = 12,
) -> list[Any]:
    """Keep the sermon that is actually about the question.

    The same rule applies to every question. A sermon that only mentions the
    topic in passing loses to the sermon that keeps teaching it. A second
    sermon is included only when it is about the topic to nearly the same
    degree, so five loosely related sermons are not mashed into one outline.
    """
    documents = [doc for doc in (docs or []) if doc is not None]
    sermons = [doc for doc in documents if not _is_bible_doc(doc)]
    cap = max(1, int(max_docs))
    if not sermons:
        return documents[:cap]
    subject = coverage_subject_tokens(query)
    if not subject:
        return sermons[:cap]

    groups: dict[str, list[Any]] = {}
    order: list[str] = []
    first_index: dict[str, int] = {}
    for index, doc in enumerate(sermons):
        key = chunk_source_key(doc)
        if key not in groups:
            groups[key] = []
            order.append(key)
            first_index[key] = index
        groups[key].append(doc)

    scored: list[tuple[int, int, int, str]] = []
    for key in order:
        blob = " ".join(
            f"{metadata_source_hint(doc)} {chunk_text(doc)}" for doc in groups[key]
        )
        present, hits = _subject_hits(blob, subject)
        scored.append((present, hits, -first_index[key], key))
    scored.sort(reverse=True)
    best_present, best_hits, _rank, best_key = scored[0]
    if best_present <= 0:
        return sermons[:cap]

    chosen = [best_key]
    source_cap = max(1, int(max_sources))
    for present, hits, _rank, key in scored[1:]:
        if len(chosen) >= source_cap:
            break
        if present < best_present:
            break
        if best_hits <= 0 or hits * 4 < best_hits * 3:
            break
        chosen.append(key)
    kept: list[Any] = []
    for key in chosen:
        kept.extend(groups[key])
    return kept[:cap]


def _usable_passage_sentences(blob: str) -> list[str]:
    usable: list[str] = []
    for sentence in split_sentences(blob) or []:
        sentence = sentence.strip()
        if len(sentence) < 40:
            continue
        if (
            looks_like_kjv_diction(sentence)
            or looks_like_scripture_blob(sentence)
            or _VERSE_LEAK_RE.search(sentence)
        ):
            continue
        if re.search(r"\bthe LORD\b", sentence) and not re.search(
            r"(?i)\b(giant|tongue|covenant|husband|wife|means)\b",
            sentence,
        ):
            continue
        if re.search(r"(?i)\bthey will (?:fail|cease|vanish)\b", sentence) and not re.search(
            r"(?i)\b(?:we|our|you|your)\b",
            sentence,
        ):
            continue
        if len(re.findall(r"(?i)\b\w+eth\b", sentence)) >= 2:
            continue
        if looks_like_deck_junk(sentence):
            continue
        cleaned = re.sub(r"\s+\d{1,3}\b", " ", sentence)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -•●▪")
        if len(cleaned) >= 40:
            usable.append(cleaned)
    return usable


def sermon_lines_for_answer(
    query: str,
    docs: Iterable[Any] | None,
    *,
    limit: int = 8,
) -> str:
    """Sentences from the highest-scored passage, in passage order.

    The same selection runs for every question. The query is unused for
    picking a word inside the sermon; the reranker already chose the passage.
    """
    del query
    sermons = [doc for doc in (docs or []) if doc is not None and not _is_bible_doc(doc)]
    if not sermons:
        return ""
    ordered = sorted(sermons, key=lambda doc: _passage_rerank_score(doc) or -1.0, reverse=True)
    cap = max(1, int(limit))
    for doc in ordered:
        lines = _usable_passage_sentences(chunk_text(doc))
        if lines:
            return "\n\n".join(lines[:cap])
    return ""
