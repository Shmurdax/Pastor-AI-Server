"""Keep God / Scripture / Pastor Don voices distinct in chat replies.

Sermon notes mix pastoral speech with verses Pastor Don is citing. The model is
also required to wrap two excerpts as Pastor Don quotes, so first-person
God-speech (Jeremiah 1:5, John 14:6, etc.) is an easy mis-fill. Detection and
rewrite live here so grounding, retrieval labels, and finalization share one
rule set.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from .bible_refs import parse_verse_refs
from .quote_chunking import split_sentences

_QUOTE_RE = re.compile(r'([\"“])(.{12,400}?)([\"”])')
_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)

_DIVINE_SPEECH_RE = re.compile(
    r"(?i)\b(?:"
    r"before (?:i formed you|you were (?:born|formed))"
    r"|i (?:knew you before|formed you in the womb)"
    r"|i (?:sanctified|ordained) you"
    r"|i appointed you as my"
    r"|my (?:spokesman|prophet) (?:to|unto) the (?:world|nations)"
    r"|thus says the lord"
    r"|says the lord(?: god)?"
    r"|the lord said(?: to me)?"
    r"|i am (?:the (?:lord|way|resurrection|good shepherd|bread of life|light of the world|true vine)|who i am)"
    r"|before abraham was,\s*i am"
    r"|this is my beloved son"
    r"|i will never leave you nor forsake you"
    r"|come to me, all you who labor"
    r"|let there be light"
    r")"
)

_KNOWN_VERSE_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("before you were born, i sanctified you", "Jeremiah 1:5"),
    ("before i formed you in the womb", "Jeremiah 1:5"),
    ("before i formed you", "Jeremiah 1:5"),
    ("i sanctified you and appointed you", "Jeremiah 1:5"),
    ("prophet to the nations", "Jeremiah 1:5"),
    ("destroy the works of the devil", "1 John 3:8"),
    ("for god so loved the world", "John 3:16"),
    ("the lord is my shepherd", "Psalm 23:1"),
    ("i am the way, the truth", "John 14:6"),
    ("come to me, all you who labor", "Matthew 11:28"),
    ("faith is the substance of things hoped for", "Hebrews 11:1"),
    ("go and sin no more", "John 8:11"),
    ("i will never leave you nor forsake you", "Hebrews 13:5"),
    ("this is my beloved son", "Matthew 3:17"),
)

_SCRIPTURE_VOICE_RE = re.compile(
    r"(?i)\b(?:"
    r"nkjv|scripture|bible|the lord|jesus(?:\s+christ)?|holy spirit|"
    r"god (?:said|says|spoke)|where the lord|records the lord|"
    r"biblical author"
    r")\b"
)

_SPEECH_VERB_RE = (
    r"(?:also\s+)?(?:teaches?|emphasizes?|says|said|taught|preaches?|"
    r"explains?|declares?|reminds?|quotes?|highlights?|adds?|notes?|"
    r"continues?|underscores?|affirms?)"
)
_PASTOR_NAME_RE = (
    r"pastor\s+don(?:\s+and\s+susan)?(?:\s+nordin)?(?:\s+and\s+susan(?:\s+nordin)?)?"
    r"|pastor\s+susan(?:\s+nordin)?"
)
_LEADIN_RE = re.compile(
    rf"(?i)(?:(?:additionally|similarly|moreover|furthermore|also|likewise)[, ]+)?"
    rf"(?:{_PASTOR_NAME_RE}|he|she|they)"
    rf"(?:\s+\w+){{0,8}}?\s+{_SPEECH_VERB_RE}"
    rf"(?:\s+that)?"
    rf"[,:\s]*$"
)
_OPENER_RE = re.compile(
    r"(?i)^(additionally|similarly|moreover|furthermore|also|likewise)[, ]+"
)

SERMON_SCRIPTURE_TAG = (
    "[Scripture cited in this sermon, spoken by the Lord or the biblical author "
    "— not Pastor Don] "
)


def normalize_speaker_text(text: str) -> str:
    folded = (text or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    folded = _MARKUP_RE.sub(" ", folded)
    folded = _PUNCT_RE.sub(" ", folded.lower())
    return _SPACE_RE.sub(" ", folded).strip()


def looks_like_divine_speech(text: str) -> bool:
    """True for first-person God / Jesus commissioning and covenant speech."""
    sample = text or ""
    if _DIVINE_SPEECH_RE.search(sample):
        return True
    folded = normalize_speaker_text(sample)
    return any(fragment in folded for fragment, _ref in _KNOWN_VERSE_FRAGMENTS)


def known_verse_ref(text: str) -> str:
    folded = normalize_speaker_text(text)
    for fragment, ref in _KNOWN_VERSE_FRAGMENTS:
        if fragment in folded:
            return ref
    return ""


def looks_like_scripture_wording(text: str, bible_corpus: str = "") -> bool:
    """True when the span is a known verse fragment or overlaps retrieved NKJV."""
    if looks_like_divine_speech(text):
        return True
    if known_verse_ref(text):
        return True
    hay = normalize_speaker_text(bible_corpus)
    needle = normalize_speaker_text(text)
    if not needle or len(needle) < 18 or not hay:
        return False
    if needle in hay:
        return True
    words = needle.split()
    if len(words) >= 8:
        probe = " ".join(words[1:-1] if len(words) > 10 else words)
        if len(probe) >= 24 and probe in hay:
            return True
    return False


def is_pastor_own_voice(text: str, *, bible_corpus: str = "") -> bool:
    """False for verses and divine first-person; those must not be Pastor Don quotes."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 12:
        return False
    if looks_like_scripture_wording(cleaned, bible_corpus):
        return False
    if parse_verse_refs(cleaned[:400]) and looks_like_divine_speech(cleaned):
        return False
    return True


def annotate_scripture_in_sermon(text: str) -> str:
    """Label God-speech / famous verses inside a sermon note for the model."""
    sample = (text or "").strip()
    if not sample:
        return sample
    sentences = split_sentences(sample) or [sample]
    labeled: list[str] = []
    for sentence in sentences:
        if looks_like_divine_speech(sentence) or known_verse_ref(sentence):
            if sentence.startswith(SERMON_SCRIPTURE_TAG.strip()):
                labeled.append(sentence)
            else:
                labeled.append(SERMON_SCRIPTURE_TAG + sentence)
        else:
            labeled.append(sentence)
    return " ".join(labeled)


def match_nkjv_ref(span: str, nkjv_pairs: Iterable[tuple[str, str]]) -> str:
    needle = normalize_speaker_text(span)
    if not needle:
        return ""
    best_ref = ""
    best_len = 0
    for ref, wording in nkjv_pairs or []:
        hay = normalize_speaker_text(wording)
        if not hay:
            continue
        if needle in hay or hay in needle:
            if len(hay) > best_len:
                best_ref = str(ref or "").strip()
                best_len = len(hay)
            continue
        words = needle.split()
        if len(words) >= 8:
            probe = " ".join(words[1:-1] if len(words) > 10 else words)
            if len(probe) >= 24 and probe in hay and len(hay) > best_len:
                best_ref = str(ref or "").strip()
                best_len = len(hay)
    return best_ref


def scripture_leadin_for(span: str, nkjv_pairs: Iterable[tuple[str, str]]) -> str:
    ref = match_nkjv_ref(span, nkjv_pairs) or known_verse_ref(span)
    divine = looks_like_divine_speech(span)
    if divine and ref:
        return f'{ref} (NKJV) records the Lord saying, '
    if divine:
        return "Scripture records the Lord saying, "
    if ref:
        return f'{ref} (NKJV) says, '
    return "Scripture says, "


def _clause_tail(prefix: str, *, limit: int = 100) -> str:
    """Last short clause before a quotation — avoids matching an earlier 'he said'."""
    window = (prefix or "")[-limit:]
    for sep in (". ", "! ", "? ", "\n"):
        idx = window.rfind(sep)
        if idx >= 0:
            window = window[idx + len(sep) :]
            break
    return window


def _leadin_match(prefix: str) -> Optional[re.Match[str]]:
    window = _clause_tail(prefix)
    found: Optional[re.Match[str]] = None
    for match in _LEADIN_RE.finditer(window):
        found = match
    if found is None:
        return None
    snippet = found.group(0)
    if _SCRIPTURE_VOICE_RE.search(snippet) or parse_verse_refs(snippet):
        return None
    return found


def quoted_span_voice(prefix: str) -> str:
    """Classify the speaker wrapping a quotation: scripture, pastor, or unknown."""
    tail = _clause_tail(prefix, limit=140)
    if _SCRIPTURE_VOICE_RE.search(tail) or parse_verse_refs(tail):
        return "scripture"
    if _leadin_match(prefix) is not None:
        return "pastor"
    return "unknown"


def quoted_spans_with_voice(answer: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    text = answer or ""
    for match in _QUOTE_RE.finditer(text):
        span = " ".join(match.group(2).split()).strip()
        found.append((span, quoted_span_voice(text[: match.start()])))
    return found


def pastor_attributed_quotes(answer: str) -> list[tuple[str, str]]:
    """Return (quote, lead-in) pairs wrapped as Pastor Don / he-teaches speech."""
    text = answer or ""
    found: list[tuple[str, str]] = []
    for match in _QUOTE_RE.finditer(text):
        span = " ".join(match.group(2).split()).strip()
        prefix = text[: match.start()]
        lead = _leadin_match(prefix)
        if lead is None:
            continue
        found.append((span, lead.group(0)))
    return found


def rewrite_misattributed_quotes(
    answer: str,
    *,
    bible_corpus: str = "",
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str:
    """Rewrite pastor/he lead-ins that wrap Scripture or the Lord's words."""
    text = answer or ""
    if not text:
        return text
    pairs = list(nkjv_pairs or [])
    pieces: list[str] = []
    cursor = 0
    changed = False
    for match in _QUOTE_RE.finditer(text):
        span = " ".join(match.group(2).split()).strip()
        prefix = text[: match.start()]
        lead = _leadin_match(prefix)
        if lead is None:
            continue
        if not looks_like_scripture_wording(span, bible_corpus):
            continue
        window = _clause_tail(prefix)
        abs_start = match.start() - len(window) + lead.start()
        if abs_start < cursor:
            continue
        opener = ""
        opener_match = _OPENER_RE.match(lead.group(0).strip())
        if opener_match:
            opener = opener_match.group(0)
            if opener and not opener.endswith(" "):
                opener = opener.rstrip(", ") + ", "
        replacement = opener + scripture_leadin_for(span, pairs)
        pieces.append(text[cursor:abs_start])
        pieces.append(replacement)
        pieces.append(match.group(0))
        cursor = match.end()
        changed = True
    if not changed:
        return text
    pieces.append(text[cursor:])
    cleaned = "".join(pieces)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
