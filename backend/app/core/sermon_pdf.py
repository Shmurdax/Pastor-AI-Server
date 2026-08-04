"""
Build inline sermon PDFs from Qdrant chunks when no uploaded PDF exists.

Chat sources come from Qdrant markdown ingestion (`*.md`). The Flutter UI expects
clicking a sermon to open `/sermons/<name>.pdf`. This module reconstructs a
readable PDF from stored chunk text for that source.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

import os

from fpdf import FPDF

logger = logging.getLogger(__name__)

MAX_CHUNKS = int(os.environ.get("SERMON_PDF_MAX_CHUNKS", "250"))
MAX_CHARS = int(os.environ.get("SERMON_PDF_MAX_CHARS", "120000"))
SCROLL_PAGE_SIZE = 64


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://127.0.0.1:6333")


def _collection_name() -> str:
    return os.getenv("QDRANT_COLLECTION", "sermon_brain")


def _source_candidates(sermon_name: str) -> List[str]:
    raw = (sermon_name or "").strip()
    if not raw:
        return []
    stem = Path(raw).stem if Path(raw).suffix.lower() in {".pdf", ".md", ".docx"} else raw
    stem = stem.strip()
    if not stem:
        return []
    # Prefer exact stem variants chat / ingest commonly emit.
    ordered = [
        f"{stem}.md",
        f"{stem}.pdf",
        stem,
        raw,
    ]
    seen = set()
    out: List[str] = []
    for item in ordered:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _payload_text(payload: dict) -> str:
    if not payload:
        return ""
    for key in ("page_content", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("page_content", "text", "content"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _payload_source(payload: dict) -> str:
    if not payload:
        return ""
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("source"):
        return str(metadata["source"])
    for key in ("source", "source_name", "file_name", "filename"):
        if payload.get(key):
            return str(payload[key])
    return ""


def _scroll_chunks_for_source(
    client,
    collection: str,
    source_name: str,
    *,
    limit: int,
) -> List[str]:
    from qdrant_client.http import models as qdrant_models

    chunks: List[str] = []
    # langchain-qdrant stores document metadata under payload.metadata.*
    filters = [
        qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="metadata.source",
                    match=qdrant_models.MatchValue(value=source_name),
                )
            ]
        ),
        qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="source",
                    match=qdrant_models.MatchValue(value=source_name),
                )
            ]
        ),
    ]

    for qfilter in filters:
        next_offset = None
        while len(chunks) < limit:
            points, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=qfilter,
                limit=min(SCROLL_PAGE_SIZE, limit - len(chunks)),
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for point in points:
                text = _payload_text(point.payload or {})
                if text:
                    chunks.append(text)
                if len(chunks) >= limit:
                    break
            if next_offset is None:
                break
        if chunks:
            return chunks
    return chunks


def fetch_sermon_text_from_qdrant(sermon_name: str) -> Optional[tuple[str, str, bool]]:
    """
    Return (title, body_text, truncated) for a sermon source, or None if missing.
    """
    candidates = _source_candidates(sermon_name)
    if not candidates:
        return None

    from qdrant_client import QdrantClient

    client = QdrantClient(url=_qdrant_url(), prefer_grpc=False)
    collection = _collection_name()
    try:
        collections = {c.name for c in client.get_collections().collections}
    except Exception as exc:
        logger.warning("Qdrant unavailable while building sermon PDF: %s", exc)
        return None
    if collection not in collections:
        return None

    for source_name in candidates:
        chunks = _scroll_chunks_for_source(
            client, collection, source_name, limit=MAX_CHUNKS + 1
        )
        if not chunks:
            continue
        truncated = len(chunks) > MAX_CHUNKS
        chunks = chunks[:MAX_CHUNKS]
        # Light de-dupe while preserving order (overlap from chunking).
        deduped: List[str] = []
        seen = set()
        for chunk in chunks:
            key = re.sub(r"\s+", " ", chunk).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(chunk)
        body = "\n\n".join(deduped).strip()
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS].rstrip() + "\n\n[… truncated …]"
            truncated = True
        title = Path(source_name).stem
        return title, body, truncated

    return None


def _pdf_safe(text: str) -> str:
    # Core PDF fonts are Latin-1; keep sermon notes readable without bundling fonts.
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("latin-1", "replace").decode("latin-1")


def build_sermon_pdf_bytes(title: str, body: str, *, truncated: bool = False) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, _pdf_safe(title))
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    if truncated:
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(
            0,
            5,
            "Note: this PDF was reconstructed from indexed sermon notes and may be truncated.",
        )
        pdf.ln(2)
        pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _pdf_safe(body))
    # fpdf2 returns bytearray when no filename is provided.
    return bytes(pdf.output())


def sermon_pdf_from_qdrant(sermon_name: str) -> Optional[tuple[str, bytes]]:
    fetched = fetch_sermon_text_from_qdrant(sermon_name)
    if not fetched:
        return None
    title, body, truncated = fetched
    if not body.strip():
        return None
    filename = f"{title}.pdf"
    return filename, build_sermon_pdf_bytes(title, body, truncated=truncated)
