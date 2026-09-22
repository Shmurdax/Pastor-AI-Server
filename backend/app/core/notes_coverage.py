"""Choose which retrieved windows become REFERENCE NOTES and source chips.

Does not rewrite the generated answer. Embeddings and the reranker still pick
the shortlist; this only drops clearly off-topic hits and flags nearest-neighbor
notes that do not mention the asked subject.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional

from .chat_retrieval import chunk_text
from .grounding import normalize_grounding_text
from .teaching_claims import distinctive_query_tokens, query_topic_tokens

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


def coverage_subject_tokens(query: str) -> set[str]:
    """Distinctive topic words used to tell on-topic notes from nearest neighbors.

    Generic identity words (Jesus, Bible, Christian) stay out unless they are
    the only topic, which distinctive_query_tokens already handles. Filler
    words such as real or outside do not count as coverage.
    """
    distinctive = distinctive_query_tokens(query_topic_tokens(query))
    return {
        token
        for token in distinctive
        if token not in _FILLER_SUBJECT_TOKENS and len(token) >= 3
    }


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
