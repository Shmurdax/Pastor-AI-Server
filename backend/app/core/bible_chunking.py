"""Split ingested NKJV text into verse-level chunks for exact lookup."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .bible_refs import BIBLE_BOOKS, canonical_book_key, display_book_name, format_verse_ref

_MIN_VERSES_TO_TRUST_PARSE = 8
_DEFAULT_VERSES_PER_CHUNK = 4
_KNOWN_BOOKS = {canonical_book_key(book) for book in BIBLE_BOOKS}

_BOOK_HEADER_RE = re.compile(
    r"^\s*(?:#+\s*)?((?:[1-3](?:st|nd|rd|th)?\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)*)\s*$"
)
_CHAPTER_HEADER_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:chapter\s+)?(\d{1,3})\s*$",
    re.IGNORECASE,
)
_PSALM_HEADER_RE = re.compile(r"^\s*psalms?\s+(\d{1,3})\s*$", re.IGNORECASE)
_INLINE_REF_RE = re.compile(
    rf"(?P<book>(?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)?)\s+"
    rf"(?P<chapter>\d{{1,3}}):(?P<verse>\d{{1,3}})\s+"
    rf"(?P<text>.+?)(?="
    rf"(?:(?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z]+)?\s+\d{{1,3}}:\d{{1,3}}\s+)"
    rf"|$)",
    re.DOTALL,
)
_CV_LINE_RE = re.compile(r"^\s*(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\s+(?P<text>.+)$")
# Spaced ("1 In the beginning") or Word-export glued ("1In the beginning").
_V_LINE_RE = re.compile(
    r"^\s*(?P<verse>\d{1,3})(?:\s+|(?=[A-Za-z“\"‘'(]))(?P<text>.+)$"
)
_PACKED_VERSE_RE = re.compile(
    r"(?:(?<=\s)|(?<=^))(?P<verse>\d{1,3})\s+(?P<text>[A-Z“\"‘'(].+?)"
    r"(?=(?:\s+\d{1,3}\s+[A-Z“\"‘'(]|$))"
)
# Verse bodies in this NKJV start with a capital, a quote, or a parenthesis.
_VERSE_BODY_START_RE = re.compile(r"^[A-Z“\"‘'(]")


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
    return canonical_book_key(value) in _KNOWN_BOOKS


def _looks_like_verse_body(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and _VERSE_BODY_START_RE.match(stripped) is not None


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

    lines = [(raw_line.strip()) for raw_line in (text or "").splitlines()]

    def peek_next_verse_number(start: int) -> int | None:
        for j in range(start + 1, min(start + 60, len(lines))):
            candidate = lines[j]
            if not candidate or candidate.startswith("[Note "):
                continue
            book_header = _BOOK_HEADER_RE.match(candidate)
            if _PSALM_HEADER_RE.match(candidate) or (
                book_header and _is_book_name(book_header.group(1))
            ):
                return None
            peeked = _V_LINE_RE.match(candidate)
            if peeked:
                body = (peeked.group("text") or "").strip()
                if body:
                    return int(peeked.group("verse"))
        return None

    current_book = ""
    current_chapter = 0
    next_verse = 1
    pending_verse: int | None = None
    pending_parts: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_verse
        if current_book and current_chapter and pending_verse:
            add(current_book, current_chapter, pending_verse, " ".join(pending_parts))
        pending_parts.clear()
        pending_verse = None

    def start_verse(verse_no: int, body: str) -> None:
        nonlocal pending_verse, next_verse
        flush_pending()
        pending_verse = verse_no
        next_verse = verse_no + 1
        if body.strip():
            pending_parts.append(body.strip())

    def start_book(book_name: str, chapter: int = 1) -> None:
        nonlocal current_book, current_chapter, next_verse
        flush_pending()
        current_book = canonical_book_key(book_name)
        current_chapter = chapter
        next_verse = 1

    for idx, line in enumerate(lines):
        if not line or line.startswith("[Note "):
            continue

        psalm_header = _PSALM_HEADER_RE.match(line)
        if psalm_header:
            start_book("psalm", int(psalm_header.group(1)))
            continue

        header = _BOOK_HEADER_RE.match(line)
        if header and _is_book_name(header.group(1)):
            start_book(header.group(1), 1)
            continue

        chapter_match = _CHAPTER_HEADER_RE.match(line)
        if chapter_match and current_book:
            flush_pending()
            current_chapter = int(chapter_match.group(1))
            next_verse = 1
            continue

        cv_match = _CV_LINE_RE.match(line)
        if cv_match and current_book:
            current_chapter = int(cv_match.group("chapter"))
            start_verse(int(cv_match.group("verse")), cv_match.group("text"))
            continue

        v_match = _V_LINE_RE.match(line)
        if v_match and current_book and current_chapter:
            verse_no = int(v_match.group("verse"))
            body = (v_match.group("text") or "").strip()
            ahead = peek_next_verse_number(idx)
            new_chapter = bool(
                body
                and verse_no == current_chapter + 1
                and (
                    ahead == 2
                    or (verse_no != next_verse and next_verse >= 8 and ahead != verse_no + 1)
                )
            )
            if new_chapter:
                flush_pending()
                current_chapter = verse_no
                start_verse(1, body)
                continue
            if verse_no == next_verse and body:
                start_verse(verse_no, body)
                continue
            if verse_no == 1 and next_verse > 1 and _looks_like_verse_body(body):
                flush_pending()
                current_chapter += 1
                start_verse(1, body)
                continue
            if pending_verse:
                pending_parts.append(line)
                continue
            for packed in _PACKED_VERSE_RE.finditer(line):
                add(
                    current_book,
                    current_chapter,
                    int(packed.group("verse")),
                    packed.group("text"),
                )
            continue

        if current_book and current_chapter and pending_verse:
            pending_parts.append(line)
            continue

        if current_book and current_chapter:
            for packed in _PACKED_VERSE_RE.finditer(line):
                add(
                    current_book,
                    current_chapter,
                    int(packed.group("verse")),
                    packed.group("text"),
                )

    flush_pending()
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
