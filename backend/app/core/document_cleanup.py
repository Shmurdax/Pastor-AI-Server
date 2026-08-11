"""
Structured cleanup for admin-ingested documents before they are chunked into Qdrant.

This module cleans *extracted text only*. Original PDF/DOCX files under
``uploads/admin_ingestion`` are left untouched so sermon-library download links
continue to serve the authentic source documents.

Pipeline stages (PDF / plain extract path):
  1. Strip control characters and soft hyphens
  2. Split on form-feed page breaks; drop repeating headers/footers and page numbers
  3. Fix hyphenation broken across line wraps (``salva-\\ntion`` → ``salvation``)
  4. Rejoin soft-wrapped lines into coherent paragraphs
  5. Drop boilerplate / noise lines that confuse retrieval and generation
  6. Deduplicate short repeated lines and normalize whitespace
  7. Return structured markdown-friendly plain text

Markdown ingest path uses a lighter pass that preserves headings and list markers.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional


# Lines that look like page chrome rather than sermon/Bible content.
_PAGE_NUMBER_RE = re.compile(
    r"""(?ix)^
        (?:
            page\s+\d+(?:\s+of\s+\d+)?
            | \d+\s*/\s*\d+
            | [-–—]?\s*\d+\s*[-–—]?
            | \d+\s*$
        )
    $"""
)

_BOILERPLATE_RE = re.compile(
    r"""(?ix)^
        (?:
            all\s+rights\s+reserved\.?
            | copyright\b.*
            | ©\s*\d{4}.*
            | confidential\.?
            | do\s+not\s+(?:copy|distribute|reproduce).*
            | proprietary\.?
            | printed\s+(?:on|from)\b.*
            | downloaded\s+from\b.*
            | this\s+document\s+is\s+(?:the\s+)?property\b.*
            | for\s+(?:internal|personal)\s+use\s+only\.?
            | unauthorized\s+(?:copying|reproduction|distribution).*
            | www\.[^\s]+\s*$
            | https?://[^\s]+\s*$
        )
    $"""
)

# Dot leaders typical of TOC rows: "Introduction .......... 12"
_TOC_LEADER_RE = re.compile(r"\.{4,}\s*\d+\s*$")

_SOFT_HYPHEN = "\u00ad"
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")

# Sentence / paragraph end that should keep a hard break.
_HARD_BREAK_END_RE = re.compile(r"[.!?:;\"')\]]\s*$")
_HEADING_OR_LIST_RE = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")


@dataclass
class CleanupStats:
    pages_seen: int = 0
    headers_removed: int = 0
    footers_removed: int = 0
    page_numbers_removed: int = 0
    boilerplate_removed: int = 0
    hyphen_fixes: int = 0
    soft_lines_joined: int = 0
    duplicate_lines_removed: int = 0
    control_chars_removed: int = 0

    def as_dict(self) -> dict:
        return {
            "pages_seen": self.pages_seen,
            "headers_removed": self.headers_removed,
            "footers_removed": self.footers_removed,
            "page_numbers_removed": self.page_numbers_removed,
            "boilerplate_removed": self.boilerplate_removed,
            "hyphen_fixes": self.hyphen_fixes,
            "soft_lines_joined": self.soft_lines_joined,
            "duplicate_lines_removed": self.duplicate_lines_removed,
            "control_chars_removed": self.control_chars_removed,
        }


@dataclass
class CleanupResult:
    text: str
    stats: CleanupStats = field(default_factory=CleanupStats)

    @property
    def changed(self) -> bool:
        s = self.stats
        return any(
            getattr(s, name) > 0
            for name in (
                "headers_removed",
                "footers_removed",
                "page_numbers_removed",
                "boilerplate_removed",
                "hyphen_fixes",
                "soft_lines_joined",
                "duplicate_lines_removed",
                "control_chars_removed",
            )
        )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_control_chars(text: str, stats: CleanupStats) -> str:
    """Keep newlines and tabs; drop other C0/C1 controls and zero-width junk."""
    out_chars: list[str] = []
    removed = 0
    for ch in text:
        if ch in ("\n", "\t"):
            out_chars.append(ch)
            continue
        if ch == _SOFT_HYPHEN:
            removed += 1
            continue
        if _ZERO_WIDTH_RE.match(ch):
            removed += 1
            continue
        cat = unicodedata.category(ch)
        if cat in {"Cc", "Cf"} and ch != "\n":
            # Form feed becomes an explicit page break for later stages.
            if ch == "\x0c":
                out_chars.append("\n\x0c\n")
            else:
                removed += 1
            continue
        out_chars.append(ch)
    stats.control_chars_removed += removed
    return "".join(out_chars)


def _is_page_number_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _PAGE_NUMBER_RE.match(stripped):
        # Avoid dropping meaningful single-digit scripture refs like "3" alone
        # only when surrounded by letters nearby — standalone digits in page
        # chrome context are still removed by the page-boundary pass.
        return True
    return False


def _is_boilerplate_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _BOILERPLATE_RE.match(stripped):
        return True
    if _TOC_LEADER_RE.search(stripped) and len(stripped) < 120:
        return True
    return False


def _split_pages(text: str) -> list[str]:
    # Prefer form-feed splits; otherwise treat double blank lines after
    # short trailing page-number-ish lines as soft page boundaries later.
    if "\x0c" in text:
        return [p.strip("\n") for p in text.split("\x0c")]
    return [text]


def _line_key(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _detect_repeating_margins(pages: list[str], *, max_scan: int = 3) -> tuple[set[str], set[str]]:
    """Find short lines that repeat at the top/bottom of many pages (headers/footers)."""
    if len(pages) < 3:
        return set(), set()

    header_counts: Counter[str] = Counter()
    footer_counts: Counter[str] = Counter()

    for page in pages:
        lines = [ln.strip() for ln in page.split("\n") if ln.strip()]
        if not lines:
            continue
        for ln in lines[:max_scan]:
            key = _line_key(ln)
            if 2 <= len(key) <= 80:
                header_counts[key] += 1
        for ln in lines[-max_scan:]:
            key = _line_key(ln)
            if 2 <= len(key) <= 80:
                footer_counts[key] += 1

    threshold = max(3, (len(pages) + 1) // 2)
    headers = {k for k, n in header_counts.items() if n >= threshold}
    footers = {k for k, n in footer_counts.items() if n >= threshold}
    # Page numbers often also appear in margins; keep them in both sets.
    return headers, footers


def _clean_pages(pages: list[str], stats: CleanupStats) -> list[str]:
    headers, footers = _detect_repeating_margins(pages)
    cleaned_pages: list[str] = []

    for page in pages:
        stats.pages_seen += 1
        kept: list[str] = []
        raw_lines = page.split("\n")
        for idx, line in enumerate(raw_lines):
            stripped = line.strip()
            if not stripped:
                kept.append("")
                continue
            key = _line_key(stripped)

            # Drop repeating header/footer chrome.
            near_top = idx < 3
            near_bottom = idx >= max(0, len(raw_lines) - 3)
            if near_top and key in headers:
                stats.headers_removed += 1
                continue
            if near_bottom and key in footers:
                stats.footers_removed += 1
                continue

            if _is_page_number_line(stripped):
                # Only strip numeric chrome at page margins. Mid-page lone digits
                # can be chapter/verse markers and must stay for the AI.
                explicit_page = bool(re.match(r"(?i)^page\s+\d+", stripped))
                if near_top or near_bottom or explicit_page:
                    stats.page_numbers_removed += 1
                    continue

            if _is_boilerplate_line(stripped):
                stats.boilerplate_removed += 1
                continue

            kept.append(stripped)

        cleaned_pages.append("\n".join(kept))

    return cleaned_pages


def _fix_hyphenation(text: str, stats: CleanupStats) -> str:
    def _repl(match: re.Match) -> str:
        stats.hyphen_fixes += 1
        return match.group(1) + match.group(2)

    # salva-\ntion → salvation (letter, hyphen, newline, lowercase letter)
    return re.sub(r"([A-Za-z])-\n([a-z])", _repl, text)


def _should_join_lines(prev: str, nxt: str) -> bool:
    if not prev or not nxt:
        return False
    if _HEADING_OR_LIST_RE.match(prev) or _HEADING_OR_LIST_RE.match(nxt):
        return False
    if _HARD_BREAK_END_RE.search(prev):
        return False
    # Don't glue onto a new heading-like Title Case short line after blank logic.
    if len(nxt) < 40 and nxt[:1].isupper() and not nxt.endswith((",", ";", ":")):
        # Allow join when previous clearly mid-sentence (lowercase continuation expected).
        if nxt[:1].isupper() and prev[-1:].islower():
            # Mid-sentence capital is uncommon; keep break for safety on short titles.
            words = nxt.split()
            if len(words) <= 6 and all(w[:1].isupper() for w in words if w[:1].isalpha()):
                return False
    # Join when next line continues a sentence (starts lowercase or mid-word punctuation).
    if nxt[:1].islower() or nxt[:1] in ",;:)":
        return True
    # Soft-wrap heuristic: both lines are mid-length prose without terminal punctuation.
    if len(prev) < 100 and len(nxt) < 100 and prev[-1:].isalnum() and nxt[:1].isupper():
        # Common PDF wrap: previous line almost full width, next continues.
        return len(prev) >= 40
    return False


def _rejoin_soft_wrapped_lines(text: str, stats: CleanupStats) -> str:
    lines = text.split("\n")
    out: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            out.append(buffer)
            buffer = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            out.append("")
            continue
        if not buffer:
            buffer = stripped
            continue
        if _should_join_lines(buffer, stripped):
            stats.soft_lines_joined += 1
            if buffer.endswith("-") and stripped[:1].islower():
                buffer = buffer[:-1] + stripped
            else:
                buffer = f"{buffer} {stripped}"
        else:
            flush()
            buffer = stripped
    flush()
    return "\n".join(out)


def _dedupe_short_lines(text: str, stats: CleanupStats) -> str:
    """Drop exact consecutive duplicates and global duplicates of short noise lines."""
    seen_short: set[str] = set()
    out: list[str] = []
    prev: Optional[str] = None
    for line in text.split("\n"):
        normalized = line.strip()
        if not normalized:
            if out and out[-1] != "":
                out.append("")
            continue
        if normalized == prev:
            stats.duplicate_lines_removed += 1
            continue
        key = normalized.lower()
        if len(normalized) < 80 and not _HEADING_OR_LIST_RE.match(normalized):
            if key in seen_short:
                stats.duplicate_lines_removed += 1
                continue
            seen_short.add(key)
        out.append(normalized)
        prev = normalized
    return "\n".join(out)


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_extracted_document(
    text: str,
    *,
    title: str = "",
    source_name: str = "",
) -> CleanupResult:
    """
    Full structured cleanup for text extracted from admin-uploaded PDFs/DOCX.

    ``title`` / ``source_name`` are optional context (unused for filtering today,
    reserved so callers can pass document identity for logging).
    """
    del title, source_name  # reserved for future title-aware header stripping
    stats = CleanupStats()
    if not text or not text.strip():
        return CleanupResult(text="", stats=stats)

    body = _normalize_newlines(text)
    body = _strip_control_chars(body, stats)
    pages = _split_pages(body)
    pages = _clean_pages(pages, stats)
    body = "\n\n".join(p.strip() for p in pages if p.strip())
    body = _fix_hyphenation(body, stats)
    body = _rejoin_soft_wrapped_lines(body, stats)
    body = _dedupe_short_lines(body, stats)
    body = _normalize_whitespace(body)
    return CleanupResult(text=body, stats=stats)


def clean_markdown_document(text: str) -> CleanupResult:
    """
    Lighter cleanup for already-structured markdown (crawl pages / converted md).

    Preserves headings and list markers; still strips boilerplate, page numbers,
    control characters, and excessive whitespace.
    """
    stats = CleanupStats()
    if not text or not text.strip():
        return CleanupResult(text="", stats=stats)

    body = _normalize_newlines(text)
    body = _strip_control_chars(body, stats)
    body = body.replace("\x0c", "\n\n")

    kept: list[str] = []
    for line in body.split("\n"):
        stripped = line.rstrip()
        raw = stripped.strip()
        if not raw:
            kept.append("")
            continue
        if _HEADING_OR_LIST_RE.match(raw):
            kept.append(raw)
            continue
        if _is_page_number_line(raw) and len(raw) <= 12:
            stats.page_numbers_removed += 1
            continue
        if _is_boilerplate_line(raw):
            stats.boilerplate_removed += 1
            continue
        kept.append(raw)

    body = "\n".join(kept)
    body = _fix_hyphenation(body, stats)
    body = _dedupe_short_lines(body, stats)
    body = _normalize_whitespace(body)
    return CleanupResult(text=body, stats=stats)


def format_cleanup_log(stats: CleanupStats, *, source_label: str = "") -> str:
    """Human-readable one-liner for ingestion job logs."""
    parts = [
        f"pages={stats.pages_seen}",
        f"headers={stats.headers_removed}",
        f"footers={stats.footers_removed}",
        f"page_nums={stats.page_numbers_removed}",
        f"boilerplate={stats.boilerplate_removed}",
        f"hyphens={stats.hyphen_fixes}",
        f"joins={stats.soft_lines_joined}",
        f"dupes={stats.duplicate_lines_removed}",
    ]
    prefix = f"Cleanup ({source_label}): " if source_label else "Cleanup: "
    return prefix + ", ".join(parts)


def clean_texts(texts: Iterable[str], *, markdown: bool = False) -> list[CleanupResult]:
    cleaner = clean_markdown_document if markdown else clean_extracted_document
    return [cleaner(t) for t in texts]
