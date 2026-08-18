"""
Ingestion pipeline (admin uploads):

1. **Normalize to PDF on disk** — uploads under ``uploads/admin_ingestion`` are always stored as
   ``{original_basename_stem}.pdf``. Incoming PDFs are written as that path; DOCX is written
   temporarily, converted with LibreOffice (``soffice``), then the DOCX is removed.
   These original PDFs are what the sermon library serves; they are never rewritten by cleanup.

2. **Text extraction** — text is read from the PDF with ``pypdf`` (not from DOCX after conversion).

3. **Structured cleanup** — ``document_cleanup.clean_extracted_document`` removes page chrome,
   repeating headers/footers, boilerplate, and soft-wrap artifacts so Qdrant chunks stay coherent.
   Cleanup applies only to extracted text destined for embeddings — not to the on-disk PDF.

4. **Markdown for chunking** — body text is wrapped as ``# {title}\\n\\n{body}`` via ``_to_markdown``
   (title = filename stem, also stored on ``IngestedDocument.title``). The DB stores ``IngestedDocument`` /
   ``IngestedChunk`` metadata; the
   markdown string is what gets split into chunks (not stored as a single DB blob).

5. **Chunk + embed + Qdrant** — ``RecursiveCharacterTextSplitter`` produces chunks; each new chunk
   is embedded (``all-MiniLM-L6-v2``) and upserted into Qdrant with payload ``source`` (PDF filename),
   ``file_hash``, ``chunk_hash``, ``text``, etc. Duplicate chunk hashes are skipped across the corpus.
"""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from django.conf import settings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from .document_cleanup import (
    clean_extracted_document,
    clean_markdown_document,
    format_cleanup_log,
)
from .embeddings_utils import get_embeddings
from .models import IngestedChunk, IngestedDocument, IngestionJob, IngestionJobFileFailure
from .qdrant_utils import collection_exists, ensure_sermon_collection
from .storage_paths import admin_ingestion_dir

try:
    from docx import Document as DocxDocument
except ImportError:  # pragma: no cover - handled at runtime by dependency install
    DocxDocument = None

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    files_received: int = 0
    files_processed: int = 0
    files_skipped_as_duplicates: int = 0
    files_failed: int = 0
    chunks_created: int = 0
    chunks_skipped_as_duplicates: int = 0


@dataclass
class DeletionResult:
    deleted_count: int = 0
    qdrant_failures: int = 0


# Larger chunking for Bible documents keeps the corpus lighter-weight
# (fewer embeddings/points) than sermon-sized uploads.
DEFAULT_SPLITTER_KWARGS = {
    "chunk_size": int(os.environ.get("INGEST_CHUNK_SIZE", "1000")),
    "chunk_overlap": int(os.environ.get("INGEST_CHUNK_OVERLAP", "150")),
    "separators": ["\n\n", "\n", " ", ""],
}
BIBLE_SPLITTER_KWARGS = {
    "chunk_size": int(os.environ.get("BIBLE_INGEST_CHUNK_SIZE", "3000")),
    "chunk_overlap": int(os.environ.get("BIBLE_INGEST_CHUNK_OVERLAP", "150")),
    "separators": ["\n\n", "\n", " ", ""],
}
BIBLE_SOURCE_MARKERS = tuple(
    marker.strip().lower()
    for marker in os.environ.get(
        "BIBLE_SOURCE_MARKERS",
        "bible,nkjv,king james,new testament,old testament,scripture",
    ).split(",")
    if marker.strip()
)


def _clean_text(text: str) -> str:
    """Light whitespace normalize used on individual chunks after splitting."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _prepare_extracted_text_for_qdrant(
    extracted_text: str,
    *,
    title: str,
    source_name: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Run structured cleanup on PDF-extracted text before chunking/embedding.

    Does not touch the original PDF on disk (sermon library links keep serving it).
    """
    result = clean_extracted_document(
        extracted_text,
        title=title,
        source_name=source_name,
    )
    if log_fn:
        log_fn(format_cleanup_log(result.stats, source_label=source_name or title))
    return result.text


def _prepare_markdown_text_for_qdrant(
    markdown_text: str,
    *,
    source_name: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """Lighter structured cleanup for crawl/markdown documents before Qdrant."""
    result = clean_markdown_document(markdown_text)
    if log_fn:
        log_fn(format_cleanup_log(result.stats, source_label=source_name))
    return result.text


def _to_markdown(title: str, body: str) -> str:
    return f"# {title}\n\n{body.strip()}\n"


def _extract_docx_text(file_path: Path) -> str:
    if DocxDocument is None:
        raise RuntimeError("python-docx is not installed.")
    doc = DocxDocument(file_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())


def _extract_pdf_text(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _qdrant_point_id(chunk_hash: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_hash))


def _is_bible_source(filename: str) -> bool:
    normalized = filename.lower()
    return any(marker in normalized for marker in BIBLE_SOURCE_MARKERS)


def _upsert_chunks(
    source_name: str,
    title: str,
    chunks: List[str],
    file_hash: str,
    *,
    document: IngestedDocument,
    embeddings: HuggingFaceEmbeddings,
    qdrant_client: QdrantClient,
    collection_name: str,
    extra_metadata: Optional[dict] = None,
) -> tuple[int, int]:
    if not chunks:
        return 0, 0

    vectors = embeddings.embed_documents(chunks)

    existing_hashes = set(
        IngestedChunk.objects.filter(chunk_hash__in=[_sha256_text(c) for c in chunks]).values_list("chunk_hash", flat=True)
    )

    points = []
    created = 0
    skipped = 0
    extra_metadata = dict(extra_metadata or {})

    for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
        chunk_text = _clean_text(chunk_text)
        if not chunk_text:
            continue

        chunk_hash = _sha256_text(chunk_text)
        if chunk_hash in existing_hashes:
            skipped += 1
            continue

        point_id = _qdrant_point_id(chunk_hash)
        nested_metadata = {
            "source": source_name,
            "title": title,
            "file_hash": file_hash,
            "chunk_hash": chunk_hash,
            "position": idx,
            **extra_metadata,
        }
        payload = {
            "source": source_name,
            "title": title,
            "file_hash": file_hash,
            "chunk_hash": chunk_hash,
            "position": idx,
            "text": chunk_text,
            **extra_metadata,
            # Keep metadata nested for vectorstore configs expecting metadata payloads.
            "metadata": nested_metadata,
        }

        points.append(
            qdrant_models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )

        IngestedChunk.objects.create(
            document=document,
            chunk_hash=chunk_hash,
            qdrant_point_id=point_id,
            source_name=source_name,
            position=idx,
        )
        created += 1

    if points:
        retry_count = int(os.environ.get("INGEST_QDRANT_UPSERT_RETRIES", "3"))
        retry_delay_s = float(os.environ.get("INGEST_QDRANT_UPSERT_RETRY_DELAY_S", "2"))
        for attempt in range(1, retry_count + 1):
            try:
                qdrant_client.upsert(collection_name=collection_name, points=points, wait=True)
                break
            except Exception:
                if attempt >= retry_count:
                    raise
                time.sleep(retry_delay_s)

    return created, skipped


def _delete_source_from_qdrant(source_name: str) -> None:
    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
    client = QdrantClient(url=qdrant_url)
    if not collection_exists(client, collection_name):
        return
    client.delete(
        collection_name=collection_name,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[qdrant_models.FieldCondition(key="source", match=qdrant_models.MatchValue(value=source_name))]
            )
        ),
        wait=True,
    )


def _delete_document_from_qdrant(source_name: str, file_hash: str) -> None:
    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
    client = QdrantClient(url=qdrant_url)
    if not collection_exists(client, collection_name):
        return
    client.delete(
        collection_name=collection_name,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(key="source", match=qdrant_models.MatchValue(value=source_name)),
                    qdrant_models.FieldCondition(key="file_hash", match=qdrant_models.MatchValue(value=file_hash)),
                ]
            )
        ),
        wait=True,
    )


def _safe_upload_stem(original_name: str) -> str:
    stem = Path(original_name).stem.strip()
    return stem if stem else "document"


def _canonical_pdf_name(original_name: str) -> str:
    return f"{_safe_upload_stem(original_name)}.pdf"


def _replace_existing_for_upload(original_name: str) -> None:
    """Remove prior rows/vectors for the same logical document (DOCX or PDF naming)."""
    stem = _safe_upload_stem(original_name)
    candidates = {original_name, f"{stem}.pdf", f"{stem}.docx"}
    for name in candidates:
        if not IngestedDocument.objects.filter(source_name=name).exists():
            continue
        _delete_source_from_qdrant(name)
        IngestedDocument.objects.filter(source_name=name).delete()


def _convert_docx_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    from .docx_to_pdf import convert_docx_to_pdf

    convert_docx_to_pdf(docx_path, pdf_path)


def delete_ingested_documents(documents) -> DeletionResult:
    result = DeletionResult()
    for document in documents:
        try:
            _delete_document_from_qdrant(document.source_name, document.file_hash)
        except Exception as exc:
            result.qdrant_failures += 1
            logger.warning(
                "Qdrant delete failed for source '%s' (hash=%s): %s",
                document.source_name,
                document.file_hash,
                exc,
            )
        document.delete()
        result.deleted_count += 1
    return result


def _persist_job_progress(job: Optional[IngestionJob], result: IngestionResult) -> None:
    if job is None:
        return
    job.files_received = result.files_received
    job.files_processed = result.files_processed
    job.files_skipped_as_duplicates = result.files_skipped_as_duplicates
    job.files_failed = result.files_failed
    job.chunks_created = result.chunks_created
    job.chunks_skipped_as_duplicates = result.chunks_skipped_as_duplicates
    job.save(
        update_fields=[
            "files_received",
            "files_processed",
            "files_skipped_as_duplicates",
            "files_failed",
            "chunks_created",
            "chunks_skipped_as_duplicates",
        ]
    )


def ingest_uploaded_files(
    uploaded_files,
    replace_existing_sources: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
    job: Optional[IngestionJob] = None,
    extra_metadata_by_name: Optional[dict] = None,
) -> IngestionResult:
    result = IngestionResult(files_received=len(uploaded_files))
    extra_metadata_by_name = extra_metadata_by_name or {}

    upload_dir = admin_ingestion_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    default_splitter = RecursiveCharacterTextSplitter(**DEFAULT_SPLITTER_KWARGS)
    bible_splitter = RecursiveCharacterTextSplitter(**BIBLE_SPLITTER_KWARGS)
    # CPU embeddings — vLLM already owns GPU VRAM; CUDA MiniLM causes OOM mid-ingest.
    embeddings = get_embeddings()
    qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
    collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
    ensure_sermon_collection(qdrant_client, collection_name)

    for upload in uploaded_files:
        try:
            extension = Path(upload.name).suffix.lower()
            if extension not in {".pdf", ".docx"}:
                if log_fn:
                    log_fn(f"Skipped unsupported file type: {upload.name}")
                continue

            if log_fn:
                log_fn(f"Processing file: {upload.name}")

            if replace_existing_sources:
                _replace_existing_for_upload(upload.name)
                if log_fn:
                    log_fn(f"Replaced previous source data for: {upload.name}")

            raw_content = upload.read()
            file_hash = _sha256_bytes(raw_content)

            if IngestedDocument.objects.filter(file_hash=file_hash).exists():
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Duplicate file skipped by hash: {upload.name}")
                _persist_job_progress(job, result)
                continue

            pdf_name = _canonical_pdf_name(upload.name)
            pdf_path = upload_dir / pdf_name

            if extension == ".pdf":
                with open(pdf_path, "wb") as out:
                    out.write(raw_content)
            else:
                docx_path = upload_dir / f"{_safe_upload_stem(upload.name)}.docx"
                with open(docx_path, "wb") as out:
                    out.write(raw_content)
                if log_fn:
                    log_fn(f"Converting DOCX to PDF: {docx_path.name} -> {pdf_name}")
                _convert_docx_to_pdf(docx_path, pdf_path)
                docx_path.unlink(missing_ok=True)

            # Persist the original/converted PDF first so sermon-library links always
            # have a file even if later text cleanup or chunking fails mid-way.
            # Cleanup below only mutates extracted text for Qdrant — never this PDF.
            extracted_text = _extract_pdf_text(pdf_path)
            title = _safe_upload_stem(upload.name)
            cleaned_text = _prepare_extracted_text_for_qdrant(
                extracted_text,
                title=title,
                source_name=pdf_name,
                log_fn=log_fn,
            )
            if not cleaned_text:
                pdf_path.unlink(missing_ok=True)
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"File had no extractable text and was skipped: {upload.name}")
                _persist_job_progress(job, result)
                continue

            markdown_text = _to_markdown(title, cleaned_text)
            use_bible_splitter = _is_bible_source(upload.name)
            splitter = bible_splitter if use_bible_splitter else default_splitter
            if log_fn and use_bible_splitter:
                log_fn(
                    "Bible source detected; using Bible splitter "
                    f"(chunk_size={BIBLE_SPLITTER_KWARGS['chunk_size']}, "
                    f"overlap={BIBLE_SPLITTER_KWARGS['chunk_overlap']})."
                )
            chunks = [_clean_text(c) for c in splitter.split_text(markdown_text) if _clean_text(c)]

            doc = IngestedDocument.objects.create(
                source_name=pdf_name,
                title=title,
                file_hash=file_hash,
                original_extension=extension,
            )

            try:
                created, skipped = _upsert_chunks(
                    pdf_name,
                    title,
                    chunks,
                    file_hash,
                    document=doc,
                    embeddings=embeddings,
                    qdrant_client=qdrant_client,
                    collection_name=collection_name,
                    extra_metadata=extra_metadata_by_name.get(upload.name)
                    or extra_metadata_by_name.get(pdf_name),
                )
            except Exception:
                # Keep corpus consistent: if vector upsert fails, remove DB rows for this doc.
                doc.delete()
                raise

            doc.chunk_count = created
            doc.save(update_fields=["chunk_count", "updated_at"])

            result.files_processed += 1
            result.chunks_created += created
            result.chunks_skipped_as_duplicates += skipped
            if log_fn:
                log_fn(
                    f"Ingested {upload.name} as {pdf_name}: created {created} chunks, skipped {skipped} duplicates."
                )
            _persist_job_progress(job, result)
        except Exception as exc:
            # Cleanup any partial artifacts and continue with the rest of the batch.
            try:
                pdf_name = _canonical_pdf_name(upload.name)
                (upload_dir / pdf_name).unlink(missing_ok=True)
                (upload_dir / f"{_safe_upload_stem(upload.name)}.docx").unlink(missing_ok=True)
            except Exception:
                pass

            result.files_failed += 1
            if job is not None:
                IngestionJobFileFailure.objects.create(
                    job=job,
                    original_name=upload.name,
                    error_message=str(exc),
                )
            if log_fn:
                log_fn(f"Ingestion failed for {upload.name}: {exc}")
            logger.exception("Ingestion failed for %s", upload.name)
            _persist_job_progress(job, result)
            continue

    _persist_job_progress(job, result)

    return result


def ingest_markdown_documents(
    documents: List[dict],
    replace_existing_sources: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
    job: Optional[IngestionJob] = None,
) -> IngestionResult:
    """
    Ingest pre-built markdown documents (e.g. website crawl pages).

    Each item in ``documents`` should include:
      - source_name (str, ideally ending in .md)
      - title (str)
      - text (str, full markdown)
    Optional metadata keys: url, content_type, ministry, domain
    """
    result = IngestionResult(files_received=len(documents))

    default_splitter = RecursiveCharacterTextSplitter(**DEFAULT_SPLITTER_KWARGS)
    # CPU embeddings — vLLM already owns GPU VRAM; CUDA MiniLM causes OOM mid-ingest.
    embeddings = get_embeddings()
    qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
    collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
    ensure_sermon_collection(qdrant_client, collection_name)

    for item in documents:
        source_name = str(item.get("source_name") or "").strip()
        title = str(item.get("title") or Path(source_name).stem or "document").strip()
        text = str(item.get("text") or "")
        try:
            if not source_name:
                raise ValueError("markdown document missing source_name")
            if log_fn:
                log_fn(f"Processing markdown: {source_name}")

            if replace_existing_sources:
                if IngestedDocument.objects.filter(source_name=source_name).exists():
                    _delete_source_from_qdrant(source_name)
                    IngestedDocument.objects.filter(source_name=source_name).delete()
                    if log_fn:
                        log_fn(f"Replaced previous source data for: {source_name}")

            cleaned_text = _prepare_markdown_text_for_qdrant(
                text,
                source_name=source_name,
                log_fn=log_fn,
            )
            if not cleaned_text:
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Markdown had no text and was skipped: {source_name}")
                _persist_job_progress(job, result)
                continue

            file_hash = _sha256_text(cleaned_text)
            if IngestedDocument.objects.filter(file_hash=file_hash).exists():
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Duplicate markdown skipped by hash: {source_name}")
                _persist_job_progress(job, result)
                continue

            chunks = [_clean_text(c) for c in default_splitter.split_text(cleaned_text) if _clean_text(c)]
            doc = IngestedDocument.objects.create(
                source_name=source_name,
                title=title,
                file_hash=file_hash,
                original_extension=".md",
            )
            extra_metadata = {
                key: value
                for key, value in {
                    "url": item.get("url"),
                    "content_type": item.get("content_type") or "website_page",
                    "ministry": item.get("ministry"),
                    "domain": item.get("domain"),
                }.items()
                if value
            }
            try:
                created, skipped = _upsert_chunks(
                    source_name,
                    title,
                    chunks,
                    file_hash,
                    document=doc,
                    embeddings=embeddings,
                    qdrant_client=qdrant_client,
                    collection_name=collection_name,
                    extra_metadata=extra_metadata,
                )
            except Exception:
                doc.delete()
                raise

            doc.chunk_count = created
            doc.save(update_fields=["chunk_count", "updated_at"])
            result.files_processed += 1
            result.chunks_created += created
            result.chunks_skipped_as_duplicates += skipped
            if log_fn:
                log_fn(
                    f"Ingested markdown {source_name}: created {created} chunks, skipped {skipped} duplicates."
                )
            _persist_job_progress(job, result)
        except Exception as exc:
            result.files_failed += 1
            if job is not None:
                IngestionJobFileFailure.objects.create(
                    job=job,
                    original_name=source_name or title or "markdown",
                    error_message=str(exc),
                )
            if log_fn:
                log_fn(f"Ingestion failed for markdown {source_name or title}: {exc}")
            logger.exception("Markdown ingestion failed for %s", source_name or title)
            _persist_job_progress(job, result)
            continue

    _persist_job_progress(job, result)
    return result
