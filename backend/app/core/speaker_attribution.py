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

_QUOTE_RE = re.compile(
    r'(?:^|(?<=[\s,:(—–]))([\"“])([^\"”]{12,400}?)([\"”])'
)
_SCARE_QUOTE_RE = re.compile(r'(["“])([A-Za-z]{1,10})[\"”]')
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
        r"|i will go to my father"
        r"|you will do greater (?:things|works)"
        r"|greater (?:things|works) than these"
        r"|he will send (?:the )?holy spirit"
        r"|if my people who are called by my name"
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
    ("don't even be angry with your brother", "Matthew 5:22"),
    ("whoever is angry with his brother", "Matthew 5:22"),
    ("if you look at a woman with lust", "Matthew 5:28"),
    ("already committed adultery", "Matthew 5:28"),
    ("recall the former days in which, after you were illuminated", "Hebrews 10:32"),
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
    ("here mortal men receive tithes", "Hebrews 7:8"),
    ("of whom it is witnessed that he lives", "Hebrews 7:8"),
    ("now concerning the collection for the saints", "1 Corinthians 16:1"),
    ("as i have given order to the churches of galatia", "1 Corinthians 16:1"),
    ("upon the first day of the week let every one of you lay by him", "1 Corinthians 16:2"),
    ("as god hath prospered him", "1 Corinthians 16:2"),
    ("jesus returned in the power of the spirit", "Luke 4:14"),
    ("thy righteousness also, o god", "Psalm 71:19"),
    ("who is like unto thee", "Psalm 71:19"),
    ("i will go in the strength of the lord god", "Psalm 71:16"),
    ("by faith we understand that the entire universe was formed", "Hebrews 11:3"),
    ("worlds were framed by the word of god", "Hebrews 11:3"),
    ("what we now see did not come from anything that can be seen", "Hebrews 11:3"),
    ("o daniel, man greatly beloved", "Daniel 10:11"),
    ("understand the words that i speak to you and stand upright", "Daniel 10:11"),
    ("i have now been sent to you", "Daniel 10:11"),
    ("do not fear, daniel", "Daniel 10:12"),
    ("from the first day that you set your heart to understand", "Daniel 10:12"),
    ("if my people who are called by my name", "2 Chronicles 7:14"),
    ("humble themselves and pray and seek my face", "2 Chronicles 7:14"),
    ("turn from their wicked ways", "2 Chronicles 7:14"),
    ("i will hear from heaven", "2 Chronicles 7:14"),
    ("forgive their sin and heal their land", "2 Chronicles 7:14"),
    ("you will do greater things because i will go to my father", "John 14:12"),
    ("you will do greater things", "John 14:12"),
    ("greater works than these he will do", "John 14:12"),
    ("i will go to my father and he will send", "John 14:12"),
    ("i will go to my father", "John 14:12"),
    ("he will send holy spirit to abide in you", "John 14:16"),
    ("he will send the holy spirit", "John 14:16"),
    ("he will give you another helper", "John 14:16"),
    ("faith is the confident assurance that what we hope for is going to happen", "Hebrews 11:1"),
    ("it is the evidence of things we cannot yet see", "Hebrews 11:1"),
    ("having then gifts differing according to the grace", "Romans 12:6"),
    ("let us use them: if prophecy", "Romans 12:6"),
    ("let us hear the conclusion of the whole matter", "Ecclesiastes 12:13"),
    ("fear god and keep his commandments for this is the whole duty of man", "Ecclesiastes 12:13"),
    ("go and marry a prostitute", "Hosea 1:2"),
    ("go, take yourself a wife of harlotry", "Hosea 1:2"),
    ("go take yourself a wife of harlotry", "Hosea 1:2"),
    ("children of harlotry", "Hosea 1:2"),
    ("the land has committed great harlotry", "Hosea 1:2"),
    ("this will illustrate the way my people have been untrue", "Hosea 1:2"),
    ("openly committing adultery against the lord by worshiping other gods", "Hosea 1:2"),
    ("for this reason a man shall leave his father and mother", "Genesis 2:24"),
    ("be joined to his wife, and the two shall become one flesh", "Genesis 2:24"),
    ("the two shall become one flesh", "Genesis 2:24"),
    ("if any man will come after me", "Luke 9:23"),
    ("let him deny himself, and take up his cross", "Luke 9:23"),
    ("a gentle answer turns away wrath", "Proverbs 15:1"),
    ("a soft answer turns away wrath", "Proverbs 15:1"),
    ("a harsh word stirs up anger", "Proverbs 15:1"),
    ("all these things i will give you if you will fall down and worship me", "Matthew 4:9"),
    ("if you will fall down and worship me", "Matthew 4:9"),
    ("fall down and worship me", "Matthew 4:9"),
    ("you are a chosen generation, a royal priesthood", "1 Peter 2:9"),
    ("but you are a chosen generation", "1 Peter 2:9"),
    ("a royal priesthood, a holy nation", "1 Peter 2:9"),
    ("his own special people, that you may proclaim the praises", "1 Peter 2:9"),
    ("called you out of darkness into his marvelous light", "1 Peter 2:9"),
    ("behold the lamb of god which taketh away the sin", "John 1:29"),
    ("behold the lamb of god which takes away the sin", "John 1:29"),
    ("behold! the lamb of god who takes away the sin of the world", "John 1:29"),
    ("behold the lamb of god", "John 1:29"),
    ("he will direct your paths", "Proverbs 3:6"),
    ("he shall direct your paths", "Proverbs 3:6"),
    ("he will direct our steps", "Proverbs 3:6"),
    ("all things work together for good", "Romans 8:28"),
    ("all things to work together for our good", "Romans 8:28"),
    ("knew his wife", "Genesis 4:1"),
    ("marriage is honorable in all, and the bed undefiled", "Hebrews 13:4"),
    ("marriage is honorable among all, and the bed undefiled", "Hebrews 13:4"),
    ("god is enthroned in the praises of his people", "Psalm 22:3"),
    ("enthroned in the praises of his people", "Psalm 22:3"),
    ("enthroned in the praises of israel", "Psalm 22:3"),
    ("while we were yet in our sins christ died", "Romans 5:8"),
    ("while we were yet in our sins", "Romans 5:8"),
    ("while we were still sinners, christ died for us", "Romans 5:8"),
    ("while we were still sinners christ died", "Romans 5:8"),
    ("as far as the east is from the west", "Psalm 103:12"),
    ("so far has he removed our transgressions", "Psalm 103:12"),
    ("hats he removed our transgressions", "Psalm 103:12"),
    ("so far hats he removed our transgressions", "Psalm 103:12"),
    ("throw off the old man", "Ephesians 4:22"),
    ("put off the old man", "Ephesians 4:22"),
    ("put off, concerning your former conduct, the old man", "Ephesians 4:22"),
    ("every great matter they shall bring to you", "Exodus 18:22"),
    ("every small matter they themselves shall judge", "Exodus 18:22"),
)

_VERSE_DUMP_RE = re.compile(
    r"(?i:\b\d{1,3}\s+and said\b|\b(?:verse|v\.)\s*\d+\b)"
    r"|\d{1,3}(?=[A-Z])"
    r"|\b\d{1,3}\s+[A-Z][a-z]"
    r"|\b\d{1,3}\s+(?:or|and)\s+[a-z]"
)

_SCRIPTURE_VOICE_RE = re.compile(
    r"(?i)\b(?:"
    r"nkjv|scripture|bible|"
    r"the lord (?:said|says|speaking)|"
    r"jesus(?:\s+christ)? (?:said|says|taught|teaches|speaking)|"
    r"god (?:said|says|spoke)|"
    r"where the lord|records the lord|"
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
# Direct pastor/Susan wrap of a quotation — does not depend on the previous
# sentence's wording (a nearby "Holy Spirit" used to hide the lead-in).
_PASTOR_WRAPPED_QUOTE_RE = re.compile(
    r"(?is)"
    r"((?:(?:additionally|similarly|moreover|furthermore|also|likewise)[, ]+)?"
    rf"(?:{_PASTOR_NAME_RE}|he|she|they)"
    r"(?:\s+\w+){0,8}?\s+"
    rf"{_SPEECH_VERB_RE}"
    r"(?:\s+that)?"
    r"[,:\s]*)"
    r'(["“])([^"”]{12,400}?)(["”])'
)

_DICTIONARY_RE = re.compile(
    r"(?i)(?:instrument|device|tool)\s+used for(?: moving the bolt)?"
    r"|locking or unlocking something"
    r"|thus locking or unlocking"
    r"|reliance on the integrity"
    r"|confident expectation of something"
    r"|a place set apart or suited for"
    r"|comes from the greek word"
    r"|the greek word"
    r"|rely upon or have confidence in"
)
_GENERIC_PROVERB_RE = re.compile(
    r"(?i)(?:only two things you can be sure of|nothing is certain (?:in this world )?except)\s*,?\s*"
    r"death and taxes"
    r"|\bdeath and taxes\b"
    r"|pain of discipline or the pain of regret"
)
_SLIDE_CHECKBOX_RE = re.compile(r"[□■▪▫☐☑☒]\s*")
_BROKEN_START_RE = re.compile(
    r"^(?:"
    r"[a-z]{1,3}[;:,]"
    r"|ieve\b"
    r"|(?:ecclesi|corint|thessalon|chron|revelat|deuteron|zechari)\b"
    r")"
)
_COMMON_QUOTE_STARTERS = frozenset(
    {
        "a", "and", "as", "but", "do", "don't", "for", "god", "he", "i", "if",
        "in", "it", "let", "lord", "my", "no", "not", "now", "our", "so", "the",
        "then", "there", "this", "that", "to", "we", "when", "you",
    }
)
_BIBLICAL_PASSAGE_RE = re.compile(
    r"(?i)(?:"
    r"(?:and|then)\s+(?:he|she|the\s+(?:angel|man|lord|messenger|one))\s+said\s+to\s+me"
    r"|o\s+(?:daniel|israel|jerusalem|jacob|judah|samuel|gideon|joshua|moses|"
    r"solomon|david|job|jonah|jeremiah|ezekiel|zechariah|nehemiah|theophilus)"
    r"|man greatly beloved"
    r"|do not fear,\s*daniel"
    r"|from the first day that you set your heart to understand"
    r"|understand the words that i (?:speak|am speaking) to you"
    r"|i have now been sent to you"
    r"|if my people who are called by my name"
    r"|you will do greater (?:things|works) because i will go to my father"
    r"|you will do greater (?:things|works)"
    r"|i will go to my father"
    r"|he will send (?:the )?holy spirit"
    r"|greater works than these"
    r"|go(?:\s+and)?\s+(?:marry a prostitute|take(?:\s+yourself)?\s+a\s+wife of harlotry)"
    r"|this will illustrate the way my people have been untrue"
    r"|children of harlotry"
    r"|for this reason a man shall leave his father"
    r"|the two shall become one flesh"
    r"|if any (?:man|person) (?:will|would) come after me"
    r"|fall down and worship me"
    r"|you are a chosen generation"
    r"|a royal priesthood, a holy nation"
    r"|behold(?:!)? the lamb of god"
    r")"
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


def normalize_mixed_inner_quotes(text: str) -> str:
    """Drop scare-quote closers like \"knew” so the real quotation can be parsed."""
    return _SCARE_QUOTE_RE.sub(r"\1\2", text or "")


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
    needles = _fragment_variants(normalize_speaker_text(fragment))
    return any(item in folded for item in needles if item)


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
    if _BIBLICAL_PASSAGE_RE.search(text or ""):
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


def looks_like_broken_excerpt(text: str) -> bool:
    """True for mid-word sermon chunks and truncated book names quoted as teaching."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return True
    if _BROKEN_START_RE.search(cleaned):
        return True
    first = re.match(r"^([a-z]+)\b", cleaned)
    if first:
        word = first.group(1)
        if word not in _COMMON_QUOTE_STARTERS and len(word) <= 3:
            return True
    return False


def looks_like_nonteaching_excerpt(text: str) -> bool:
    """True for dictionary slides, titles, and other non-spoken pastor lines."""
    sample = " ".join((text or "").split())
    if not sample:
        return True
    if _DICTIONARY_RE.search(sample):
        return True
    if _GENERIC_PROVERB_RE.search(sample):
        return True
    if _SLIDE_CHECKBOX_RE.search(sample):
        return True
    if looks_like_broken_excerpt(sample):
        return True
    if re.match(r"(?i)^(intro|title|key|definition)\s*:", sample):
        return True
    if re.match(r"(?i)^to get right\b", sample.strip(" \"“”'")):
        return True
    if re.search(
        r"(?i)pastor don(?: and susan)?(?: nordin)?(?: also)? "
        r"(?:teach(?:es)?|explains?|emphasizes?|says|said)",
        sample,
    ):
        return True
    stripped = sample.strip(" \"“”'")
    if re.match(r"^[A-Z]{4,}\b", stripped) and not _SENTENCE_END_RE.search(stripped):
        return True
    if (stripped.count("…") + stripped.count("...")) >= 2:
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
        if looks_like_scripture_wording(sentence):
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
        "Hebrews 7:8",
        "1 Corinthians 16:1",
        "1 Corinthians 16:2",
        "Hebrews 10:32",
        "Hebrews 10:36",
        "Hebrews 11:1",
        "2 Corinthians 6:2",
        "Romans 1:16",
        "Luke 4:14",
        "Psalm 92:12",
        "Psalm 71:16",
        "Psalm 71:19",
        "Hebrews 11:3",
        "Daniel 10:11",
        "Daniel 10:12",
        "Romans 12:6",
        "Ecclesiastes 12:13",
        "1 Peter 2:9",
        "Matthew 4:9",
        "John 1:29",
        "Proverbs 3:6",
        "Romans 8:28",
        "Genesis 4:1",
        "Hebrews 13:4",
        "Psalm 22:3",
        "Romans 5:8",
        "Psalm 103:12",
        "Ephesians 4:22",
        "Exodus 18:22",
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
    # Include closing-quote ends so "But Holy Spirit?" does not leak into the
    # next Pastor Don / Susan lead-in.
    for sep in ('."', '!"', '?"', '.”', '!”', '?”', ". ", "! ", "? ", "\n"):
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
    """Closed quotes first (they may wrap a newline), then unclosed pastor quotes."""
    sample = text or ""
    occupied: list[tuple[int, int]] = []
    items: list[tuple[int, int, str, str]] = []

    for match in _QUOTE_RE.finditer(sample):
        span = " ".join(match.group(2).split()).strip()
        items.append((match.start(), match.end(), span, match.group(0)))
        occupied.append((match.start(), match.end()))

    for match in _UNCLOSED_QUOTE_RE.finditer(sample):
        if _ranges_overlap(match.start(), match.end(), occupied):
            continue
        prefix = sample[: match.start()]
        if _leadin_match(prefix) is None:
            continue
        span = " ".join(match.group(2).split()).strip()
        if len(span) < 12:
            continue
        items.append((match.start(), match.end(), span, _closed_quote(match.group(0))))
        occupied.append((match.start(), match.end()))

    items.sort(key=lambda item: item[0])
    return items


def quoted_spans_with_voice(answer: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    text = normalize_mixed_inner_quotes(answer or "")
    for start, _end, span, _quoted in _iter_quote_matches(text):
        found.append((span, quoted_span_voice(text[:start])))
    return found


def pastor_attributed_quotes(answer: str) -> list[tuple[str, str]]:
    """Return (quote, lead-in) pairs wrapped as Pastor Don / he-teaches speech."""
    text = normalize_mixed_inner_quotes(answer or "")
    found: list[tuple[str, str]] = []
    for start, _end, span, _quoted in _iter_quote_matches(text):
        lead = _leadin_match(text[:start])
        if lead is None:
            continue
        found.append((span, lead.group(0)))
    return found


_PASTOR_TEACHES_THAT_RE = re.compile(
    r"(?i)((?:Pastor Don(?: and Susan)?(?: Nordin)?|he|she)(?: also)? "
    r"teach(?:es)? that\s+)(.{30,360}?)(?=(?:\s+For instance|\s+Pastor Don|\n\n|\Z))"
)


def _rewrite_unquoted_pastor_scripture(
    text: str,
    *,
    bible_corpus: str = "",
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str:
    """Rewrite 'Pastor Don teaches that <verse>' when the clause is Scripture."""
    pairs = list(nkjv_pairs or [])

    def repl(match: re.Match[str]) -> str:
        span = " ".join(match.group(2).split()).strip()
        if not looks_like_scripture_wording(span, bible_corpus):
            return match.group(0)
        return scripture_leadin_for(span, pairs) + f'"{span}"'

    return _PASTOR_TEACHES_THAT_RE.sub(repl, text or "")


def _split_mixed_scripture_quote(
    lead: str,
    span: str,
    *,
    bible_corpus: str = "",
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str | None:
    """Keep Pastor Don's own sentences; cite only the Scripture clauses as the Lord."""
    parts = split_sentences(span)
    if len(parts) < 2:
        return None
    pastor_parts: list[str] = []
    scripture_parts: list[str] = []
    for part in parts:
        cleaned = " ".join(part.split()).strip()
        if not cleaned or looks_like_nonteaching_excerpt(cleaned):
            continue
        if looks_like_scripture_wording(cleaned, bible_corpus):
            scripture_parts.append(cleaned)
        else:
            pastor_parts.append(cleaned)
    if not pastor_parts or not scripture_parts:
        return None
    bits: list[str] = []
    lead_text = (lead or "").strip()
    if lead_text and not lead_text.endswith(" "):
        lead_text += " "
    if pastor_parts:
        bits.append(f'{lead_text}"{" ".join(pastor_parts)}"')
    for part in scripture_parts:
        bits.append(scripture_leadin_for(part, nkjv_pairs) + f'"{part}"')
    return " ".join(bits)


def _rewrite_pastor_wrapped_scripture(
    text: str,
    *,
    bible_corpus: str = "",
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str:
    """Rewrite or drop Pastor Don / Susan wraps even when nearby prose names Jesus."""
    pairs = list(nkjv_pairs or [])

    def repl(match: re.Match[str]) -> str:
        lead = match.group(1) or ""
        span = " ".join((match.group(3) or "").split()).strip()
        quoted = f'{match.group(2)}{match.group(3)}{match.group(4)}'
        if looks_like_nonteaching_excerpt(span):
            return ""
        mixed = _split_mixed_scripture_quote(
            lead, span, bible_corpus=bible_corpus, nkjv_pairs=pairs
        )
        if mixed is not None:
            return mixed
        if not looks_like_scripture_wording(span, bible_corpus):
            return match.group(0)
        opener = ""
        opener_match = _OPENER_RE.match(lead.strip())
        if opener_match:
            opener = opener_match.group(0)
            if opener and not opener.endswith(" "):
                opener = opener.rstrip(", ") + ", "
        return opener + scripture_leadin_for(span, pairs) + quoted

    return _PASTOR_WRAPPED_QUOTE_RE.sub(repl, text or "")


def rewrite_misattributed_quotes(
    answer: str,
    *,
    bible_corpus: str = "",
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str:
    """Rewrite pastor/he lead-ins that wrap Scripture or the Lord's words."""
    text = normalize_mixed_inner_quotes(answer or "")
    if not text:
        return text
    text = _rewrite_pastor_wrapped_scripture(
        text, bible_corpus=bible_corpus, nkjv_pairs=nkjv_pairs
    )
    pairs = list(nkjv_pairs or [])
    pieces: list[str] = []
    cursor = 0
    changed = False
    for start, end, span, quoted in _iter_quote_matches(text):
        prefix = text[:start]
        lead = _leadin_match(prefix)
        if lead is None:
            continue
        window = _clause_tail(prefix)
        abs_start = start - len(window) + lead.start()
        if abs_start < cursor:
            continue
        mixed = _split_mixed_scripture_quote(
            lead.group(0),
            span,
            bible_corpus=bible_corpus,
            nkjv_pairs=pairs,
        )
        if mixed is not None:
            pieces.append(text[cursor:abs_start])
            pieces.append(mixed)
            cursor = end
            changed = True
            continue
        if not looks_like_scripture_wording(span, bible_corpus):
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
        return drop_nonteaching_pastor_wraps(
            _rewrite_unquoted_pastor_scripture(
                text, bible_corpus=bible_corpus, nkjv_pairs=pairs
            )
        )
    pieces.append(text[cursor:])
    cleaned = "".join(pieces)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return drop_nonteaching_pastor_wraps(
        _rewrite_unquoted_pastor_scripture(
            cleaned.strip(), bible_corpus=bible_corpus, nkjv_pairs=pairs
        )
    )


def drop_nonteaching_pastor_wraps(answer: str) -> str:
    """Remove Pastor Don wraps that are titles, dictionary slides, or empty quotes."""
    text = normalize_mixed_inner_quotes(answer or "")
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
    cleaned = re.sub(
        r'(?i)Pastor Don(?: and Susan)?(?: Nordin)?(?: also)? teach(?:es)?,\.\s*',
        "",
        cleaned,
    )
    cleaned = re.sub(
        r'(?i)(?:^|(?<=\s))Pastor Don(?: and Susan)?(?: Nordin)?(?: also)? '
        r'(?:teaches|emphasizes|advises|encourages|explains|reminds us),'
        r'(?!\s*[\"“])\s*(?:\.\s*)?',
        "",
        cleaned,
    )
    cleaned = re.sub(
        r'(?i)(?:^|(?<=\s))(?:[A-Za-z][^.\n\"“]{0,60})?[\"”]\s*(?=(?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+\d+:\d+)',
        "",
        cleaned,
    )
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
