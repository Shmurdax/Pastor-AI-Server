"""
Best-effort PII redaction for user chat queries before persistence and model calls.

Always applies high-precision patterns: emails, phone-like numbers, and US-style
street addresses.

Optional conservative name handling: only **two consecutive** Title Case tokens
(e.g. likely given name + surname). Single capitalized words, Mc/Mac, and hyphenated
tokens are **not** redacted here—those caused too many false positives on ordinary
theological English.

Use `redact_user_query` for persistence; use `query_text_for_llm` when feeding the
model or retriever so `[REDACTED]` markers do not confuse generation.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

REDACTED = "[REDACTED]"

# Plain-language substitute for retrieval + LLM only. Storage keeps `REDACTED`.
LLM_PII_PLACEHOLDER = "someone"

_MULTI_PLACEHOLDER_RE = re.compile(
    rf"(?:\b{re.escape(LLM_PII_PLACEHOLDER)}\b\s*){{2,}}",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# US-centric phones; extension formats and spaced digits.
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?)?"
    r"(?:\(\s*\d{3}\s*\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
    r"|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    r"|\b\d{10}\b"
)

_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[NWES]?\s*[A-Za-z0-9.'\u2019]+\s+"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|"
    r"Boulevard|Blvd\.?|Court|Ct\.?|Way|Circle|Cir\.?|Place|Pl\.?|"
    r"Highway|Hwy\.?|Route|Rt\.?)\b",
    re.IGNORECASE,
)

# Title-case word including optional possessive (Mary's / Mary's).
_CAP_WORD = r"[A-Z][a-z]{1,}(?:['\u2019][sS])?"
# Exactly two consecutive Title Case tokens (broader chains looked too much like theology).
_TWO_CAP_NAME_RE = re.compile(rf"\b{_CAP_WORD}\s+{_CAP_WORD}\b")

# Phrases common in theological chat that look like multi-word names but are not PII.
_PROTECTED_PHRASES_LOWER = frozenset(
    {
        "new testament",
        "old testament",
        "holy spirit",
        "son of man",
        "son of god",
        "most high",
        "king james",
        "word of god",
        "body of christ",
        "blood of christ",
        "bread of life",
        "light of the world",
        "lamb of god",
        "house of god",
        "kingdom of god",
        "kingdom of heaven",
        "day of the lord",
        "lord's supper",
        "lords supper",
        "great commission",
        "ten commandments",
        "fruit of the spirit",
        "armor of god",
        "armor of christ",
        "book of life",
        "tree of life",
        "lake of fire",
        "valley of death",
        "shadow of death",
        "song of solomon",
        "song of songs",
        "children of israel",
        "people of god",
        "chosen people",
        "good shepherd",
        "great shepherd",
        "chief shepherd",
        "high priest",
        "living water",
        "living bread",
        "second coming",
        "second adam",
        "last adam",
        "new covenant",
        "old covenant",
        "new creation",
        "new jerusalem",
        "new heaven",
        "new earth",
        "throne room",
        "burning bush",
        "golden calf",
        "red sea",
        "dead sea",
        "sea of galilee",
        "mount sinai",
        "mount zion",
        "mount moriah",
        "mount of olives",
        "mount olivet",
        "lord's prayer",
        "lords prayer",
        "golden rule",
        "great tribulation",
        "final judgment",
        "white throne",
        "great white throne",
        "beatitudes",
        "lords day",
        "lord's day",
        "mercy seat",
        "brazen altar",
        "bronze altar",
        "ark of the covenant",
        "burning fiery furnace",
    }
)

# Extra lowercase tokens allowed when judging capitalized spans (not exhaustive).
_EXTRA_TOKEN_ALLOWLIST = frozenset(
    {
        "when",
        "where",
        "why",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "should",
        "would",
        "could",
        "please",
        "help",
        "thank",
        "thanks",
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "advent",
        "lent",
        "easter",
        "christmas",
        "pastor",
        "church",
        "scripture",
        "scriptures",
        "bible",
        "biblical",
        "gospel",
        "christian",
        "christians",
        "catholic",
        "protestant",
        "orthodox",
        "baptist",
        "methodist",
        "presbyterian",
        "pentecostal",
        "episcopal",
        "lutheran",
        "evangelical",
        "ministry",
        "minister",
        "elders",
        "deacon",
        "deacons",
        "missionary",
        "seminary",
        "theology",
        "theological",
        "discipleship",
        "sermon",
        "psalm",
        "proverbs",
        "ecclesiastes",
        "revelation",
        "genesis",
        "exodus",
        "leviticus",
        "numbers",
        "deuteronomy",
        "american",
        "english",
        "latin",
        "greek",
        "hebrew",
        "aramaic",
        "north",
        "south",
        "east",
        "west",
        "northern",
        "southern",
        "eastern",
        "western",
        "god",
        "lord",
        "christ",
        "jesus",
        "amen",
        "hallelujah",
        "hosanna",
        "maranatha",
        "jerusalem",
        "bethlehem",
        "nazareth",
        "galilee",
        "samaria",
        "egypt",
        "babylon",
        "rome",
        "asia",
        "europe",
        "africa",
        # Often capitalized mid-sentence in religious English (avoid redacting as “names”).
        "mercy",
        "grace",
        "faith",
        "hope",
        "love",
        "peace",
        "joy",
        "truth",
        "life",
        "light",
        "glory",
        "honor",
        "blessing",
        "blessings",
        "covenant",
        "covenants",
        "salvation",
        "righteousness",
        "holiness",
        "sanctification",
        "redemption",
        "atonement",
        "resurrection",
        "incarnation",
        "rapture",
        "tribulation",
        "judgment",
        "heaven",
        "hell",
        "sheol",
        "hades",
        "gehenna",
        "worship",
        "prayer",
        "fasting",
        "communion",
        "baptism",
        "eucharist",
        "liturgy",
        "canon",
        "apostolic",
        "nicene",
        "chalcedonian",
        "reformation",
        "pentecost",
        "purim",
        "passover",
        "tabernacles",
        "trinity",
        "godhead",
        "messiah",
        "immanuel",
        "emmanuel",
        "prophet",
        "prophets",
        "apostle",
        "apostles",
        "disciple",
        "disciples",
        "pharisee",
        "pharisees",
        "sadducee",
        "sadducees",
        "gentile",
        "gentiles",
        "samaritan",
        "samaritans",
        "creation",
        "creator",
        "providence",
        "sovereignty",
        "predestination",
        "election",
        "justification",
        "regeneration",
        "repentance",
        "forgiveness",
        "obedience",
        "surrender",
        "submission",
        "humility",
        "patience",
        "kindness",
        "goodness",
        "faithfulness",
        "gentleness",
        "self-control",
    }
)


@lru_cache(maxsize=1)
def _load_bible_allowlist() -> frozenset[str]:
    path = Path(__file__).resolve().parent / "data" / "bible_names.txt"
    names: set[str] = set()
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            for line in f:
                token = line.strip().lower()
                if token:
                    names.add(token)
    return frozenset(names)


def _token_variants(token: str) -> frozenset[str]:
    w = token.strip().replace("\u2019", "'").lower()
    if not w:
        return frozenset()
    out: set[str] = {w}
    if w.endswith("'s"):
        out.add(w[:-2])
    out.add(w.replace("'", ""))
    return frozenset(out)


def _token_allowed(token: str, bible: frozenset[str]) -> bool:
    if _token_variants(token) & _EXTRA_TOKEN_ALLOWLIST:
        return True
    return bool(_token_variants(token) & bible)


def _protected_phrase_pattern(phrase_lower: str) -> re.Pattern[str]:
    parts = phrase_lower.split()
    inner = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<!\w)({inner})(?!\w)", re.IGNORECASE)


def _mask_protected_phrases(text: str) -> tuple[str, dict[str, str]]:
    """
    Temporarily replace known theological phrases so broader capitalized-span
    heuristics do not swallow them (e.g. 'New Testament view').
    """
    mapping: dict[str, str] = {}
    out = text
    n = 0
    for phrase in sorted(_PROTECTED_PHRASES_LOWER, key=len, reverse=True):
        pat = _protected_phrase_pattern(phrase)
        while True:
            m = pat.search(out)
            if not m:
                break
            key = f"\uffffPP{n}\uffff"
            mapping[key] = m.group(1)
            n += 1
            out = out[: m.start()] + key + out[m.end() :]
    return out, mapping


def _unmask_protected(text: str, mapping: dict[str, str]) -> str:
    for key, val in mapping.items():
        text = text.replace(key, val)
    return text


def _phrase_allowed(words: tuple[str, ...], bible: frozenset[str]) -> bool:
    joined = " ".join(w.strip().replace("\u2019", "'").lower() for w in words)
    if joined in _PROTECTED_PHRASES_LOWER:
        return True
    return all(_token_allowed(w, bible) for w in words)


def _redact_two_word_cap_names(text: str, bible: frozenset[str]) -> str:
    out = []
    pos = 0
    for m in _TWO_CAP_NAME_RE.finditer(text):
        out.append(text[pos : m.start()])
        phrase = m.group()
        words = tuple(phrase.split())
        if _phrase_allowed(words, bible):
            out.append(phrase)
        else:
            out.append(REDACTED)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _redact_pattern(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(REDACTED, text)


def redact_user_query(text: str | None) -> str:
    """
    Return text with likely PII replaced by REDACTED. Empty input becomes empty string.
    """
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""

    bible = _load_bible_allowlist()

    s = _redact_pattern(s, _EMAIL_RE)
    s = _redact_pattern(s, _PHONE_RE)
    s = _redact_pattern(s, _STREET_RE)

    s, prot_map = _mask_protected_phrases(s)
    s = _redact_two_word_cap_names(s, bible)
    s = _unmask_protected(s, prot_map)

    return s


def query_text_for_llm(stored_redacted: str | None) -> str:
    """
    Convert DB-safe redacted strings into natural wording for embeddings and the model.

    Literal `[REDACTED]` tokens can skew refusal behavior and retrieval; persistence
    still uses `redact_user_query` output unchanged.
    """
    if stored_redacted is None:
        return ""
    s = str(stored_redacted).strip()
    if not s:
        return ""
    s = s.replace(REDACTED, LLM_PII_PLACEHOLDER)
    s = _MULTI_PLACEHOLDER_RE.sub(f"{LLM_PII_PLACEHOLDER} ", s)
    return re.sub(r"\s+", " ", s).strip()
