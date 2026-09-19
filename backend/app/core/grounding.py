"""Extractive grounding: allowed sermon quotes, NKJV lookup, and answer verification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from .bible_refs import canonical_book_key, format_verse_ref, parse_verse_refs
from .chat_retrieval import (
    chunk_text,
    extract_used_quotes,
    extract_used_verse_refs,
    is_bible_source,
    metadata_source_hint,
)
from .quote_chunking import extract_quote_spans, spoken_text_without_timestamps

logger = logging.getLogger(__name__)

_QUOTE_RE = re.compile(r"[\"“](.{12,400}?)[\"”]")
_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)


def normalize_grounding_text(text: str) -> str:
    folded = (text or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    folded = _MARKUP_RE.sub(" ", folded)
    folded = _PUNCT_RE.sub(" ", folded.lower())
    return _SPACE_RE.sub(" ", folded).strip()


def _metadata(doc: Any) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def _is_bible_doc(doc: Any) -> bool:
    meta = _metadata(doc)
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    return is_bible_source(metadata_source_hint(doc) or str(meta.get("source") or ""))


def collect_allowed_sermon_quotes(docs: Iterable[Any], *, limit: int = 12) -> list[str]:
    """Exact lines the model may quote as Pastor Don / Susan."""
    quotes: list[str] = []
    seen: set[str] = set()
    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        kind = str(meta.get("chunk_kind") or "").lower()
        if "overview" in kind:
            continue
        stored = str(meta.get("quote_text") or "").strip()
        body = spoken_text_without_timestamps(chunk_text(doc))
        candidates = []
        if stored:
            candidates.extend(part.strip() for part in stored.split(" | ") if part.strip())
        candidates.extend(extract_quote_spans(body))
        if body and len(body) >= 40:
            candidates.append(body)
        for item in candidates:
            cleaned = " ".join(item.split())
            key = normalize_grounding_text(cleaned)
            if len(cleaned) < 12 or key in seen:
                continue
            seen.add(key)
            quotes.append(cleaned)
            if len(quotes) >= limit:
                return quotes
    return quotes


def collect_allowed_nkjv(docs: Iterable[Any], *, limit: int = 12) -> list[tuple[str, str]]:
    """(ref, exact NKJV wording) pairs from retrieved or looked-up Bible chunks."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc in docs or []:
        if not _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        ref = str(meta.get("verse_ref") or "").strip()
        if not ref:
            book = meta.get("book")
            chapter = meta.get("chapter")
            start = meta.get("verse_start")
            if book and chapter and start:
                ref = format_verse_ref(book, int(chapter), int(start), verse_end=meta.get("verse_end"))
        wording = str(meta.get("quote_text") or "").strip() or spoken_text_without_timestamps(chunk_text(doc))
        wording = " ".join(wording.split())
        if len(wording) < 8:
            continue
        key = normalize_grounding_text(f"{ref}|{wording}")
        if key in seen:
            continue
        seen.add(key)
        pairs.append((ref or "NKJV", wording))
        if len(pairs) >= limit:
            break
    return pairs


def sermon_note_corpus(docs: Iterable[Any]) -> str:
    parts = []
    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        parts.append(spoken_text_without_timestamps(chunk_text(doc)))
        quote_text = str(_metadata(doc).get("quote_text") or "")
        if quote_text:
            parts.append(quote_text.replace(" | ", " "))
    return " ".join(parts)


def nkjv_corpus(docs: Iterable[Any]) -> str:
    parts = []
    for doc in docs or []:
        if not _is_bible_doc(doc):
            continue
        parts.append(str(_metadata(doc).get("quote_text") or ""))
        parts.append(chunk_text(doc))
    return " ".join(parts)


def text_is_grounded(span: str, corpus: str, *, min_ratio: float = 0.92) -> bool:
    needle = normalize_grounding_text(span)
    hay = normalize_grounding_text(corpus)
    if not needle or len(needle) < 12:
        return True
    if needle in hay:
        return True
    words = needle.split()
    if len(words) < 6:
        return False
    # Allow a short prefix/suffix mismatch from punctuation or NKJV italics.
    probe = " ".join(words[1:-1] if len(words) > 8 else words)
    if len(probe) >= 20 and probe in hay:
        return True
    from difflib import SequenceMatcher

    window = max(len(needle) - 8, 24)
    if len(hay) < 12:
        return False
    best = 0.0
    step = max(12, window // 4)
    for start in range(0, max(1, len(hay) - window + 1), step):
        chunk = hay[start : start + window + 16]
        best = max(best, SequenceMatcher(None, needle, chunk).ratio())
        if best >= min_ratio:
            return True
    return False


@dataclass
class GroundingReport:
    ok: bool
    invented_quotes: list[str] = field(default_factory=list)
    invented_scripture: list[str] = field(default_factory=list)
    missing_nkjv_refs: list[str] = field(default_factory=list)


def verify_answer_grounding(
    answer: str,
    *,
    sermon_docs: Iterable[Any],
    nkjv_docs: Iterable[Any],
) -> GroundingReport:
    notes = sermon_note_corpus(sermon_docs)
    bible = nkjv_corpus(nkjv_docs)
    allowed_refs = {
        canonical_book_key(book) + f"|{chapter}|{verse}"
        for book, chapter, verse in parse_verse_refs(
            " ".join(str(_metadata(doc).get("verse_ref") or "") + " " + chunk_text(doc) for doc in (nkjv_docs or []))
        )
    }
    for doc in nkjv_docs or []:
        meta = _metadata(doc)
        book = canonical_book_key(str(meta.get("book") or ""))
        chapter = meta.get("chapter")
        start = int(meta.get("verse_start") or 0)
        end = int(meta.get("verse_end") or start)
        if book and chapter and start:
            for verse in range(start, max(start, end) + 1):
                allowed_refs.add(f"{book}|{int(chapter)}|{verse}")

    invented_quotes: list[str] = []
    invented_scripture: list[str] = []
    for span in extract_used_quotes([answer]):
        in_notes = text_is_grounded(span, notes)
        in_bible = text_is_grounded(span, bible)
        if in_notes or in_bible:
            continue
        lowered = (span or "").lower()
        if "nkjv" in lowered or parse_verse_refs(span):
            invented_scripture.append(span)
        else:
            invented_quotes.append(span)

    missing_refs: list[str] = []
    for ref in extract_used_verse_refs([answer]):
        parsed = parse_verse_refs(ref)
        if not parsed:
            continue
        book, chapter, verse = parsed[0]
        key = f"{canonical_book_key(book)}|{chapter}|{verse}"
        if allowed_refs and key not in allowed_refs:
            missing_refs.append(ref)
        elif not bible.strip():
            missing_refs.append(ref)

    ok = not invented_quotes and not invented_scripture and not missing_refs
    return GroundingReport(
        ok=ok,
        invented_quotes=invented_quotes,
        invented_scripture=invented_scripture,
        missing_nkjv_refs=missing_refs,
    )


def grounded_fallback_answer(
    quotes: Iterable[str],
    nkjv_pairs: Iterable[tuple[str, str]],
) -> str:
    quote_list = [item.strip() for item in quotes if item and item.strip()]
    nkjv_list = [(ref, text) for ref, text in nkjv_pairs if text and text.strip()]
    parts: list[str] = ["**From the retrieved notes**"]
    if quote_list:
        parts.append("Pastor Don and Susan Nordin teach from the retrieved sermons:")
        for quote in quote_list[:4]:
            parts.append(f'"{quote}"')
    else:
        parts.append(
            "The retrieved sermon notes do not include a usable Pastor Don or Susan quotation for this question."
        )
    if nkjv_list:
        parts.append("**Scripture (NKJV)**")
        for ref, wording in nkjv_list[:4]:
            parts.append(f'{ref} (NKJV): "{wording}"')
    else:
        parts.append("No NKJV verse from the retrieved Bible document applies in this turn.")
    parts.append(
        "I can only teach from these retrieved lines. Ask another question if you want a different passage or sermon."
    )
    return "\n\n".join(parts)


def verse_refs_for_lookup(user_query: str, docs: Iterable[Any], *, limit: int = 8) -> list[tuple[str, int, int]]:
    blobs = [user_query or ""]
    for doc in docs or []:
        blobs.append(chunk_text(doc))
        blobs.append(str(_metadata(doc).get("verse_ref") or ""))
        refs = _metadata(doc).get("scripture_refs") or []
        if isinstance(refs, (list, tuple)):
            blobs.extend(str(item) for item in refs)
    return parse_verse_refs(" ".join(blobs))[:limit]


def _payload_of(point: Any) -> dict:
    payload = getattr(point, "payload", None)
    if isinstance(payload, dict):
        return payload
    return {}


def lookup_nkjv_verses(
    client: Any,
    collection_name: str,
    refs: Iterable[tuple[str, int, int]],
    *,
    retrieved_docs: Optional[Iterable[Any]] = None,
    make_doc: Optional[Callable[[str, dict], Any]] = None,
    limit_per_ref: int = 3,
) -> list[Any]:
    """Return Bible documents for the requested refs from payload lookup or retrieved docs."""
    from types import SimpleNamespace

    factory = make_doc or (
        lambda text, metadata: SimpleNamespace(page_content=text, metadata=metadata)
    )
    found: list[Any] = []
    seen: set[str] = set()

    def add_doc(doc: Any) -> None:
        text = chunk_text(doc)
        key = normalize_grounding_text(text)[:240]
        if not key or key in seen:
            return
        seen.add(key)
        found.append(doc)

    retrieved = [doc for doc in (retrieved_docs or []) if _is_bible_doc(doc)]
    wanted = {(canonical_book_key(book), int(chapter), int(verse)) for book, chapter, verse in refs}

    for doc in retrieved:
        meta = _metadata(doc)
        book = canonical_book_key(str(meta.get("book") or ""))
        chapter = int(meta.get("chapter") or 0)
        start = int(meta.get("verse_start") or 0)
        end = int(meta.get("verse_end") or start)
        if book and chapter and start and any(
            book == w_book and chapter == w_chap and start <= w_verse <= max(start, end)
            for w_book, w_chap, w_verse in wanted
        ):
            add_doc(doc)

    if not wanted:
        return found

    if client is None:
        return found

    from qdrant_client.http import models as qdrant_models

    for book, chapter, verse in list(wanted)[:12]:
        try:
            points, _offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="chunk_kind",
                            match=qdrant_models.MatchValue(value="bible_verse"),
                        ),
                        qdrant_models.FieldCondition(
                            key="book",
                            match=qdrant_models.MatchValue(value=book),
                        ),
                        qdrant_models.FieldCondition(
                            key="chapter",
                            match=qdrant_models.MatchValue(value=int(chapter)),
                        ),
                    ]
                ),
                limit=max(8, limit_per_ref * 4),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            logger.debug("NKJV payload lookup failed for %s %s:%s", book, chapter, verse, exc_info=True)
            points = []
        matched = 0
        for point in points or []:
            payload = _payload_of(point)
            start = int(payload.get("verse_start") or 0)
            end = int(payload.get("verse_end") or start)
            if start and not (start <= verse <= max(start, end)):
                continue
            text = str(payload.get("text") or "").strip()
            if not text:
                continue
            metadata = dict(payload.get("metadata") or {})
            metadata.update({k: v for k, v in payload.items() if k != "metadata"})
            add_doc(factory(text, metadata))
            matched += 1
            if matched >= limit_per_ref:
                break
    return found


GROUNDING_REPAIR_STEER = (
    "A RAG check found quotations or verses that are not in the retrieved notes. "
    "Do not restart or apologize. Do not say Certainly, Let's continue, or Teaching Points. "
    "Drop any quotation or verse that is not copied from ALLOWED SERMON QUOTES or ALLOWED NKJV. "
    "Add at least two word-for-word ALLOWED SERMON QUOTES attributed to Pastor Don or Susan, "
    "and one ALLOWED NKJV verse if that list is not empty."
)


def split_docs_for_grounding(docs: Iterable[Any]) -> tuple[list[Any], list[Any]]:
    sermon: list[Any] = []
    bible: list[Any] = []
    for doc in docs or []:
        if _is_bible_doc(doc):
            bible.append(doc)
        else:
            sermon.append(doc)
    return sermon, bible


def grounding_repair_steer(
    report: GroundingReport,
    quotes: Iterable[str],
    nkjv_pairs: Iterable[tuple[str, str]],
) -> str:
    parts = [GROUNDING_REPAIR_STEER]
    if report.invented_quotes:
        parts.append("Drop these ungrounded quotations:")
        for span in report.invented_quotes[:4]:
            parts.append(f'- "{(span or "")[:220]}"')
    dropped = list(report.invented_scripture) + list(report.missing_nkjv_refs)
    if dropped:
        parts.append("Drop these ungrounded Scripture lines or refs:")
        for span in dropped[:6]:
            parts.append(f"- {(span or '')[:220]}")
    quote_list = [item.strip() for item in quotes if item and str(item).strip()][:4]
    if quote_list:
        parts.append("ALLOWED SERMON QUOTES (copy word-for-word):")
        for quote in quote_list:
            parts.append(f'- "{quote[:240]}"')
    nkjv_list = [
        (str(ref), str(text).strip())
        for ref, text in nkjv_pairs
        if text and str(text).strip()
    ][:4]
    if nkjv_list:
        parts.append("ALLOWED NKJV (copy word-for-word):")
        for ref, wording in nkjv_list:
            parts.append(f'- {ref}: "{wording[:240]}"')
    parts.append("Then stop.")
    return "\n".join(parts)
