"""Stop the model from attributing unmentioned terms to Pastor Don or Susan."""

from __future__ import annotations

import re
from typing import Iterable

_APOS_RE = re.compile(r"[\u2019']s\b")
_QUOTE_RE = re.compile(r"[\"“”']([^\"“”']{3,80})[\"“”']")
_COUNCIL_RE = re.compile(
    r"\b(?:the\s+)?(Council|Synod|Creed|Confession)\s+of\s+[A-Za-z][A-Za-z\-']+",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-']{4,}")
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z\-']{5,}\b")

# Ordinary question words and ministry vocabulary that are not claim-terms.
_STOP = frozenset(
    {
        "about",
        "according",
        "address",
        "addressed",
        "after",
        "again",
        "against",
        "along",
        "already",
        "always",
        "among",
        "another",
        "answer",
        "around",
        "because",
        "before",
        "being",
        "believe",
        "believes",
        "between",
        "bible",
        "biblical",
        "called",
        "christ",
        "christian",
        "christians",
        "church",
        "clearly",
        "could",
        "council",
        "did",
        "does",
        "doing",
        "don",
        "during",
        "every",
        "explain",
        "explains",
        "father",
        "gospel",
        "great",
        "have",
        "having",
        "holy",
        "jesus",
        "language",
        "later",
        "like",
        "lord",
        "mean",
        "meaning",
        "mention",
        "mentioned",
        "nordin",
        "nordins",
        "other",
        "pastor",
        "people",
        "preach",
        "preached",
        "question",
        "really",
        "said",
        "scripture",
        "sermon",
        "sermons",
        "should",
        "something",
        "spirit",
        "susan",
        "teach",
        "teaching",
        "teachings",
        "term",
        "terms",
        "their",
        "there",
        "these",
        "think",
        "thought",
        "those",
        "through",
        "today",
        "toward",
        "under",
        "using",
        "what",
        "when",
        "where",
        "which",
        "while",
        "would",
    }
)


def _fold(text: str) -> str:
    raw = (text or "").replace("\u2019", "'").replace("\u2018", "'")
    raw = _APOS_RE.sub("", raw)
    return raw.casefold()


def distinctive_query_terms(query: str) -> list[str]:
    """Uncommon names/terms the user asked about (e.g. homoousios, Nicaea)."""
    raw = (query or "").replace("\u2019", "'").replace("\u2018", "'")
    found: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        cleaned = _APOS_RE.sub("", (term or "").strip(" .,;:?!"))
        cleaned = cleaned.strip("'\"")
        if len(cleaned) < 5:
            return
        key = cleaned.casefold()
        if key in seen or key in _STOP:
            return
        seen.add(key)
        found.append(cleaned)

    for match in _QUOTE_RE.findall(raw):
        add(match)
    for match in _COUNCIL_RE.finditer(raw):
        add(match.group(0))
        parts = match.group(0).split()
        if parts:
            add(parts[-1])
    for match in _PROPER_RE.finditer(raw):
        add(match.group(0))
    for match in _TOKEN_RE.findall(raw):
        token = match.strip("'")
        if len(token) >= 8:
            add(token)
        elif re.search(r"ousios$|ousia$|hypostasis|filioque|arian", token, re.I):
            add(token)
    return found


def notes_mention_term(notes: str, term: str) -> bool:
    hay = _fold(notes)
    needle = _fold(term)
    if not needle:
        return False
    if needle in hay:
        return True
    words = [w for w in re.split(r"\s+", needle) if w and w not in {"the", "of", "and"}]
    if not words:
        return False
    specific = [w for w in words if w not in {"council", "synod", "creed", "confession"}]
    return all(w in hay for w in (specific or words))


def unmentioned_claim_terms(query: str, notes: str) -> list[str]:
    """Distinctive asked-about terms that do not appear in REFERENCE NOTES."""
    return [term for term in distinctive_query_terms(query) if not notes_mention_term(notes, term)]


def attribution_lock_instruction(query: str, notes: str) -> str:
    """Concrete lock listing terms the notes never use."""
    missing = unmentioned_claim_terms(query, notes)
    if not missing:
        return ""
    listed = ", ".join(f'"{term}"' for term in missing)
    return (
        "<attribution_lock>\n"
        f"REFERENCE NOTES do not mention: {listed}.\n"
        "Do not say Pastor Don Nordin or Susan Nordin taught, used, defined, affirmed, "
        "or gave an opinion on those terms. Lead with that fact in plain language.\n"
        "You may still teach the biblical or historical meaning from NKJV Scripture and "
        "orthodox Christianity, but you must label that as Scripture or church history—"
        "never as their sermon teaching.\n"
        "Forbidden phrasing about those terms: \"According to Pastor Don\", "
        "\"Pastor Don explains\", \"In his teachings\", \"Pastor Don emphasizes\", "
        "\"Pastor Don believed\".\n"
        "Quotes from the notes may be used only for what those notes actually discuss. "
        "Do not quote an unrelated sentence and present it as their view of the missing terms.\n"
        "</attribution_lock>\n"
    )


def attribution_generation_reminder(query: str, notes: str) -> str:
    missing = unmentioned_claim_terms(query, notes)
    if not missing:
        return ""
    listed = ", ".join(f'"{term}"' for term in missing)
    return (
        f"\n\n[Do not attribute {listed} to Pastor Don or Susan. Those words are not "
        "in the notes. Say they have not addressed that wording, then teach from Scripture "
        "without putting the term in their mouth.]"
    )


def docs_matching_asked_terms(docs: Iterable, query: str) -> list:
    """Keep displayed sermon sources that actually mention the asked-about terms.

    If the question has no distinctive terms, return docs unchanged. If it does and
    none of the chunks mention them, return an empty list so the UI does not imply
    those sermons taught the missing term.
    """
    items = list(docs or [])
    terms = distinctive_query_terms(query)
    if not terms:
        return items
    matched = []
    for doc in items:
        text = getattr(doc, "page_content", "") or ""
        if any(notes_mention_term(text, term) for term in terms):
            matched.append(doc)
    return matched
