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
# Opening quote with no closer before the line ends — the model often drops the
# closing mark, which used to skip rewrite entirely.
_UNCLOSED_QUOTE_RE = re.compile(r'([\"“])([^\"”\n]{12,}?)(?=\s*(?:\n|$))')
_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)
_DESTROY_STEM_RE = re.compile(r"\bdestroy(?:ed)?\b")

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
    r"|it is written"
    r"|i am crucified with christ"
    r"|my house (?:is|shall be(?: called)?) a house of prayer"
    r"|i am not ashamed of the gospel"
    r"|all things are possible to (?:him|them) who believes"
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
    ("destroyed the works of the devil", "1 John 3:8"),
    ("he destroyed the devil", "1 John 3:8"),
    ("for god so loved the world", "John 3:16"),
    ("the lord is my shepherd", "Psalm 23:1"),
    ("i am the way, the truth", "John 14:6"),
    ("come to me, all you who labor", "Matthew 11:28"),
    ("faith is the substance of things hoped for", "Hebrews 11:1"),
    ("go and sin no more", "John 8:11"),
    ("i will never leave you nor forsake you", "Hebrews 13:5"),
    ("this is my beloved son", "Matthew 3:17"),
    ("all things are possible to him who believes", "Mark 9:23"),
    ("i am crucified with christ", "Galatians 2:20"),
    ("christ liveth in me", "Galatians 2:20"),
    ("gather together and come", "Isaiah 45:20"),
    ("fugitives from the nations", "Isaiah 45:20"),
    ("pray to gods that cannot save", "Isaiah 45:20"),
    ("my house is a house of prayer", "Luke 19:46"),
    ("den of thieves", "Luke 19:46"),
    ("king melchizedek of salem", "Genesis 14:18"),
    ("god most high, creator of heaven", "Genesis 14:19"),
    ("how terrible it will be for you teachers of religious law", "Matthew 23:23"),
    ("you are careful to tithe", "Matthew 23:23"),
    ("you have need of endurance", "Hebrews 10:36"),
    ("i am not ashamed of the gospel", "Romans 1:16"),
    ("now is the accepted time", "2 Corinthians 6:2"),
    ("now is the day of salvation", "2 Corinthians 6:2"),
    ("flourish like the palm tree", "Psalm 92:12"),
    ("god did not send his son into the world to condemn", "John 3:17"),
    ("for this melchizedek", "Hebrews 7:1"),
    ("melchizedek, king of salem", "Hebrews 7:1"),
    ("priest of the most high god", "Hebrews 7:1"),
    ("king of peace", "Hebrews 7:2"),
    ("king of righteousness", "Hebrews 7:2"),
    ("jesus returned in the power of the spirit", "Luke 4:14"),
    ("thy righteousness also, o god", "Psalm 71:19"),
    ("who is like unto thee", "Psalm 71:19"),
    ("i will go in the strength of the lord god", "Psalm 71:16"),
    ("by faith we understand that the entire universe was formed", "Hebrews 11:3"),
    ("worlds were framed by the word of god", "Hebrews 11:3"),
    ("what we now see did not come from anything that can be seen", "Hebrews 11:3"),
)

_VERSE_DUMP_RE = re.compile(
    r"(?i)\b\d{1,3}\s+and said\b|\b(?:verse|v\.)\s*\d+\b|\d{1,3}(?=[A-Z])"
)

_SCRIPTURE_VOICE_RE = re.compile(
    r"(?i)\b(?:"
    r"nkjv|scripture|bible|the lord|jesus(?:\s+christ)?|holy spirit|"
    r"god (?:said|says|spoke)|where the lord|records the lord|"
    r"biblical author"
    r")\b"
)

_SPEECH_VERB_RE = (
    r"(?:also\s+)?(?:teach(?:es)?|emphasizes?|says|said|taught|preach(?:es)?|"
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

_DICTIONARY_RE = re.compile(
    r"(?i)(?:instrument|device|tool)\s+used for(?: moving the bolt)?"
    r"|locking or unlocking something"
    r"|thus locking or unlocking"
)
_SENTENCE_END_RE = re.compile(r"[.!?…]")

SERMON_SCRIPTURE_TAG = (
    "[Scripture cited in this sermon, spoken by the Lord or the biblical author "
    "— not Pastor Don] "
)


def normalize_speaker_text(text: str) -> str:
    folded = (text or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    folded = _MARKUP_RE.sub(" ", folded)
    folded = _PUNCT_RE.sub(" ", folded.lower())
    return _SPACE_RE.sub(" ", folded).strip()


def _fragment_variants(fragment: str) -> tuple[str, ...]:
    """NKJV infinitive vs model past tense (destroy / destroyed)."""
    variants = [fragment]
    if _DESTROY_STEM_RE.search(fragment):
        as_past = _DESTROY_STEM_RE.sub("destroyed", fragment)
        as_base = _DESTROY_STEM_RE.sub("destroy", fragment)
        for item in (as_past, as_base):
            if item not in variants:
                variants.append(item)
    return tuple(variants)


def _text_contains_fragment(folded: str, fragment: str) -> bool:
    return any(item in folded for item in _fragment_variants(fragment))


def looks_like_divine_speech(text: str) -> bool:
    """True for first-person God / Jesus commissioning and covenant speech."""
    sample = text or ""
    if _DIVINE_SPEECH_RE.search(sample):
        return True
    folded = normalize_speaker_text(sample)
    return any(_text_contains_fragment(folded, fragment) for fragment, _ref in _KNOWN_VERSE_FRAGMENTS)


def known_verse_ref(text: str) -> str:
    folded = normalize_speaker_text(text)
    for fragment, ref in _KNOWN_VERSE_FRAGMENTS:
        if _text_contains_fragment(folded, fragment):
            return ref
    return ""


def looks_like_scripture_wording(text: str, bible_corpus: str = "") -> bool:
    """True when the span is a known verse fragment or overlaps retrieved NKJV."""
    if looks_like_divine_speech(text):
        return True
    if known_verse_ref(text):
        return True
    if _VERSE_DUMP_RE.search(text or ""):
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


def looks_like_title_excerpt(text: str) -> bool:
    """True for sermon titles / slide headings quoted as if Pastor Don said them."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return True
    if cleaned.startswith("#"):
        return True
    titled_src = cleaned[:-1].rstrip() if cleaned.endswith(".") else cleaned
    if len(cleaned) <= 80 and not _SENTENCE_END_RE.search(titled_src):
        words = [word for word in re.findall(r"[A-Za-z']+", titled_src)]
        if 2 <= len(words) <= 12:
            titled = sum(1 for word in words if word[:1].isupper())
            if titled >= max(2, len(words) - 1):
                return True
    return False


def looks_like_nonteaching_excerpt(text: str) -> bool:
    """True for dictionary slides, titles, and other non-spoken pastor lines."""
    sample = " ".join((text or "").split())
    if not sample:
        return True
    if _DICTIONARY_RE.search(sample):
        return True
    if re.match(r"(?i)^(intro|title|key|definition)\s*:", sample):
        return True
    return looks_like_title_excerpt(sample)


def is_pastor_own_voice(text: str, *, bible_corpus: str = "") -> bool:
    """False for verses and divine first-person; those must not be Pastor Don quotes."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 12:
        return False
    if looks_like_nonteaching_excerpt(cleaned):
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


_NARRATOR_OR_APOSTLE_REFS = frozenset(
    {
        "Galatians 2:20",
        "1 John 3:8",
        "Genesis 14:18",
        "Genesis 14:19",
        "Hebrews 7:1",
        "Hebrews 7:2",
        "Hebrews 10:36",
        "Hebrews 11:1",
        "2 Corinthians 6:2",
        "Romans 1:16",
        "Luke 4:14",
        "Psalm 92:12",
        "Psalm 71:16",
        "Psalm 71:19",
        "Hebrews 11:3",
    }
)


def scripture_leadin_for(span: str, nkjv_pairs: Iterable[tuple[str, str]]) -> str:
    ref = match_nkjv_ref(span, nkjv_pairs) or known_verse_ref(span)
    lord = looks_like_divine_speech(span) and (not ref or ref not in _NARRATOR_OR_APOSTLE_REFS)
    if lord and ref:
        return f'{ref} (NKJV) records the Lord saying, '
    if lord:
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


def _closed_quote(quoted: str) -> str:
    text = (quoted or "").rstrip()
    if text and text[-1] not in '"”':
        return text + '"'
    return text


def _ranges_overlap(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(not (end <= left or start >= right) for left, right in occupied)


def _iter_quote_matches(text: str) -> list[tuple[int, int, str, str]]:
    """Closed quotes, then pastor-led unclosed quotes that end at a newline."""
    sample = text or ""
    occupied: list[tuple[int, int]] = []
    items: list[tuple[int, int, str, str]] = []

    for match in _UNCLOSED_QUOTE_RE.finditer(sample):
        prefix = sample[: match.start()]
        if _leadin_match(prefix) is None:
            continue
        span = " ".join(match.group(2).split()).strip()
        if len(span) < 12:
            continue
        items.append((match.start(), match.end(), span, _closed_quote(match.group(0))))
        occupied.append((match.start(), match.end()))

    for match in _QUOTE_RE.finditer(sample):
        if _ranges_overlap(match.start(), match.end(), occupied):
            continue
        span = " ".join(match.group(2).split()).strip()
        items.append((match.start(), match.end(), span, match.group(0)))
        occupied.append((match.start(), match.end()))

    items.sort(key=lambda item: item[0])
    return items


def quoted_spans_with_voice(answer: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    text = answer or ""
    for start, _end, span, _quoted in _iter_quote_matches(text):
        found.append((span, quoted_span_voice(text[:start])))
    return found


def pastor_attributed_quotes(answer: str) -> list[tuple[str, str]]:
    """Return (quote, lead-in) pairs wrapped as Pastor Don / he-teaches speech."""
    text = answer or ""
    found: list[tuple[str, str]] = []
    for start, _end, span, _quoted in _iter_quote_matches(text):
        lead = _leadin_match(text[:start])
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
    for start, end, span, quoted in _iter_quote_matches(text):
        prefix = text[:start]
        lead = _leadin_match(prefix)
        if lead is None:
            continue
        if not looks_like_scripture_wording(span, bible_corpus):
            continue
        window = _clause_tail(prefix)
        abs_start = start - len(window) + lead.start()
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
        pieces.append(quoted)
        cursor = end
        changed = True
    if not changed:
        return drop_nonteaching_pastor_wraps(text)
    pieces.append(text[cursor:])
    cleaned = "".join(pieces)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return drop_nonteaching_pastor_wraps(cleaned.strip())


def drop_nonteaching_pastor_wraps(answer: str) -> str:
    """Remove Pastor Don wraps that are titles, dictionary slides, or empty quotes."""
    text = answer or ""
    if not text:
        return text
    pieces: list[str] = []
    cursor = 0
    changed = False
    for start, end, span, _quoted in _iter_quote_matches(text):
        if not looks_like_nonteaching_excerpt(span):
            continue
        prefix = text[:start]
        lead = _leadin_match(prefix)
        if lead is None:
            continue
        window = _clause_tail(prefix)
        abs_start = start - len(window) + lead.start()
        if abs_start < cursor:
            continue
        pieces.append(text[cursor:abs_start])
        cursor = end
        while cursor < len(text) and text[cursor] in " \t.":
            cursor += 1
        changed = True
    if not changed:
        cleaned = text
    else:
        pieces.append(text[cursor:])
        cleaned = "".join(pieces)
    cleaned = re.sub(
        r'(?i)\s*Pastor Don(?: and Susan)?(?: Nordin)?(?: also)? teach(?:es)?,?\s*(?:["“]["”]?)?\s*$',
        "",
        cleaned,
    )
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
