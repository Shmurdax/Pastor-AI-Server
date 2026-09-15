"""Split sermon notes and transcripts into quote-sized retrieval windows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_SENTENCE_RE = re.compile(r"(?<=[.!?])[\"”']?\s+(?=[A-Z“\"‘'])")
_QUOTE_SPAN_RE = re.compile(r"[\"“](.{12,400}?)[\"”]")
_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_TIMESTAMP_RE = re.compile(r"^\s*\[[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?[–-][0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\]\s*")
_DEFAULT_TARGET = 550
_DEFAULT_OVERLAP = 80


@dataclass(frozen=True)
class QuoteChunk:
    text: str
    quote_text: str
    chunk_kind: str = "sermon_quote"


def spoken_text_without_timestamps(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        cleaned = _TIMESTAMP_RE.sub("", line).strip()
        if cleaned:
            lines.append(cleaned)
    return " ".join(lines).strip() or " ".join((text or "").split())


def split_sentences(text: str) -> list[str]:
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return []
    parts = _SENTENCE_RE.split(collapsed)
    return [part.strip() for part in parts if part.strip()]


def extract_quote_spans(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _QUOTE_SPAN_RE.finditer(text or ""):
        span = " ".join(match.group(1).split()).strip()
        key = span.lower()
        if len(span) < 12 or key in seen:
            continue
        seen.add(key)
        found.append(span)
    for sentence in split_sentences(text):
        cleaned = sentence.strip(" \"“”'")
        key = cleaned.lower()
        if len(cleaned) < 40 or len(cleaned) > 400 or key in seen:
            continue
        if _HEADER_RE.match(cleaned):
            continue
        seen.add(key)
        found.append(cleaned)
    return found


def _paragraphs(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in (text or "").splitlines():
        if not line.strip():
            if current:
                blocks.append(" ".join(part.strip() for part in current if part.strip()))
                current = []
            continue
        if _HEADER_RE.match(line) and current:
            blocks.append(" ".join(part.strip() for part in current if part.strip()))
            current = [line.strip()]
            continue
        current.append(line)
    if current:
        blocks.append(" ".join(part.strip() for part in current if part.strip()))
    return [block for block in blocks if block]


def _pack_windows(paragraphs: list[str], *, target: int, overlap: int) -> list[str]:
    if not paragraphs:
        return []
    windows: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current} {para}".strip() if current else para
        if current and len(candidate) > target:
            windows.append(current.strip())
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:].lstrip()
                candidate = f"{current} {para}".strip()
            else:
                candidate = para
        current = candidate
        if len(current) >= target:
            windows.append(current.strip())
            current = current[-overlap:].lstrip() if overlap else ""
    if current.strip():
        windows.append(current.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for window in windows:
        key = window.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(window)
    return deduped


def split_sermon_quote_chunks(
    text: str,
    *,
    target_size: int | None = None,
    overlap: int | None = None,
    chunk_kind: str = "sermon_quote",
) -> tuple[list[str], list[dict]]:
    target = max(
        220,
        int(target_size if target_size is not None else os.getenv("INGEST_CHUNK_SIZE", str(_DEFAULT_TARGET))),
    )
    overlap_n = max(
        0,
        int(overlap if overlap is not None else os.getenv("INGEST_CHUNK_OVERLAP", str(_DEFAULT_OVERLAP))),
    )
    paragraphs = _paragraphs(text)
    windows = _pack_windows(paragraphs, target=target, overlap=overlap_n)
    if not windows and (text or "").strip():
        windows = [" ".join(text.split())]
    chunks: list[str] = []
    metas: list[dict] = []
    for window in windows:
        quotes = extract_quote_spans(window)
        quote_text = " | ".join(quotes[:4]) if quotes else spoken_text_without_timestamps(window)
        chunks.append(window.strip())
        metas.append(
            {
                "chunk_kind": chunk_kind,
                "quote_text": quote_text[:1200],
            }
        )
    return chunks, metas


def quote_chunks_from_windows(
    windows: list[str],
    *,
    chunk_kind: str = "sermon_quote",
) -> tuple[list[str], list[dict]]:
    chunks: list[str] = []
    metas: list[dict] = []
    for window in windows:
        cleaned = (window or "").strip()
        if not cleaned:
            continue
        quotes = extract_quote_spans(spoken_text_without_timestamps(cleaned))
        quote_text = " | ".join(quotes[:4]) if quotes else spoken_text_without_timestamps(cleaned)
        chunks.append(cleaned)
        metas.append({"chunk_kind": chunk_kind, "quote_text": quote_text[:1200]})
    return chunks, metas
