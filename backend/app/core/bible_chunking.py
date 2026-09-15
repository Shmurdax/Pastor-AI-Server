"""Split ingested NKJV text into verse-level chunks for exact lookup."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .bible_refs import BIBLE_BOOKS, canonical_book_key, display_book_name, format_verse_ref

_MIN_VERSES_TO_TRUST_PARSE = 8
_DEFAULT_VERSES_PER_CHUNK = 4

_BOOK_HEADER_RE = re.compile(
    rf"^\s*(?:#+\s*)?((?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)*)\s*$",
    re.MULTILINE,
)
_CHAPTER_HEADER_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:chapter\s+)?(\d{1,3})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_INLINE_REF_RE = re.compile(
    rf"(?P<book>(?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)?)\s+"
    rf"(?P<chapter>\d{{1,3}}):(?P<verse>\d{{1,3}})\s+"
    rf"(?P<text>.+?)(?="
    rf"(?:(?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)?\s+\d{{1,3}}:\d{{1,3}}\s+)"
    rf"|$)",
    re.DOTALL,
)
_CV_LINE_RE = re.compile(r"^\s*(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\s+(?P<text>.+)$")
_V_LINE_RE = re.compile(r"^\s*(?P<verse>\d{1,3})\s+(?P<text>.+)$")
_PACKED_VERSE_RE = re.compile(r"(?:(?<=\s)|(?<=^))(?P<verse>\d{1,3})\s+(?P<text>[A-Z“\"‘'].+?)(?=(?:\s+\d{1,3}\s+[A-Z“\"‘']|$))")


@dataclass(frozen=True)
class NkjvVerse:
    book: str
    chapter: int
    verse: int
    text: str

    @property
    def ref(self) -> str:
        return format_verse_ref(self.book, self.chapter, self.verse)


def _is_book_name(value: str) -> bool:
    key = canonical_book_key(value)
    return key in {canonical_book_key(book) for book in BIBLE_BOOKS}


def parse_nkjv_verses(text: str) -> list[NkjvVerse]:
    """Best-effort verse parse of extracted NKJV markdown/PDF text."""
    verses: list[NkjvVerse] = []
    seen: set[str] = set()

    def add(book_name: str, chap: int, verse: int, body: str) -> None:
        cleaned = " ".join((body or "").split())
        if not book_name or chap < 1 or verse < 1 or len(cleaned) < 8:
            return
        key = f"{canonical_book_key(book_name)}|{chap}|{verse}"
        if key in seen:
            return
        seen.add(key)
        verses.append(
            NkjvVerse(
                book=canonical_book_key(book_name),
                chapter=int(chap),
                verse=int(verse),
                text=cleaned,
            )
        )

    for match in _INLINE_REF_RE.finditer(text or ""):
        raw_book = match.group("book")
        if not _is_book_name(raw_book):
            continue
        add(raw_book, int(match.group("chapter")), int(match.group("verse")), match.group("text"))

    current_book = ""
    current_chapter = 0
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[Note "):
            continue
        header = _BOOK_HEADER_RE.match(line)
        if header and _is_book_name(header.group(1)):
            current_book = canonical_book_key(header.group(1))
            current_chapter = 0
            continue
        chapter_match = _CHAPTER_HEADER_RE.match(line)
        if chapter_match and current_book:
            current_chapter = int(chapter_match.group(1))
            continue
        cv_match = _CV_LINE_RE.match(line)
        if cv_match:
            current_chapter = int(cv_match.group("chapter"))
            if current_book:
                add(current_book, current_chapter, int(cv_match.group("verse")), cv_match.group("text"))
            continue
        v_match = _V_LINE_RE.match(line)
        if v_match and current_book and current_chapter:
            add(current_book, current_chapter, int(v_match.group("verse")), v_match.group("text"))
            continue
        if current_book and current_chapter:
            for packed in _PACKED_VERSE_RE.finditer(line):
                add(current_book, current_chapter, int(packed.group("verse")), packed.group("text"))

    verses.sort(key=lambda item: (item.book, item.chapter, item.verse))
    return verses


def pack_nkjv_verse_chunks(
    verses: list[NkjvVerse],
    *,
    verses_per_chunk: int | None = None,
) -> tuple[list[str], list[dict]]:
    size = max(1, int(verses_per_chunk or os.getenv("BIBLE_VERSES_PER_CHUNK", str(_DEFAULT_VERSES_PER_CHUNK))))
    chunks: list[str] = []
    metas: list[dict] = []
    group: list[NkjvVerse] = []

    def flush() -> None:
        if not group:
            return
        first = group[0]
        last = group[-1]
        heading = display_book_name(first.book)
        body_lines = [f"{item.verse} {item.text}" for item in group]
        text = f"# {heading} {first.chapter}\n\n" + "\n".join(body_lines)
        chunks.append(text.strip())
        metas.append(
            {
                "chunk_kind": "bible_verse",
                "content_type": "bible",
                "book": first.book,
                "chapter": first.chapter,
                "verse_start": first.verse,
                "verse_end": last.verse,
                "verse_ref": format_verse_ref(
                    first.book, first.chapter, first.verse, verse_end=last.verse
                ),
                "quote_text": " ".join(item.text for item in group),
            }
        )
        group.clear()

    for verse in verses:
        if group and (
            verse.book != group[0].book
            or verse.chapter != group[0].chapter
            or len(group) >= size
        ):
            flush()
        group.append(verse)
    flush()
    return chunks, metas


def split_nkjv_document(text: str) -> tuple[list[str], list[dict]]:
    verses = parse_nkjv_verses(text)
    if len(verses) < _MIN_VERSES_TO_TRUST_PARSE:
        return [], []
    return pack_nkjv_verse_chunks(verses)
