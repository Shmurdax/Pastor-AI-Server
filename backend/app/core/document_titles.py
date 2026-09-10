"""
Display-title cleanup for ingested sermons and media.

Keeps on-disk ``source_name`` / PDF paths stable while producing readable
``IngestedDocument.title`` values for the sermon library and admin UI.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Trailing / mid-name noise often present in exported sermon filenames.
_TAG_PHRASES = (
    "teaching notes",
    "sermon notes",
    "study notes",
    "pastor notes",
    "pastors notes",
    "pastor's notes",
    "manuscript",
    "handout",
    "outline",
    "transcript",
    "full notes",
    "speaker notes",
    "discussion guide",
    "small group",
    "leader guide",
)

# Video/audio export tokens that should not appear in sermon library titles.
# Matched as whole tokens between separators (so "Child" keeps "hd" letters).
_VIDEO_EXPORT_TOKEN_RE = re.compile(
    r"""(?ix)
        (?:^|[\s_\-]+)
        (?:
            v\d+                          # V1, V2
            | ver(?:sion)?\s*\d+          # ver 1, version2
            | \d{3,4}p                    # 240p, 720p, 1080p
            | 4k | 8k | uhd | fhd | hd | sd
            | \d{3,4}\s*x\s*\d{3,4}       # 1920x1080
            | \d{2,3}\s*fps
            | h\.?264 | h\.?265 | hevc | x264 | x265 | avc | prores
            | export(?:ed)?
            | proxy
            | screener
            | webrip | web-?dl
            | raw\s*export
        )
        (?=$|[\s_\-]+)
    """
)

_COPY_SUFFIX_RE = re.compile(
    r"""(?ix)
        (?:
            [\s_\-]*\(\s*\d+\s*\)          # (1), (2)
            | [\s_\-]+copy(?:\s*\d+)?     # copy, copy 2
            | [\s_\-]+final
            | [\s_\-]+draft
            # Single-digit copy markers only (Promise 1). Keep multi-digit
            # dates / series numbers (June 30, Sermon 12).
            | [\s_\-]+[1-9](?!\d)
        )
        \s*$
    """
)

_SEPARATOR_RE = re.compile(r"[\s_\-]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Small words kept lowercase inside a title (not at start/end).
_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "nor",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "vs",
    "via",
    "with",
}

# Known acronyms forced to ALL CAPS after title cleanup (case-insensitive match).
# Do not put ordinary short words here (a, an, is, man, …).
_ACRONYM_ALLOWLIST = {
    # Geographic / org
    "USA",
    "US",
    "UK",
    "UN",
    "EU",
    # Bible versions / translations
    "NKJV",
    "KJV",
    "NIV",
    "ESV",
    "NASB",
    "CSB",
    "HCSB",
    "RSV",
    "NRSV",
    "ASV",
    "NET",
    "AMP",
    "NLT",
    "BSB",
    "LSB",
    "MEV",
    # Scripture / era shorthand
    "NT",
    "OT",
    "BC",
    "AD",
    # Common short tokens in filenames
    "AI",
    "FAQ",
    "PDF",
}
_ACRONYMS_BY_LOWER = {token.lower(): token for token in _ACRONYM_ALLOWLIST}


def filename_stem(name: str) -> str:
    return Path(name or "").stem.strip() or "document"


def _strip_tag_phrases(text: str) -> str:
    lowered = text
    for phrase in _TAG_PHRASES:
        # Remove phrase when bounded by separators or string edges.
        pattern = re.compile(
            rf"(?i)(?:^|[\s_\-\|\[\(\{{]+){re.escape(phrase)}(?:[\s_\-\|\]\)\}}]+|$)"
        )
        lowered = pattern.sub(" ", lowered)
    return lowered


def _strip_copy_suffixes(text: str) -> str:
    previous = None
    current = text.strip()
    while previous != current:
        previous = current
        current = _COPY_SUFFIX_RE.sub("", current).strip()
    return current


def _strip_video_export_tokens(text: str) -> str:
    """Remove resolution / version / codec tags from video export filenames."""
    previous = None
    current = text.strip()
    while previous != current:
        previous = current
        current = _VIDEO_EXPORT_TOKEN_RE.sub(" ", current)
        current = _SEPARATOR_RE.sub(" ", current).strip()
    return current


def _title_case_word(word: str, *, first: bool, last: bool) -> str:
    if not word:
        return word
    lower = word.lower()
    # Allowlisted acronyms win over small-word / shouting-filename heuristics.
    acronym = _ACRONYMS_BY_LOWER.get(lower)
    if acronym is not None:
        return acronym
    if "'" in word and len(word) > 2:
        # Preserve simple possessives / contractions: God's, Don't
        parts = word.split("'")
        return "'".join(
            p[:1].upper() + p[1:].lower() if p else p for p in parts
        )
    if not first and not last and lower in _SMALL_WORDS:
        return lower
    return lower[:1].upper() + lower[1:]


def title_case(text: str) -> str:
    words = [w for w in _SEPARATOR_RE.split(text.strip()) if w]
    if not words:
        return ""
    last_idx = len(words) - 1
    return " ".join(
        _title_case_word(word, first=(idx == 0), last=(idx == last_idx))
        for idx, word in enumerate(words)
    )


def prettify_title(name: str) -> str:
    """
    Turn a raw upload filename (or stem) into a presentable display title.

    Examples:
      ``PREGNANT WITH A PROMISE 1 - TEACHING NOTES.pdf``
        → ``Pregnant with a Promise``
      ``A GOOD MAN.pdf`` → ``A Good Man``
      ``USA MISSIONS NKJV.pdf`` → ``USA Missions NKJV``
      ``Faith_That_Moves_Mountains_Sermon_Notes.docx``
        → ``Faith That Moves Mountains``
      ``June_30_V1_240p.mp4`` → ``June 30``
    """
    stem = filename_stem(name)
    # Normalize unicode and drop odd control chars.
    stem = unicodedata.normalize("NFKC", stem)
    stem = stem.replace("—", "-").replace("–", "-")
    # Normalize separators early so multi-word tags match across `_` / `-`.
    stem = _SEPARATOR_RE.sub(" ", stem).strip()
    stem = _strip_tag_phrases(stem)
    stem = _strip_video_export_tokens(stem)
    stem = _strip_copy_suffixes(stem)
    # Treat pipes / brackets leftovers as separators.
    stem = re.sub(r"[\[\]\{\}\(\)\|]+", " ", stem)
    stem = _SEPARATOR_RE.sub(" ", stem).strip(" -_")
    stem = _strip_video_export_tokens(stem)
    stem = _strip_copy_suffixes(stem)
    pretty = title_case(stem)
    return pretty or "Untitled"


def normalize_title_key(name: str) -> str:
    """
    Stable key for near-duplicate title matching.

    Lowercase alphanumeric only after the same cleanup as ``prettify_title``.
    """
    pretty = prettify_title(name)
    key = _NON_ALNUM_RE.sub("", pretty.lower())
    return key
