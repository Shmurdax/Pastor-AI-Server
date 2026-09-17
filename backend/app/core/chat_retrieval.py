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

_APPLY_RE = re.compile(
    r"\b("
    r"what (?:do|should|would) i say|"
    r"how do i (?:say|tell|respond|talk|put|phrase)|"
    r"in the kitchen|tonight|give me (?:the )?words|a script"
    r")\b",
    re.IGNORECASE,
)

_LIBRARY_PULL_RE = re.compile(
    r"\b("
    r"pull(?:\s+up)?\s+(?:a\s+)?sermon|"
    r"(?:show|get|find|open|read)\s+(?:me\s+)?(?:a\s+)?sermon|"
    r"sermon\s+(?:in\s+the\s+)?(?:library|notes)|"
    r"from\s+the\s+sermon\s+library|"
    r"sermon\s+excerpt|"
    r"excerpt\s+(?:from|of|on)"
    r")\b",
    re.IGNORECASE,
)
_LIBRARY_FOCUS_STOP = frozenset(
    {"excerpt", "excerpts", "find", "library", "open", "pull", "read", "show"}
)
# "three point sermon on Faith" should embed Faith, not "three/point".
_OUTLINE_FOCUS_STOP = frozenset(
    {
        "five",
        "four",
        "numbered",
        "outline",
        "outlines",
        "point",
        "points",
        "series",
        "three",
        "week",
        "weeks",
    }
)
_TOPIC_SERMON_RE = re.compile(
    r"(?:"
    r"\b(?:three|four|five|3|4|5)[\s-]*points?\s+(?:sermon|message|teaching|homily|outline)\b|"
    r"\b(?:sermon|message|homily)\s+(?:series|outline)\s+(?:on|about|for)\b|"
    r"\b(?:need|want|write|prepare|give|create|draft|compose|generate|make|develop|preach|build)\s+"
    r"(?:me\s+)?(?:a\s+|an\s+)?(?:\d+[\s-]*)?(?:point\s+)?(?:sermon|message|homily|outline)\b|"
    r"\ba\s+sermon\s+(?:on|about|for)\b|"
    r"\bsermon\s+about\b"
    r")",
    re.IGNORECASE,
)

INTENT_NEW_TOPIC = "new_topic"
INTENT_NEW_ANGLE = "same_topic_new_angle"
INTENT_CLARIFY = "clarify"
INTENT_APPLY = "apply"
INTENT_SOCIAL = "social"
_CONTINUING_INTENTS = frozenset({INTENT_NEW_ANGLE, INTENT_CLARIFY, INTENT_APPLY})

_HEADING_LINE_RE = re.compile(
    r"^\s*(?:#{1,3}\s+|\*\*)([^*#\n]{3,80}?)(?:\*\*)?\s*$",
    re.MULTILINE,
)
_HEADING_BULLET_RE = re.compile(
    r"^\s*[-*]\s+(?:\*\*)?([A-Z][A-Za-z' /]{2,40})(?:\*\*)?:",
    re.MULTILINE,
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

# Generic ask-phrasing that should not be embedded or count as topical overlap.
# Keep social-issue and theology terms (homosexuality, abortion, predestination,
# salvation, etc.) — only drop instruction/template language.
_GENERIC_FOCUS_STOPWORDS = frozenset(
    {
        "about",
        "answer",
        "based",
        "chapter",
        "compose",
        "create",
        "draft",
        "essay",
        "explain",
        "generate",
        "give",
        "help",
        "homily",
        "lesson",
        "lessons",
        "library",
        "like",
        "excerpt",
        "excerpts",
        "make",
        "message",
        "messages",
        "need",
        "notes",
        "outline",
        "paper",
        "passage",
        "passages",
        "please",
        "prepare",
        "produce",
        "prompt",
        "question",
        "request",
        "response",
        "sermon",
        "sermons",
        "someone",
        "something",
        "stories",
        "story",
        "talk",
        "talks",
        "teach",
        "teaching",
        "teachings",
        "tell",
        "topic",
        "topics",
        "verse",
        "verses",
        "video",
        "videos",
        "want",
        "would",
        "write",
        "written",
    }
)

# Whisper often misspells short biblical names; match those variants in transcripts.
# Do not use common English words (able, cane) as global aliases — they match
# ordinary sermon intros ("we are able to…") and drown the real story clips.
_WHISPER_NAME_ALIASES = {
    "abel": ("able",),
    "abraham": ("abram",),
    "cain": ("kane", "kayn"),
    "elijah": ("elija",),
    "isaac": ("issac",),
    "moses": ("mozes",),
    "noah": ("noa",),
    "pharaoh": ("pharoah",),
    "sarah": ("sarai",),
}
_NOISY_WHISPER_ALIASES = frozenset({"able", "cane"})

# When several names appear together, add the usual NKJV landing passage.
_NAME_PASSAGES = {
    frozenset({"cain", "abel"}): "Genesis 4",
    frozenset({"cain"}): "Genesis 4",
    frozenset({"abel"}): "Genesis 4",
    frozenset({"noah"}): "Genesis 6",
    frozenset({"abraham", "isaac"}): "Genesis 22",
    frozenset({"david", "goliath"}): "1 Samuel 17",
    frozenset({"moses"}): "Exodus",
    frozenset({"jonah"}): "Jonah 1",
}


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


def looks_like_library_pull(query: str) -> bool:
    """True when the user asked to open one sermon from the library."""
    return bool(_LIBRARY_PULL_RE.search(query or ""))


def looks_like_topic_sermon(query: str) -> bool:
    """True when the user asked for a sermon/outline on a topic (not a library pull)."""
    text = query or ""
    if looks_like_library_pull(text):
        return False
    return bool(_TOPIC_SERMON_RE.search(text))


def looks_like_primary_source_lock(query: str) -> bool:
    """True when retrieval should stay inside one sermon plus Bible verses."""
    return looks_like_library_pull(query) or looks_like_topic_sermon(query)


def portable_search_focus(query: str) -> str:
    """Topic words for embeddings: drop pull/outline scaffolding."""
    focus = keyword_search_query(query)
    if not looks_like_library_pull(query) and not looks_like_topic_sermon(query):
        return focus
    return " ".join(
        token
        for token in focus.split()
        if token.lower() not in _LIBRARY_FOCUS_STOP
        and token.lower() not in _OUTLINE_FOCUS_STOP
    )


def restrict_docs_to_primary_source(
    docs: Optional[Iterable[Any]],
    *,
    topic: str = "",
    is_bible: Optional[Callable[[Any], bool]] = None,
    source_key: Optional[Callable[[Any], str]] = None,
    limit: int = 8,
) -> list[Any]:
    """Keep chunks from one sermon plus any already-selected Bible verses."""
    bible_fn = is_bible or (lambda _doc: False)
    source_fn = source_key or chunk_source_key
    topic_tokens = set(portable_search_focus(topic).lower().split())
    if not topic_tokens:
        topic_tokens = set(keyword_search_query(topic).lower().split())
    scores: dict[str, int] = {}
    counts: dict[str, int] = {}
    ordered: list[Any] = list(docs or [])
    for doc in ordered:
        if bible_fn(doc):
            continue
        key = source_fn(doc)
        counts[key] = counts.get(key, 0) + 1
        blob = f"{metadata_source_hint(doc)} {chunk_text(doc)[:500]}".lower()
        overlap = sum(1 for token in topic_tokens if token and token in blob)
        scores[key] = scores.get(key, 0) + overlap
    if not counts:
        return ordered
    primary = next((source_fn(doc) for doc in ordered if not bible_fn(doc)), None)
    if max(scores.values(), default=0) > 0:
        primary = max(counts, key=lambda key: (scores.get(key, 0), counts[key]))
    kept: list[Any] = []
    bible_docs: list[Any] = []
    for doc in ordered:
        if bible_fn(doc):
            bible_docs.append(doc)
            continue
        if source_fn(doc) == primary and len(kept) < max(1, limit):
            kept.append(doc)
    return kept + bible_docs[:2]


def looks_like_followup(query: str) -> bool:
    """True for short / clarify-style prompts (not the only follow-up gate)."""
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


def topic_anchor_query(current: str, prior_user_queries: Optional[Iterable[str]] = None) -> str:
    """Blend the last user turn into retrieval so follow-ups keep the topic."""
    current_q = (current or "").strip()
    last_prior = _last_prior_user(current_q, prior_user_queries)
    if last_prior and current_q:
        return f"{last_prior} {current_q}"
    return current_q or last_prior


def _last_prior_user(current_q: str, prior_user_queries: Optional[Iterable[str]]) -> str:
    current_key = (current_q or "").strip().lower()
    for item in reversed(list(prior_user_queries or [])):
        text = str(item or "").strip()
        if text and text.lower() != current_key:
            return text
    return ""


def classify_followup_intent(
    current: str,
    prior_user_queries: Optional[Iterable[str]] = None,
    prior_ai_texts: Optional[Iterable[str]] = None,
) -> str:
    """Classify a turn so retrieval and steers are not regex-only.

    With chat history, a new question on the same pastoral situation is a
    new-angle follow-up unless it looks like clarify, apply, or a topic break.
    """
    from .chat_system_prompt import looks_like_brief_social

    current_q = (current or "").strip()
    if looks_like_brief_social(current_q):
        return INTENT_SOCIAL
    last_prior = _last_prior_user(current_q, prior_user_queries)
    if not last_prior:
        return INTENT_NEW_TOPIC
    if _APPLY_RE.search(current_q):
        return INTENT_APPLY
    # Explicit clarify words stay on-topic even when they share no keywords
    # ("What do you mean?"). Short new questions do not — check topic-break
    # first so "What is communion?" is not treated as a follow-up.
    if _FOLLOWUP_RE.search(current_q):
        return INTENT_CLARIFY
    current_tokens = set(keyword_search_query(current_q).lower().split())
    prior_blob = last_prior
    for item in reversed(list(prior_ai_texts or [])):
        text = str(item or "").strip()
        if text:
            prior_blob = f"{last_prior} {keyword_search_query(text[:900])}"
            break
    prior_tokens = set(keyword_search_query(prior_blob).lower().split())
    if current_tokens and prior_tokens and not (current_tokens & prior_tokens):
        return INTENT_NEW_TOPIC
    if looks_like_followup(current_q):
        return INTENT_CLARIFY
    return INTENT_NEW_ANGLE


def extract_used_headings(texts: Iterable[str], *, limit: int = 8) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts or []:
        for match in _HEADING_LINE_RE.finditer(text or ""):
            heading = " ".join(match.group(1).split()).strip(" #")
            key = heading.lower()
            if len(heading) < 3 or key in seen:
                continue
            seen.add(key)
            found.append(heading)
            if len(found) >= limit:
                return found
        for match in _HEADING_BULLET_RE.finditer(text or ""):
            heading = " ".join(match.group(1).split()).strip()
            key = heading.lower()
            if len(heading) < 3 or key in seen:
                continue
            seen.add(key)
            found.append(heading)
            if len(found) >= limit:
                return found
    return found


def keyword_search_query(text: str) -> str:
    """Content words for embeddings: drop filler like \"generate a sermon\"."""
    terms = [
        token
        for token in re.findall(r"[A-Za-z']{3,}", text or "")
        if token.lower() not in _QUESTION_STOPWORDS
        and token.lower() not in _GENERIC_FOCUS_STOPWORDS
        and token.lower() not in _ENTITY_NOISE
    ]
    return " ".join(terms).strip()


_ENTITY_NOISE = frozenset(
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
        "do",
        "for",
        "from",
        "her",
        "him",
        "his",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "the",
        "to",
        "us",
        "we",
        "with",
        "you",
        "your",
    }
)


def retrieval_bible_names(text: str) -> list[str]:
    """Character names from the query, ignoring Bible-list collisions like ``the`` / ``on``."""
    from .chat_system_prompt import find_biblical_character_names

    names = []
    seen: set[str] = set()
    for name in find_biblical_character_names(text):
        key = str(name).lower().strip()
        if len(key) < 3 or key in _ENTITY_NOISE or key in seen:
            continue
        seen.add(key)
        names.append(str(name).strip())
    return names


def query_canonical_entity_tokens(text: str) -> frozenset[str]:
    """Canonical biblical names the query is about, without Whisper aliases."""
    return frozenset(name.lower() for name in retrieval_bible_names(text))


def _safe_whisper_aliases(name: str) -> tuple[str, ...]:
    return tuple(
        alias
        for alias in _WHISPER_NAME_ALIASES.get((name or "").lower(), ())
        if alias and alias not in _NOISY_WHISPER_ALIASES
    )


def query_entity_tokens(text: str) -> frozenset[str]:
    """Biblical names plus safe Whisper aliases (excludes able/cane)."""
    expanded: set[str] = set()
    for name in retrieval_bible_names(text):
        key = name.lower()
        expanded.add(key)
        expanded.update(_safe_whisper_aliases(key))
    return frozenset(expanded)


def story_passage_for_query(text: str) -> str:
    names = frozenset(name.lower() for name in retrieval_bible_names(text))
    if not names:
        return ""
    if names in _NAME_PASSAGES:
        return _NAME_PASSAGES[names]
    for key, passage in _NAME_PASSAGES.items():
        if key.issubset(names):
            return passage
    return ""


def query_focus_tokens(text: str) -> frozenset[str]:
    """Distinctive query words used for topical overlap.

    Named Bible-story questions use the character names, not filler like
    \"sermon\" / \"story\" / \"based\" that matches almost every pastoral clip.
    Aliases are resolved at match time so \"able\" is not a focus token.
    """
    entities = query_canonical_entity_tokens(text)
    if entities:
        return entities
    stops = set(_GENERIC_FOCUS_STOPWORDS)
    if looks_like_library_pull(text) or looks_like_topic_sermon(text):
        stops |= _LIBRARY_FOCUS_STOP
        stops |= _OUTLINE_FOCUS_STOP
    return frozenset(
        token.lower()
        for token in keyword_search_query(text).split()
        if len(token) >= 3
        and token.lower() not in stops
        and token.lower() not in {"god", "man", "men", "son", "day", "way"}
    )


def _blob_has_token(hay: str, token: str) -> bool:
    cleaned = (token or "").strip().lower()
    if not cleaned or not hay:
        return False
    if len(cleaned) <= 4:
        return bool(re.search(rf"\b{re.escape(cleaned)}\b", hay))
    return cleaned in hay


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


def _focus_token_in_blob(token: str, hay: str, sibling_tokens: set[str]) -> bool:
    """True when a focus token (or a safe Whisper spelling) appears in the chunk.

    Noisy aliases such as Abel→able only count when a companion name from the
    same query (Cain / Kane) is also in the chunk.
    """
    cleaned = (token or "").strip().lower()
    if not cleaned or not hay:
        return False
    if _blob_has_token(hay, cleaned):
        return True
    companion_surface = {item for item in sibling_tokens if item != cleaned}
    for sibling in list(companion_surface):
        companion_surface.update(_safe_whisper_aliases(sibling))
    for alias in _WHISPER_NAME_ALIASES.get(cleaned, ()):
        if not _blob_has_token(hay, alias):
            continue
        if alias in _NOISY_WHISPER_ALIASES:
            if not any(_blob_has_token(hay, companion) for companion in companion_surface):
                continue
        return True
    return False


def topic_overlap_score(doc: Any, query_tokens: Iterable[str]) -> float:
    tokens = [str(token).lower() for token in query_tokens if str(token).strip()]
    if not tokens:
        return 0.0
    hay = _metadata_search_blob(doc)
    if not hay:
        return 0.0
    token_set = set(tokens)
    hits = sum(1 for token in tokens if _focus_token_in_blob(token, hay, token_set))
    return hits / len(tokens)


def filter_hits_by_topic(
    scored_hits: list[tuple[Any, float]],
    query: str,
    *,
    retrieval_k: int,
) -> list[tuple[Any, float]]:
    """Drop embedding-only matches that share no distinctive query words.

    Vector search is already ANN (not a slow scan). Extra *time* does not help;
    extra *candidates + lexical overlap* does. Named-entity questions keep only
    chunks that mention those names (or Whisper aliases) instead of padding with
    unrelated sermon intros.
    """
    tokens = query_focus_tokens(query)
    entities = query_entity_tokens(query)
    if not tokens or not scored_hits:
        return scored_hits
    ranked = []
    for doc, score in scored_hits:
        overlap = topic_overlap_score(doc, tokens)
        ranked.append((doc, score, overlap))
    on_topic = [(doc, score) for doc, score, overlap in ranked if overlap > 0]
    if entities:
        # A Cain/Abel question with 1–3 true hits should not fall back to 24
        # generic \"sermon\" clips just to fill the quota. If nothing names the
        # people, keep Bible verses only — never April-7 intros / unrelated PDFs.
        if on_topic:
            return on_topic
        return [
            (doc, score)
            for doc, score, _overlap in ranked
            if is_bible_source(metadata_source_hint(doc))
        ]
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
    last_prior = _last_prior_user(current_q, prior)
    prior_focus = keyword_search_query(last_prior) if last_prior else ""
    heading_focus = ""
    if last_prior and prior_ai_texts:
        labels = extract_used_headings(prior_ai_texts, limit=6)
        if labels:
            heading_focus = keyword_search_query(" ".join(labels))

    bible_names = retrieval_bible_names(current_q)
    focus = portable_search_focus(current_q)

    # Follow-ups: search the prior user topic first so "expand week one"
    # still retrieves marriage notes instead of generic "week / point" clips.
    if prior_focus:
        add(prior_focus)
        add(f"Pastor Don Nordin {prior_focus}")
        if heading_focus:
            add(f"{prior_focus} {heading_focus}")
        if focus and focus.lower() != prior_focus.lower():
            add(f"{prior_focus} {focus}")

    if bible_names:
        joined = " ".join(bible_names)
        add(joined)
        add(f"Pastor Don Nordin {joined}")
        passage = story_passage_for_query(current_q)
        if passage:
            add(f"{passage} {joined}")
        aliases = []
        for name in bible_names:
            for alias in _safe_whisper_aliases(name.lower()):
                if alias.lower() != name.lower():
                    aliases.append(alias)
        if aliases:
            add(" ".join(bible_names + aliases))
    elif focus and (not prior_focus or focus.lower() != prior_focus.lower()):
        # Embed the topical core (homosexuality, salvation, …), not
        # "generate a sermon based on …".
        add(focus)
        add(f"Pastor Don Nordin {focus}")

    # Only embed the raw prompt when it already is the topical core.
    if focus and current_q.lower() == focus.lower():
        add(current_q)

    if not last_prior and focus:
        add(f"Pastor Don Nordin {focus}")

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
    # Small already-filtered sets (named-story lexical hits) must not be
    # discarded because a generic intro scored 0.93 and they scored 0.74.
    if len(scored_hits) <= max(6, retrieval_k // 4):
        return scored_hits
    if len(scored_hits) <= retrieval_k and threshold < 0.7:
        return scored_hits
    above = [pair for pair in scored_hits if pair[1] >= threshold]
    min_keep = max(6, retrieval_k // 4)
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

    entity_tokens = query_entity_tokens(query)
    has_video = any(
        not item.is_bible
        and item.is_video
        and (not entity_tokens or item.topic_overlap > 0)
        for item in chunks
    )
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
        if prefer_video is True and entity_tokens and chunk.topic_overlap <= 0:
            return False
        if prefer_video is False and (chunk.is_bible or chunk.is_video):
            return False
        if entity_tokens and not chunk.is_bible and chunk.topic_overlap <= 0:
            return False
        if (
            query
            and not entity_tokens
            and not chunk.is_bible
            and chunk.topic_overlap <= 0
        ):
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
    entity_tokens = query_canonical_entity_tokens(query)
    fill_rows = topical if entity_tokens else topical + rest
    for row in fill_rows:
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
        if entity_tokens and overlap <= 0:
            doc = row[0]
            if doc is None or not is_bible_source(metadata_source_hint(doc)):
                continue
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
            if entity_tokens and overlap <= 0:
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
        if entity_tokens:
            _inject(lambda doc: video_fn(doc) and topic_overlap_score(doc, focus) > 0)
        else:
            _inject(video_fn)

    while len(picked) < min(want, len(by_stem)):
        added = False
        for row in ordered:
            stem = source_stem_key(row[1])
            if stem in picked_stems:
                continue
            if entity_tokens and row[2] <= 0:
                doc = row[0]
                if doc is None or not is_bible_source(metadata_source_hint(doc)):
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
    intent: Optional[str] = None,
    used_headings: Optional[Iterable[str]] = None,
    banned_titles: Optional[Iterable[str]] = None,
) -> str:
    quotes = [item.strip() for item in used_quotes if item and item.strip()]
    verses = [item.strip() for item in used_verses if item and item.strip()]
    headings = [item.strip() for item in (used_headings or []) if item and item.strip()]
    titles = [item.strip() for item in (banned_titles or []) if item and item.strip()]
    resolved = intent or (INTENT_NEW_ANGLE if is_followup else INTENT_NEW_TOPIC)
    lines = ["<uniqueness>"]
    topic = " ".join((prior_user_query or "").split())
    if len(topic) > 160:
        topic = topic[:157] + "..."
    if resolved == INTENT_CLARIFY:
        lines.extend(
            [
                "This is a clarifying follow-up in the SAME chat. Stay on the same pastoral topic.",
                "Only develop the part they asked about. Do not reprint the previous heading or step list.",
            ]
        )
        if topic:
            lines.append(f'Prior user question to stay anchored to: "{topic}"')
    elif resolved in {INTENT_NEW_ANGLE, INTENT_APPLY}:
        lines.extend(
            [
                "This is a follow-up in the SAME pastoral situation. Answer THIS new question.",
                "Do not reuse the previous heading, outline, or step list. Write a new teaching.",
            ]
        )
        if topic:
            lines.append(f'Prior user question (situation only, not the outline to copy): "{topic}"')
    else:
        lines.extend(
            [
                "Each reply must be unique. Do not restate the previous answer, recycle the same outline, "
                "or reuse the same sermon excerpt and verse across turns.",
                "Answer THIS user question with different notes than earlier turns. Draw from more than one "
                "labeled source in REFERENCE NOTES when they fit.",
            ]
        )
    if headings:
        lines.append("Already-used headings / step labels (do not reuse):")
        for heading in headings[:8]:
            lines.append(f"- {heading}")
    if titles:
        lines.append(
            "Do not use these sermon titles or REFERENCE NOTES labels as the answer heading: "
            + ", ".join(titles[:8])
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
