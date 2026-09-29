"""Dry-run the admin Document Ingestion path for local .txt/.md files.

Mirrors production ``ingest_uploaded_files`` for text uploads through cleanup,
title prettify, quote-chunking, and scripture-ref indexing. Does not write
Qdrant, Postgres, or library PDFs.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from core.bible_refs import scripture_refs_from_text
from core.document_cleanup import clean_extracted_document, clean_markdown_document, format_cleanup_log
from core.document_titles import normalize_title_key, prettify_title
from core.quote_chunking import split_sermon_quote_chunks

BIBLE_SOURCE_MARKERS = tuple(
    marker.strip().lower()
    for marker in os.environ.get(
        "BIBLE_SOURCE_MARKERS",
        "bible,nkjv,king james,new testament,old testament,scripture",
    ).split(",")
    if marker.strip()
)

_JUNK_RE = re.compile(
    r"(Dedication|Acknowledgments|About the Author|Works Cited|"
    r"Resources for Further Study|All rights reserved|ISBN|P\.O\. Box|"
    r"thenordins|Connect with Susan|@SusanNordin|/snordin|"
    r"polarisproject|pewresearch|blueletterbible|torahresource)",
    re.I,
)

_STOPWORDS = frozenset(
    "a an the and or of to for in on with what how why is are was were be "
    "this that it my your our me i you we they them their from about".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']{2,}")


def _decode_text_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _to_markdown(title: str, body: str) -> str:
    return f"# {title}\n\n{body.strip()}\n"


def _is_bible_source(filename: str) -> bool:
    normalized = filename.lower()
    return any(marker in normalized for marker in BIBLE_SOURCE_MARKERS)


def _tokens(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "") if tok.lower() not in _STOPWORDS}


@dataclass
class PreviewHit:
    query: str
    chunk_index: int
    score: float
    excerpt: str


@dataclass
class DocumentIngestPreview:
    upload_name: str
    library_pdf_name: str
    title: str
    normalized_title: str
    original_extension: str
    is_bible: bool
    splitter: str
    file_hash: str
    content_hash: str
    cleanup_log: str
    raw_chars: int
    cleaned_chars: int
    chunk_count: int
    chunk_min: int = 0
    chunk_median: int = 0
    chunk_max: int = 0
    large_chunk_count: int = 0
    scripture_refs: list[str] = field(default_factory=list)
    leftover_junk: list[str] = field(default_factory=list)
    first_chunk: str = ""
    last_chunk: str = ""
    warnings: list[str] = field(default_factory=list)
    retrieval_hits: list[PreviewHit] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list, repr=False)


def _lexical_hits(chunks: list[str], queries: list[str], *, limit: int = 2) -> list[PreviewHit]:
    hits: list[PreviewHit] = []
    for query in queries:
        q_tokens = _tokens(query)
        if not q_tokens:
            continue
        scored: list[tuple[float, int]] = []
        for idx, chunk in enumerate(chunks):
            c_tokens = _tokens(chunk)
            overlap = q_tokens & c_tokens
            if not overlap:
                continue
            score = len(overlap) / len(q_tokens)
            scored.append((score, idx))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for score, idx in scored[:limit]:
            excerpt = " ".join(chunks[idx].split())
            hits.append(
                PreviewHit(
                    query=query,
                    chunk_index=idx,
                    score=round(score, 3),
                    excerpt=excerpt[:220],
                )
            )
    return hits


def preview_text_upload(
    path: Path,
    *,
    upload_name: str | None = None,
    queries: list[str] | None = None,
    large_chunk_chars: int = 2000,
) -> DocumentIngestPreview:
    """Run the production .txt/.md ingest path without writing storage."""
    source = Path(path)
    raw_bytes = source.read_bytes()
    name = upload_name or source.name
    extension = Path(name).suffix.lower() or source.suffix.lower()
    extracted_text = _decode_text_bytes(raw_bytes)
    title = prettify_title(name)
    is_bible = _is_bible_source(name)

    if is_bible:
        cleaned_text = re.sub(r"\n{3,}", "\n\n", extracted_text.replace("\r\n", "\n").replace("\r", "\n")).strip()
        cleanup_log = "Skipped sermon-style cleanup for Bible source."
        splitter = "bible_verse"
    elif extension == ".md":
        result = clean_markdown_document(extracted_text)
        cleaned_text = result.text
        cleanup_log = format_cleanup_log(result.stats, source_label=name)
        splitter = "sermon_quote"
    else:
        result = clean_extracted_document(extracted_text, title=title, source_name=name)
        cleaned_text = result.text
        cleanup_log = format_cleanup_log(result.stats, source_label=name)
        splitter = "sermon_quote"

    markdown_text = _to_markdown(title, cleaned_text)
    if splitter == "bible_verse":
        # Preview stays on the sermon splitter; Bible files are rejected from this helper.
        chunks, _metas = split_sermon_quote_chunks(markdown_text)
    else:
        chunks, _metas = split_sermon_quote_chunks(markdown_text)

    lengths = [len(chunk) for chunk in chunks] or [0]
    leftover = sorted({match.group(0) for match in _JUNK_RE.finditer(cleaned_text)})
    refs = [] if is_bible else scripture_refs_from_text(f"{title}\n{cleaned_text}")
    warnings: list[str] = []
    if leftover:
        warnings.append("Packaging/junk phrases still present in cleaned text.")
    if title.lower().endswith(" full"):
        warnings.append(
            f'Library title is “{title}” because the filename word “Transcript” is stripped and “Full” remains.'
        )
    large_count = sum(1 for length in lengths if length >= large_chunk_chars)
    if large_count:
        warnings.append(
            f"{large_count} chunk(s) are {large_chunk_chars}+ chars (a long paragraph becomes one retrieval window)."
        )
    if is_bible:
        warnings.append("Filename looks like a Bible source; production would use verse-level NKJV splitting.")

    return DocumentIngestPreview(
        upload_name=name,
        library_pdf_name=f"{Path(name).stem.strip() or 'document'}.pdf",
        title=title,
        normalized_title=normalize_title_key(name),
        original_extension=extension or ".txt",
        is_bible=is_bible,
        splitter=splitter,
        file_hash=hashlib.sha256(raw_bytes).hexdigest(),
        content_hash=hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest(),
        cleanup_log=cleanup_log,
        raw_chars=len(extracted_text),
        cleaned_chars=len(cleaned_text),
        chunk_count=len(chunks),
        chunk_min=min(lengths),
        chunk_median=int(statistics.median(lengths)),
        chunk_max=max(lengths),
        large_chunk_count=large_count,
        scripture_refs=refs,
        leftover_junk=leftover,
        first_chunk=" ".join((chunks[0] if chunks else "").split())[:280],
        last_chunk=" ".join((chunks[-1] if chunks else "").split())[:280],
        warnings=warnings,
        retrieval_hits=_lexical_hits(chunks, queries or []),
        chunks=chunks,
    )


def format_preview(preview: DocumentIngestPreview) -> str:
    lines = [
        f"== {preview.upload_name} ==",
        f"library PDF name: {preview.library_pdf_name}",
        f"display title: {preview.title}",
        f"bible splitter: {preview.is_bible} ({preview.splitter})",
        preview.cleanup_log,
        (
            f"chars: raw {preview.raw_chars} -> cleaned {preview.cleaned_chars}; "
            f"chunks {preview.chunk_count} "
            f"(min/med/max {preview.chunk_min}/{preview.chunk_median}/{preview.chunk_max})"
        ),
        f"scripture refs indexed: {len(preview.scripture_refs)}"
        + (f" e.g. {', '.join(preview.scripture_refs[:8])}" if preview.scripture_refs else ""),
        f"leftover junk: {preview.leftover_junk or 'none'}",
        f"first chunk: {preview.first_chunk}",
        f"last chunk: {preview.last_chunk}",
    ]
    if preview.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {item}" for item in preview.warnings)
    if preview.retrieval_hits:
        lines.append("lexical retrieval dry-run (not BGE vectors):")
        current = None
        for hit in preview.retrieval_hits:
            if hit.query != current:
                lines.append(f'  query: "{hit.query}"')
                current = hit.query
            lines.append(f"    chunk {hit.chunk_index} score={hit.score} {hit.excerpt}")
    return "\n".join(lines)


def default_queries_for(name: str) -> list[str]:
    lowered = name.lower()
    if "know your why" in lowered:
        return [
            "what is my God given purpose",
            "what is a rhema word",
            "Your word have I hidden in my heart",
        ]
    if "advent" in lowered:
        return [
            "who is Immanuel",
            "why was Jesus born in Bethlehem",
            "Prince of Peace",
        ]
    if "determined mom" in lowered:
        return [
            "how can I be a determined mom",
            "motherhood is a calling",
            "the buck stops here with parents",
        ]
    return ["what does this book teach"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run admin Document Ingestion for local .txt/.md files (no Qdrant writes)."
    )
    parser.add_argument("files", nargs="+", help="Transcript files to preview.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Optional lexical retrieval probe. Repeatable. Defaults depend on the filename.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reports: list[str] = []
    for raw_path in args.files:
        path = Path(raw_path)
        if not path.is_file():
            raise SystemExit(f"File not found: {path}")
        queries = list(args.query) or default_queries_for(path.name)
        preview = preview_text_upload(path, queries=queries)
        reports.append(format_preview(preview))
    print("\n\n".join(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
