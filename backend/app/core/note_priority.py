"""Rank sermon sentences as teaching ideas vs deck junk, stats, or KJV fragments."""

from __future__ import annotations

import re

from .quote_chunking import split_sentences

_KJV_DICT_RE = re.compile(
    r"\b(?:ye|thou|thee|thy|thine|hath|hast|doth|dost|saith|waxen|shalt|unto)\b",
    re.IGNORECASE,
)
_PACKED_KJV_RE = re.compile(r"\d+\s*Ye\b")
_WINE_FRAGMENT_RE = re.compile(
    r"\bwine and strong drink\b|\bstrong drink is a brawler\b|\bwine is a mocker\b",
    re.IGNORECASE,
)
_DECK_RE = re.compile(
    r"(?i)("
    r"leave on the screen|place on the screen|do not remove|"
    r"click to add|speaker notes|next slide"
    r")"
)
_ALLCAPS_PAREN_RE = re.compile(r"\([A-Z][A-Z0-9 ,.'’-]{8,}\)")
_STATS_RE = re.compile(
    r"(?i)("
    r"\d[\d,]*\s*(?:%|percent)|"
    r"\$\s*\d|"
    r"\d[\d,]*\s*(?:billion|million)|"
    r"every\s+\d+\s+minutes|"
    r"alcohol-related (?:deaths|crashes|beverages)"
    r")"
)
_TEACHING_RE = re.compile(
    r"(?i)\b("
    r"should|cannot|can't|must|boundary|abstinence|abstain|"
    r"refuse|sin|sinner|lifestyle|never|only acceptable|"
    r"covenant|not a contract|approve|stone|fornicator|"
    r"natural law|stand firmly"
    r")\b"
)
_VICE_WORDS_RE = re.compile(
    r"(?i)\b("
    r"unrighteousness|immorality|wickedness|covetousness|maliciousness|"
    r"whisperers|backbiters|boasters|undiscerning|untrustworthy|"
    r"unloving|unforgiving|unmerciful|evil-mindedness|"
    r"inventors of evil"
    r")\b"
)
_APPLICATION_KEEP_RE = re.compile(
    r"(?i)\b("
    r"must|should|love|stand|refuse|acceptable|boundary|"
    r"approve|stone|natural law"
    r")\b"
)


def looks_like_kjv_diction(text: str) -> bool:
    """True for KJV/NKJV wording even without a book-and-chapter citation."""
    blob = text or ""
    if _PACKED_KJV_RE.search(blob):
        return True
    if re.search(r"wine is a mocker|strong drink is a brawler", blob, re.I):
        return True
    if _WINE_FRAGMENT_RE.search(blob) and (
        len(blob) < 120 or not _TEACHING_RE.search(blob)
    ):
        return True
    archaic = _KJV_DICT_RE.findall(blob)
    return len(archaic) >= 2


def looks_like_deck_junk(text: str) -> bool:
    blob = text or ""
    if _DECK_RE.search(blob):
        return True
    return bool(_ALLCAPS_PAREN_RE.search(blob)) and len(blob) < 220


def looks_like_stat_slide(text: str) -> bool:
    blob = text or ""
    if not _STATS_RE.search(blob):
        return False
    return not _TEACHING_RE.search(blob)


def looks_like_vice_catalog(text: str) -> bool:
    """True for Romans-1 style sin lists, not Don's application of them."""
    blob = text or ""
    if blob.count(",") < 4:
        return False
    if len(_VICE_WORDS_RE.findall(blob)) < 3:
        return False
    return not _APPLICATION_KEEP_RE.search(blob)


def thesis_sentence_score(text: str) -> float:
    """Higher is a complete teaching sentence; junk and Bible fragments score low."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 40 or len(cleaned) > 400:
        return -1.0
    if looks_like_deck_junk(cleaned) or looks_like_kjv_diction(cleaned):
        return -1.0
    if looks_like_vice_catalog(cleaned):
        return -1.0
    if looks_like_stat_slide(cleaned):
        return -0.5
    score = 0.5
    if _TEACHING_RE.search(cleaned):
        score += 1.5
    if 60 <= len(cleaned) <= 280:
        score += 0.4
    if cleaned[:1].isupper() and cleaned.rstrip()[-1:] in ".!?":
        score += 0.2
    return score


def chunk_thesis_score(text: str) -> float:
    """Best teaching-sentence score inside a retrieval window."""
    best = -1.0
    body = " ".join((text or "").split())
    if not body:
        return best
    sentences = split_sentences(body) or [body]
    for sentence in sentences:
        best = max(best, thesis_sentence_score(sentence))
    if best < 0 and _TEACHING_RE.search(body) and not looks_like_kjv_diction(body):
        return 0.3
    return best
