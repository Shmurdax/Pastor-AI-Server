"""Canonical Bible book names and verse-reference parsing for NKJV ingest/lookup."""

from __future__ import annotations

import re

BIBLE_BOOKS = tuple(
    sorted(
        (
            "song of solomon",
            "1 corinthians",
            "2 corinthians",
            "1 thessalonians",
            "2 thessalonians",
            "1 timothy",
            "2 timothy",
            "1 peter",
            "2 peter",
            "1 john",
            "2 john",
            "3 john",
            "1 samuel",
            "2 samuel",
            "1 kings",
            "2 kings",
            "1 chronicles",
            "2 chronicles",
            "genesis",
            "exodus",
            "leviticus",
            "numbers",
            "deuteronomy",
            "joshua",
            "judges",
            "ruth",
            "ezra",
            "nehemiah",
            "esther",
            "job",
            "psalm",
            "psalms",
            "proverbs",
            "ecclesiastes",
            "isaiah",
            "jeremiah",
            "lamentations",
            "ezekiel",
            "daniel",
            "hosea",
            "joel",
            "amos",
            "obadiah",
            "jonah",
            "micah",
            "nahum",
            "habakkuk",
            "zephaniah",
            "haggai",
            "zechariah",
            "malachi",
            "matthew",
            "mark",
            "luke",
            "john",
            "acts",
            "romans",
            "galatians",
            "ephesians",
            "philippians",
            "colossians",
            "titus",
            "philemon",
            "hebrews",
            "james",
            "jude",
            "revelation",
        ),
        key=len,
        reverse=True,
    )
)

_BOOK_ALIASES = {
    "psalms": "Psalm",
    "psalm": "Psalm",
    "song of solomon": "Song of Solomon",
    "song of songs": "Song of Solomon",
}

_BOOK_LOOKUP = {book: book for book in BIBLE_BOOKS}
for alias, canonical in {
    "song of songs": "song of solomon",
}.items():
    _BOOK_LOOKUP[alias] = canonical

_BOOK_DISPLAY = {
    book: _BOOK_ALIASES.get(book, " ".join(part.capitalize() for part in book.split()))
    for book in BIBLE_BOOKS
}
_BOOK_DISPLAY["psalms"] = "Psalm"
_BOOK_DISPLAY["psalm"] = "Psalm"

_BOOK_PATTERN = "|".join(re.escape(book) for book in BIBLE_BOOKS)
VERSE_REF_RE = re.compile(
    rf"\b({_BOOK_PATTERN})\s+(\d+):(\d+)(?:\s*[-–]\s*(\d+))?",
    re.IGNORECASE,
)


def canonical_book_key(name: str) -> str:
    key = re.sub(r"\s+", " ", (name or "").strip().lower())
    key = re.sub(r"^psalms$", "psalm", key)
    return _BOOK_LOOKUP.get(key, key)


def display_book_name(name: str) -> str:
    key = canonical_book_key(name)
    return _BOOK_DISPLAY.get(key, (name or "").strip() or "Scripture")


def format_verse_ref(book: str, chapter: int, verse: int, *, verse_end: int | None = None) -> str:
    label = display_book_name(book)
    if verse_end and verse_end != verse:
        return f"{label} {int(chapter)}:{int(verse)}-{int(verse_end)}"
    return f"{label} {int(chapter)}:{int(verse)}"


def parse_verse_refs(text: str) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for match in VERSE_REF_RE.finditer(text or ""):
        book = canonical_book_key(match.group(1))
        if book not in _BOOK_LOOKUP and book not in BIBLE_BOOKS:
            continue
        chapter = int(match.group(2))
        start = int(match.group(3))
        end = int(match.group(4) or start)
        for verse in range(start, end + 1):
            key = f"{book}|{chapter}|{verse}"
            if key in seen:
                continue
            seen.add(key)
            found.append((book, chapter, verse))
    return found
