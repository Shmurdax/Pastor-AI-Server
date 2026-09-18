"""Retrieve Don/Susan theses, bind them as required content, and check coverage.

Tone stays generic pastoral English. The claims are the doctrine and outline.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .chat_retrieval import chunk_text, is_bible_source, looks_like_library_pull, metadata_source_hint
from .grounding import normalize_grounding_text
from .quote_chunking import extract_quote_spans, spoken_text_without_timestamps, split_sentences

_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_CLAIM_MAX_CHARS = 280
_CLAIM_MIN_CHARS = 24
_DEFAULT_LIMIT = 6
_CONTRAST_RE = re.compile(
    r"\b("
    r"not just|rather than|only if|only indicative|same power|"
    r"fool'?s paradise|come let us|instead of|but the|"
    r"do not|don't|cannot|can't"
    r")\b",
    re.IGNORECASE,
)

# Topic words we still want when matching a user question, even though they are
# too generic to identify a distinctive Don thesis on their own.
_QUERY_TOPIC_WORDS = frozenset(
    {
        "faith",
        "hope",
        "love",
        "loving",
        "patience",
        "prayer",
        "barriers",
        "alcohol",
        "church",
        "lord",
        "god",
        "jesus",
        "christ",
        "holy",
        "spirit",
        "bible",
        "scripture",
        "gospel",
        "grace",
        "worship",
        "gift",
        "gifts",
        "altar",
        "anointing",
        "tithe",
        "tithing",
        "marriage",
        "covenant",
        "tongues",
        "baptism",
        "giving",
    }
)
# Words almost every sermon uses. Overlap on these alone must not make a
# Community / harvest sentence a required point for "why this church…".
_WEAK_QUERY_WORDS = frozenset(
    {
        "faith",
        "hope",
        "love",
        "loving",
        "prayer",
        "church",
        "churches",
        "lord",
        "god",
        "jesus",
        "christ",
        "holy",
        "spirit",
        "bible",
        "scripture",
        "gospel",
        "grace",
        "worship",
        "gift",
        "gifts",
        "christian",
        "christians",
        "life",
        "lives",
        "people",
    }
)
_MEMOIR_RE = re.compile(
    r"(?i)\b("
    r"i grew up|when i was \d+|i accepted christ|"
    r"my parents(?:,| were)|i began preaching|"
    r"working on a sermon that late"
    r")\b"
)
_TESTIMONY_QUERY_RE = re.compile(
    r"(?i)\b(testimony|biography|childhood|grew up|your story|"
    r"pastor don'?s (?:life|story)|parents)\b"
)

# Common English + generic Christian words. Distinctive Don content must survive this list.
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this",
        "these", "those", "to", "of", "in", "on", "for", "from", "with", "without",
        "as", "at", "by", "into", "onto", "over", "under", "about", "above", "after",
        "before", "between", "through", "during", "because", "while", "when", "where",
        "which", "who", "whom", "whose", "what", "why", "how", "not", "no", "nor",
        "so", "too", "very", "just", "also", "even", "still", "only", "own", "same",
        "other", "another", "each", "every", "all", "any", "both", "few", "more",
        "most", "some", "such", "is", "are", "was", "were", "be", "been", "being",
        "am", "do", "does", "did", "done", "doing", "have", "has", "had", "having",
        "will", "would", "shall", "should", "can", "could", "may", "might", "must",
        "i", "we", "you", "he", "she", "it", "they", "me", "us", "him", "her", "them",
        "my", "our", "your", "his", "its", "their", "mine", "ours", "yours", "theirs",
        "pastor", "don", "susan", "nordin", "nordins", "said", "says", "teach",
        "teaches", "taught", "teaching", "preach", "preaches", "preached",
        "god", "lord", "jesus", "christ", "holy", "spirit", "bible", "scripture",
        "scriptures", "church", "churches", "christian", "christians", "faith",
        "people", "person", "life", "lives", "way", "ways", "thing", "things",
        "time", "times", "today", "now", "let", "lets", "need", "needs", "needed",
        "want", "wants", "like", "make", "makes", "come", "comes", "go", "goes",
        "know", "knows", "see", "sees", "say", "says", "get", "gets", "give",
        "gives", "take", "takes", "one", "two", "first", "second", "third",
        "point", "points", "week", "topic", "topics", "note", "notes",
        "verse", "verses", "word", "words", "amen", "hallelujah",
    }
)


def _metadata(doc: Any) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def _is_bible_doc(doc: Any) -> bool:
    meta = _metadata(doc)
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    return is_bible_source(metadata_source_hint(doc) or str(meta.get("source") or ""))


def _clip_claim(text: str) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = _MARKUP_RE.sub(" ", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip(" \"“”'")
    if len(cleaned) <= _CLAIM_MAX_CHARS:
        return cleaned
    return cleaned[: _CLAIM_MAX_CHARS - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def claim_content_tokens(text: str) -> list[str]:
    words = normalize_grounding_text(text).split()
    return [word for word in words if word not in _STOP and len(word) >= 4]


def query_topic_tokens(query: str) -> set[str]:
    """Content tokens from the user question, keeping faith/love/Lord and similar."""
    words = normalize_grounding_text(query).split()
    kept: set[str] = set()
    for word in words:
        if len(word) < 4:
            continue
        if word in _STOP and word not in _QUERY_TOPIC_WORDS:
            continue
        kept.add(word)
    return kept


def distinctive_query_tokens(query_tokens: Iterable[str]) -> set[str]:
    """Query words that are not generic Christian vocabulary (church/love/spirit)."""
    return {
        str(token).lower()
        for token in query_tokens
        if str(token).strip() and str(token).lower() not in _WEAK_QUERY_WORDS
    }


def claim_matches_query(claim: str, query_tokens: set[str]) -> bool:
    if not query_tokens:
        return True
    claim_words = set(normalize_grounding_text(claim).split())
    distinctive = distinctive_query_tokens(query_tokens)
    if distinctive:
        return bool(distinctive & claim_words)
    return bool(query_tokens & claim_words)


def _looks_like_memoir(claim: str) -> bool:
    return bool(_MEMOIR_RE.search(claim or ""))


def _score_claim(claim: str, query_tokens: set[str]) -> int:
    tokens = claim_content_tokens(claim)
    if not tokens:
        return -1
    claim_words = set(normalize_grounding_text(claim).split())
    distinctive = distinctive_query_tokens(query_tokens)
    dist_overlap = sum(1 for token in distinctive if token in claim_words)
    overlap = sum(1 for token in query_tokens if token in claim_words)
    contrast = 6 if _CONTRAST_RE.search(claim) else 0
    return dist_overlap * 6 + overlap * 3 + min(len(tokens), 8) + contrast


def extract_teaching_claims(
    docs: Iterable[Any] | None,
    *,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[str]:
    """Sentence-sized Don/Susan theses from retrieved sermon notes, not Bible."""
    query_tokens = query_topic_tokens(query)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    allow_memoir = bool(_TESTIMONY_QUERY_RE.search(query or ""))

    def add(raw: str, *, bonus: int = 0) -> None:
        claim = _clip_claim(raw)
        if len(claim) < _CLAIM_MIN_CHARS:
            return
        if len(claim_content_tokens(claim)) < 2 and bonus <= 0:
            return
        if _looks_like_memoir(claim) and not allow_memoir:
            return
        key = normalize_grounding_text(claim)
        if len(key) < 16 or key in seen:
            return
        seen.add(key)
        scored.append((_score_claim(claim, query_tokens) + bonus, claim))

    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        kind = str(meta.get("chunk_kind") or "").lower()
        if "overview" in kind:
            continue
        stored = str(meta.get("quote_text") or "").strip()
        if stored:
            for part in stored.split(" | "):
                add(part, bonus=4)
        body = spoken_text_without_timestamps(chunk_text(doc))
        if not body:
            continue
        for span in extract_quote_spans(body):
            add(span, bonus=2)
        for sentence in split_sentences(body):
            add(sentence)

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    ranked = [claim for score, claim in scored if score >= 0]
    if query_tokens and ranked and not looks_like_library_pull(query):
        topical = [claim for claim in ranked if claim_matches_query(claim, query_tokens)]
        if topical:
            ranked = topical
    return ranked[: max(1, limit)]


def format_teaching_claims_block(claims: Iterable[str]) -> str:
    points = [item.strip() for item in claims if item and item.strip()]
    if not points:
        return ""
    lines = [
        "<required_teaching_points>",
        "Use a clear, generic Christian pastoral tone. Do not imitate Pastor Don's or Susan's speaking style.",
        "The numbered points are the retrieved teaching content for this answer. Teach them in your own words.",
        "In your own words means the same thesis with different wording. Keep the contrast "
        "(the not / only if / same power / rather than). Do not keep a story or illustration "
        "and teach a different point with it.",
        "They are the outline and the doctrine. Do not replace them with generic Christian topics "
        "(for example a communication or conflict-resolution seminar) unless those topics appear below.",
        "If part of the user's question is not covered by these points, say the retrieved teaching does not address that part.",
    ]
    for index, claim in enumerate(points, start=1):
        lines.append(f"{index}. {claim}")
    lines.append("</required_teaching_points>")
    return "\n".join(lines) + "\n"


def claim_is_covered(claim: str, answer: str) -> bool:
    tokens = claim_content_tokens(claim)
    if len(tokens) < 2:
        return True
    answer_norm = normalize_grounding_text(answer)
    if not answer_norm:
        return False
    answer_words = set(answer_norm.split())
    hits = sum(1 for token in tokens if token in answer_words)
    if len(tokens) >= 4:
        for index in range(len(tokens) - 2):
            if all(token in answer_words for token in tokens[index : index + 3]):
                return True
        later = tokens[len(tokens) // 2 :]
        for index in range(len(later) - 1):
            if later[index] in answer_words and later[index + 1] in answer_words and hits >= 3:
                return True
        return False
    phrases = [" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1)]
    if any(phrase in answer_norm for phrase in phrases):
        return True
    return hits >= min(2, len(tokens))


def uncovered_claims(answer: str, claims: Iterable[str]) -> list[str]:
    return [claim for claim in claims if claim and not claim_is_covered(claim, answer)]


def repairable_claims(answer: str, claims: Iterable[str], *, query: str = "") -> list[str]:
    """Missed claims that still belong to the user's question (skip memoir / off-topic)."""
    missing = uncovered_claims(answer, claims)
    query_tokens = query_topic_tokens(query)
    if not query_tokens:
        return missing
    return [claim for claim in missing if claim_matches_query(claim, query_tokens)]


def claim_repair_steer(missing: Iterable[str]) -> str:
    points = [item.strip() for item in missing if item and item.strip()]
    lines = [
        "The draft on screen already answers the user. Do not restart it.",
        "Do not say Certainly, Let's continue, or Teaching Points.",
        "Do not paste a numbered list. Write 1-2 ordinary paragraphs, then stop on a complete sentence.",
        "Keep a generic Christian pastoral tone. Do not imitate Pastor Don's speaking style.",
        "Only add a missed point if it actually answers the user's question. Skip autobiography, jokes, and unrelated notes.",
        "If none of the points below answer the user's question, reply with nothing.",
        "Keep the same thesis, including the contrast. Do not keep the illustration and change what it teaches.",
    ]
    for index, claim in enumerate(points[:_DEFAULT_LIMIT], start=1):
        lines.append(f"{index}. {claim}")
    return "\n".join(lines)


def claim_repair_token_budget(*, completion_tokens: int, limit: int = 384) -> int:
    completion = int(completion_tokens or 0)
    if completion <= 0:
        return 0
    return min(completion, max(128, int(limit)))
