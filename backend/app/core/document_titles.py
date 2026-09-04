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

_COPY_SUFFIX_RE = re.compile(
    r"""(?ix)
        (?:
            [\s_\-]*\(\s*\d+\s*\)          # (1), (2)
            | [\s_\-]+copy(?:\s*\d+)?     # copy, copy 2
            | [\s_\-]+final
            | [\s_\-]+draft
            | [\s_\-]+\d+                 # trailing 1 / 2
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


def _title_case_word(word: str, *, first: bool, last: bool) -> str:
    if not word:
        return word
    if "'" in word and len(word) > 2:
        # Preserve simple possessives / contractions: God's, Don't
        parts = word.split("'")
        return "'".join(
            p[:1].upper() + p[1:].lower() if p else p for p in parts
        )
    lower = word.lower()
    if not first and not last and lower in _SMALL_WORDS:
        return lower
    if word.isupper() and len(word) <= 3 and word.isalpha():
        # Keep short acronyms like NKJV, USA when already all-caps input tokens.
        return word.upper()
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
        → ``Pregnant With a Promise``
      ``Faith_That_Moves_Mountains_Sermon_Notes.docx``
        → ``Faith That Moves Mountains``
    """
    stem = filename_stem(name)
    # Normalize unicode and drop odd control chars.
    stem = unicodedata.normalize("NFKC", stem)
    stem = stem.replace("—", "-").replace("–", "-")
    # Normalize separators early so multi-word tags match across `_` / `-`.
    stem = _SEPARATOR_RE.sub(" ", stem).strip()
    stem = _strip_tag_phrases(stem)
    stem = _strip_copy_suffixes(stem)
    # Treat pipes / brackets leftovers as separators.
    stem = re.sub(r"[\[\]\{\}\(\)\|]+", " ", stem)
    stem = _SEPARATOR_RE.sub(" ", stem).strip(" -_")
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
