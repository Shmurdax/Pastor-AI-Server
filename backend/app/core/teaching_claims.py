"""Retrieve Don/Susan theses, bind them as required content, and check coverage.

Tone stays generic pastoral English. The claims are the doctrine and outline.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Iterable

from .chat_retrieval import chunk_text, is_bible_source, metadata_source_hint
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

_LOCAL_EVENT_RE = re.compile(
    r"\b("
    r"empowerment\s+conference|"
    r"(?!the|this|that|our|a|an)\w{4,}\s+conference|"
    r"camp\s+meeting|heart\s+for\s+the\s+house|"
    r"this\s+(?:past\s+)?(?:sunday|wednesday|friday|weekend)|"
    r"last\s+(?:sunday|week|night|wednesday)|"
    r"vacation\s+bible\s+school|\bvbs\b"
    r")\b",
    re.IGNORECASE,
)
_FAMILY_STORY_RE = re.compile(
    r"\b("
    r"foster(?:ed|ing)?|adopt(?:ed|ing|ion)|"
    r"a\s+couple\s+in\s+(?:the|our)\s+church|"
    r"extra\s+teenagers|enlarged\s+their\s+hearts"
    r")\b",
    re.IGNORECASE,
)
_NAME_PAIR_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+and\s+([A-Z][a-z]{2,})\b")
_THEOLOGICAL_NAME_WORDS = frozenset(
    {
        "faith", "love", "hope", "grace", "truth", "works", "law", "gospel",
        "spirit", "word", "church", "marriage", "husband", "wife", "father",
        "son", "mother", "daughter", "lord", "god", "jesus", "christ", "holy",
        "bible", "scripture", "heaven", "kingdom", "cross", "blood", "glory",
        "wisdom", "peace", "joy", "mercy", "power", "life", "death", "sin",
        "salvation", "righteousness", "holiness", "prayer", "worship",
    }
)
_ALLOWED_PERSON_NAMES = frozenset(
    {
        "don", "susan", "nordin", "nordins", "pastor", "jesus", "christ",
        "god", "lord", "moses", "abraham", "isaac", "jacob", "joseph",
        "david", "solomon", "elijah", "elisha", "isaiah", "jeremiah",
        "ezekiel", "daniel", "hosea", "joel", "amos", "jonah", "micah",
        "peter", "james", "john", "paul", "timothy", "titus", "barnabas",
        "silas", "stephen", "philip", "mary", "martha", "elizabeth",
        "sarah", "ruth", "esther", "hannah", "nehemiah", "ezra", "noah",
        "adam", "eve", "cain", "abel", "goliath", "samuel", "nathan",
        "matthew", "mark", "luke", "andrew", "thomas", "judas", "simon",
        "pharaoh", "pilate", "herod", "nicodemus", "lazarus", "job",
    }
)
_ALLOWED_NAME_PAIRS = frozenset(
    {
        frozenset({"don", "susan"}),
        frozenset({"cain", "abel"}),
        frozenset({"mary", "martha"}),
        frozenset({"david", "goliath"}),
        frozenset({"adam", "eve"}),
        frozenset({"peter", "john"}),
        frozenset({"paul", "silas"}),
        frozenset({"husband", "wife"}),
        frozenset({"faith", "works"}),
        frozenset({"grace", "truth"}),
        frozenset({"love", "hope"}),
    }
)


def is_local_anecdote(text: str) -> bool:
    """True for local events, named members, or family stories—not portable doctrine."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _LOCAL_EVENT_RE.search(raw):
        return True
    if _FAMILY_STORY_RE.search(raw):
        return True
    for match in _NAME_PAIR_RE.finditer(raw):
        left = match.group(1).lower()
        right = match.group(2).lower()
        pair = frozenset({left, right})
        if pair in _ALLOWED_NAME_PAIRS:
            continue
        if left in _THEOLOGICAL_NAME_WORDS or right in _THEOLOGICAL_NAME_WORDS:
            continue
        if left in _ALLOWED_PERSON_NAMES and right in _ALLOWED_PERSON_NAMES:
            continue
        return True
    return False


def drop_local_anecdote_sentences(text: str) -> str:
    """Keep doctrinal sentences; drop local-event / named-people asides."""
    parts = split_sentences(text)
    if not parts:
        return ""
    kept = [part for part in parts if not is_local_anecdote(part)]
    return " ".join(kept).strip()


def docs_without_local_anecdotes(docs: Iterable[Any] | None) -> list[Any]:
    """Copy retrieved chunks with local-event / named-people sentences removed."""
    cleaned_docs: list[Any] = []
    for doc in docs or []:
        if _is_bible_doc(doc):
            cleaned_docs.append(doc)
            continue
        meta = dict(_metadata(doc))
        stored = str(meta.get("quote_text") or "").strip()
        if stored:
            kept = [
                part.strip()
                for part in stored.split(" | ")
                if part.strip() and not is_local_anecdote(part)
            ]
            meta["quote_text"] = " | ".join(kept)
        body = drop_local_anecdote_sentences(
            spoken_text_without_timestamps(chunk_text(doc))
        )
        if not body and not meta.get("quote_text"):
            continue
        cleaned_docs.append(
            SimpleNamespace(page_content=body or chunk_text(doc), metadata=meta)
        )
    return cleaned_docs


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


def _score_claim(claim: str, query_tokens: set[str]) -> int:
    tokens = claim_content_tokens(claim)
    if not tokens:
        return -1
    overlap = sum(1 for token in tokens if token in query_tokens)
    contrast = 6 if _CONTRAST_RE.search(claim) else 0
    return overlap * 3 + min(len(tokens), 8) + contrast


def extract_teaching_claims(
    docs: Iterable[Any] | None,
    *,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[str]:
    """Sentence-sized Don/Susan theses from retrieved sermon notes, not Bible."""
    query_tokens = set(claim_content_tokens(query))
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(raw: str, *, bonus: int = 0) -> None:
        claim = _clip_claim(raw)
        if len(claim) < _CLAIM_MIN_CHARS:
            return
        if len(claim_content_tokens(claim)) < 2 and bonus <= 0:
            return
        key = normalize_grounding_text(claim)
        if len(key) < 16 or key in seen:
            return
        if is_local_anecdote(claim):
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
    return [claim for score, claim in scored if score >= 0][: max(1, limit)]


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
        "Teach portable doctrine: definitions, levels, purposes, and contrasts. Do not retell local "
        "church events, conferences, campaigns, or named people from the notes unless the user asked "
        "for that story.",
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


def claim_repair_steer(missing: Iterable[str]) -> str:
    points = [item.strip() for item in missing if item and item.strip()]
    lines = [
        "Continue the same teaching without restarting or replacing the draft on screen.",
        "Keep a generic Christian pastoral tone. Do not imitate Pastor Don's speaking style.",
        "You missed these retrieved Pastor Don/Susan teaching points. Teach them now in your own words.",
        "Keep the same thesis, including the contrast. Do not keep the illustration and change what it teaches.",
        "Do not invent a different outline. Do not switch to generic Christian topics that are not listed.",
        "Do not add local events, conferences, or named church members.",
    ]
    for index, claim in enumerate(points[:_DEFAULT_LIMIT], start=1):
        lines.append(f"{index}. {claim}")
    return "\n".join(lines)


def claim_repair_token_budget(*, completion_tokens: int, limit: int = 384) -> int:
    completion = int(completion_tokens or 0)
    if completion <= 0:
        return 0
    return min(completion, max(128, int(limit)))
