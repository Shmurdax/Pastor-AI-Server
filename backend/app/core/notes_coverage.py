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


# Light English morphology only — shared stems, not topic synonym lists.
_MORPH_SUFFIXES = (
    "ational",
    "ation",
    "tion",
    "sion",
    "ance",
    "ence",
    "ness",
    "ment",
    "ings",
    "ying",
    "ing",
    "ied",
    "ies",
    "ers",
    "ely",
    "ly",
    "ed",
    "es",
    "er",
    "s",
)


def _morph_stem(word: str) -> str:
    """Strip one common English suffix for bidirectional topic matching."""
    text = (word or "").lower()
    if len(text) < 5:
        return text
    for suffix in _MORPH_SUFFIXES:
        if len(text) > len(suffix) + 3 and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _tokens_morph_match(left: str, right: str) -> bool:
    """True when two English words share a stem or clear prefix variant."""
    a = (left or "").lower()
    b = (right or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    stem_a = _morph_stem(a)
    stem_b = _morph_stem(b)
    if len(stem_a) >= 4 and stem_a == stem_b:
        return True
    if len(stem_a) >= 4 and len(stem_b) >= 4 and (
        stem_a.startswith(stem_b) or stem_b.startswith(stem_a)
    ):
        return True
    return False


def _token_count(words: list[str], token: str) -> int:
    """Count a topic word, including light morphological variants."""
    if not token:
        return 0
    return sum(1 for word in words if _tokens_morph_match(word, token))


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


def _passage_embed_score(doc: Any) -> float:
    meta = getattr(doc, "metadata", None) or {}
    raw = meta.get("embed_score")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _passage_rerank_score(doc: Any) -> Optional[float]:
    meta = getattr(doc, "metadata", None) or {}
    raw = meta.get("rerank_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


_QUESTION_FILLER = frozenset(
    {
        "create",
        "someone",
        "stay",
        "give",
        "tell",
        "using",
        "uses",
        "talks",
        "really",
        "actually",
        "according",
        "please",
        "there",
        "their",
        "together",
        "between",
        "among",
        "within",
        "daily",
        "look",
        "looks",
        "like",
        "make",
        "makes",
        "does",
        "what",
        "when",
        "where",
        "which",
    }
)


def sermon_mentions_question(query: str, docs: Iterable[Any] | None) -> bool:
    """True when the chosen sermon's body is about the question's topic.

    Rerank already picked the file. This gate only blocks winners whose
    passages do not talk about the question. Matching uses light English
    morphology so forgive/forgiveness style variants count. A title match is
    never required and never enough on its own. One incidental shared word in
    a long multi-topic question is not enough; about half of the distinctive
    topic words must appear in the body (at least one).
    """
    tokens = distinctive_query_tokens(query_topic_tokens(query))
    tokens = {
        token
        for token in tokens
        if token not in _QUESTION_FILLER and token not in _FILLER_SUBJECT_TOKENS
    }
    if not tokens:
        return True
    documents = [doc for doc in (docs or []) if doc is not None]
    if not documents:
        return False
    passage_words: list[str] = []
    for doc in documents:
        passage_words.extend(normalize_grounding_text(chunk_text(doc)).split())
    hits = sum(1 for token in tokens if _token_count(passage_words, token))
    # Threshold uses non-weak topic words when present, but any topic hit counts —
    # so a hope sermon still covers a hope/sick/grieving question.
    strong = {token for token in tokens if token not in _WEAK_QUERY_WORDS}
    basis = strong or tokens
    needed = max(1, (len(basis) + 1) // 2)
    return hits >= needed


def _group_rerank_aggregate(pairs: list[tuple[float, Any]], *, top_n: int = 3) -> float:
    """Score a sermon without punishing short topical files.

    Uses the mean of the strongest available passages (up to top_n), then a
    small bonus when a second passage is nearly as strong. Raw sums of three
    mediocre hits from a long transcript no longer beat one clear short-file
    match. A single hot aside with a weak second chunk still loses to a file
    that teaches the topic across several strong passages.
    """
    if not pairs:
        return 0.0
    scores = sorted((float(score) for score, _doc in pairs), reverse=True)[: max(1, top_n)]
    mean = float(sum(scores)) / float(len(scores))
    if len(scores) >= 2 and scores[1] >= scores[0] - 0.12:
        mean += 0.05
    return mean


def sermon_select_max_files(env: Optional[dict] = None) -> int:
    source = env if env is not None else os.environ
    raw = str(source.get("SERMON_SELECT_MAX_FILES", "3") or "3").strip()
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return 3


def _sermon_chunk_caps(env: Optional[dict] = None) -> tuple[int, int, int]:
    """How many windows to keep from primary / secondary / tertiary files."""
    source = env if env is not None else os.environ

    def _read(name: str, default: int) -> int:
        raw = str(source.get(name, str(default)) or str(default)).strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    return (
        _read("SERMON_PRIMARY_CHUNK_CAP", 10),
        _read("SERMON_SECONDARY_CHUNK_CAP", 4),
        _read("SERMON_TERTIARY_CHUNK_CAP", 3),
    )


def diversify_hits_by_source(
    scored_hits: Iterable[tuple[Any, float]] | None,
    *,
    max_per_source: int = 8,
    limit: int = 96,
) -> list[tuple[Any, float]]:
    """Keep strong hits while reserving slots across distinct sermon files.

    Long transcripts otherwise fill the rerank window and crowd out short
    topical sermons that only have a few chunks in the ANN shortlist.
    """
    hits = [item for item in (scored_hits or []) if isinstance(item, tuple) and item]
    if not hits:
        return []
    ordered = sorted(
        hits,
        key=lambda item: float(item[1]) if item[1] is not None else 0.0,
        reverse=True,
    )
    per_source: dict[str, int] = {}
    kept: list[tuple[Any, float]] = []
    cap = max(1, int(max_per_source))
    total = max(1, int(limit))
    for doc, score in ordered:
        if doc is None or len(kept) >= total:
            break
        key = chunk_source_key(doc)
        if per_source.get(key, 0) >= cap:
            continue
        kept.append((doc, score))
        per_source[key] = per_source.get(key, 0) + 1
    return kept


def choose_sermon_by_rerank(
    scored_hits: Iterable[tuple[Any, float]] | None,
    *,
    min_score: Optional[float] = None,
    max_files: Optional[int] = None,
    query: str = "",
) -> tuple[list[Any], str, float]:
    """Keep the top sermon files that teach the question, primary first.

    Passages are grouped by sermon file and ranked with a length-fair score so
    short topical sermons can compete with long multi-hit transcripts. Up to
    max_files sermons that clear the score floor (and, when query is set, the
    body teaching gate) are kept. The primary file contributes the most
    windows; secondary files are supporting context. Titles are not used to
    pick winners. Refuse only when no file clears the gates.
    """
    floor = sermon_rerank_min_score() if min_score is None else float(min_score)
    file_cap = sermon_select_max_files() if max_files is None else max(1, int(max_files))
    primary_cap, secondary_cap, tertiary_cap = _sermon_chunk_caps()
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
        key=lambda item: (
            _group_rerank_aggregate(item[1]),
            max(score for score, _doc in item[1]),
        ),
        reverse=True,
    )
    best_key = ranked_groups[0][0]
    ranked_best = sorted(groups[best_key], key=lambda item: item[0], reverse=True)
    best_score = ranked_best[0][0]
    best_aggregate = _group_rerank_aggregate(ranked_best)
    second_score = 0.0
    second_aggregate = 0.0
    if len(ranked_groups) > 1:
        second_pairs = ranked_groups[1][1]
        second_score = max(score for score, _doc in second_pairs)
        second_aggregate = _group_rerank_aggregate(second_pairs)
    margin = best_aggregate - second_aggregate
    top = []
    for key, pairs in ranked_groups[:3]:
        score = max(item[0] for item in pairs)
        aggregate = _group_rerank_aggregate(pairs)
        sample = pairs[0][1]
        meta = getattr(sample, "metadata", None) or {}
        label = meta.get("title") or meta.get("source") or key
        embed = _passage_embed_score(sample)
        top.append(
            f"agg={aggregate:.3f}/best={score:.3f}/embed={embed:.3f}:{label}"
        )
    logger.warning(
        "Rerank candidates best=%.3f agg=%.3f second=%.3f second_agg=%.3f margin=%.3f top=%s",
        best_score,
        best_aggregate,
        second_score,
        second_aggregate,
        margin,
        " | ".join(top),
    )
    # Margin alone must not refuse when several files are close — top-K keeps
    # them. Only an optional positive margin floor still blocks a lone weak
    # cluster when max_files is forced to 1.
    if (
        file_cap <= 1
        and margin < sermon_rerank_min_margin()
        and second_aggregate > 0
    ):
        return [], COVERAGE_NONE, best_score
    if best_score < floor:
        return [], COVERAGE_NONE, best_score

    weights = (1.0, 0.55, 0.35)
    caps = (primary_cap, secondary_cap, tertiary_cap)
    kept_docs: list[Any] = []
    kept_labels: list[str] = []
    primary_score = 0.0
    primary_aggregate = 0.0
    for key, pairs in ranked_groups:
        if len(kept_labels) >= file_cap:
            break
        ranked = sorted(pairs, key=lambda item: item[0], reverse=True)
        file_best = ranked[0][0]
        if file_best < floor:
            continue
        file_docs = [doc for _score, doc in ranked]
        if query and not sermon_mentions_question(query, file_docs):
            continue
        file_aggregate = _group_rerank_aggregate(ranked)
        if kept_labels:
            # Supporting files must be near the primary on length-fair score so a
            # single hot aside cannot ride along as a second "source".
            if primary_aggregate > 0 and file_aggregate < primary_aggregate * 0.8:
                continue
            if primary_score > 0 and file_best < primary_score * 0.55:
                continue
        rank_index = len(kept_labels)
        weight = weights[min(rank_index, len(weights) - 1)]
        cap = caps[min(rank_index, len(caps) - 1)]
        sample_meta = getattr(ranked[0][1], "metadata", None) or {}
        label = sample_meta.get("title") or sample_meta.get("source") or key
        for _score, doc in ranked[:cap]:
            meta = getattr(doc, "metadata", None)
            if isinstance(meta, dict):
                meta["sermon_weight"] = weight
                meta["sermon_rank"] = rank_index + 1
            kept_docs.append(doc)
        kept_labels.append(str(label))
        if rank_index == 0:
            primary_score = file_best
            primary_aggregate = file_aggregate

    if not kept_docs:
        return [], COVERAGE_NONE, best_score
    logger.warning(
        "Teaching sermons score=%.3f sources=%s query=%s",
        primary_score,
        " | ".join(kept_labels),
        (query or "")[:80],
    )
    return kept_docs, COVERAGE_FULL, primary_score


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
