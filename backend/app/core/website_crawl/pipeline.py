"""Crawl allowlisted ministry sites and ingest into Qdrant via existing pipeline helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from django.conf import settings
from django.utils import timezone

from ..ingestion_service import ingest_markdown_documents, ingest_uploaded_files
from ..models import IngestionJob, IngestionJobLog
from .crawler import CrawlResult, WebsiteCrawler

logger = logging.getLogger(__name__)

LogFn = Optional[Callable[[str], None]]


@dataclass
class CrawlIngestResult:
    pages_fetched: int = 0
    pages_ingested: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    pdfs_fetched: int = 0
    pdfs_ingested: int = 0
    pdfs_failed: int = 0
    chunks_created: int = 0
    markdown_paths: List[str] = field(default_factory=list)
    domains_touched: List[str] = field(default_factory=list)
    job_id: Optional[int] = None


class _BytesUpload:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def read(self) -> bytes:
        return self._content


def _website_output_dir() -> Path:
    path = Path(settings.BASE_DIR) / "uploads" / "website_crawl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_markdown_pages(crawl: CrawlResult, log_fn: LogFn) -> List[Path]:
    out_dir = _website_output_dir()
    written: List[Path] = []
    for page in crawl.pages:
        path = out_dir / page.source_name
        path.write_text(page.markdown, encoding="utf-8")
        written.append(path)
        if log_fn:
            log_fn(f"Wrote markdown: {path.name}")
    return written


def run_website_crawl_and_ingest(
    *,
    replace_existing_sources: bool = True,
    log_fn: LogFn = None,
    job: Optional[IngestionJob] = None,
    delay_s: float = 0.35,
    respect_robots: bool = True,
) -> CrawlIngestResult:
    """
    Synchronous crawl + ingest.

    Markdown pages are ingested via ``ingest_markdown_documents``.
    Linked public PDFs are ingested via ``ingest_uploaded_files``.
    """

    def _log(message: str) -> None:
        if log_fn:
            log_fn(message)
        if job is not None:
            IngestionJobLog.objects.create(job=job, message=message)
        logger.info(message)

    crawler = WebsiteCrawler(delay_s=delay_s, log_fn=_log, respect_robots=respect_robots)
    crawl = crawler.crawl()

    result = CrawlIngestResult(
        pages_fetched=crawl.pages_fetched,
        pages_skipped=crawl.pages_skipped,
        pages_failed=crawl.pages_failed,
        pdfs_fetched=crawl.pdfs_fetched,
        pdfs_failed=crawl.pdfs_failed,
        domains_touched=sorted(crawl.domains_touched),
        job_id=job.id if job else None,
    )

    markdown_paths = _write_markdown_pages(crawl, _log)
    result.markdown_paths = [str(p) for p in markdown_paths]

    if markdown_paths:
        _log(f"Ingesting {len(markdown_paths)} markdown page(s) into Qdrant…")
        md_docs = []
        for page, path in zip(crawl.pages, markdown_paths):
            md_docs.append(
                {
                    "source_name": page.source_name,
                    "title": page.title,
                    "text": path.read_text(encoding="utf-8"),
                    "url": page.url,
                    "content_type": page.content_type,
                    "ministry": page.ministry_label,
                    "domain": page.domain,
                }
            )
        md_result = ingest_markdown_documents(
            md_docs,
            replace_existing_sources=replace_existing_sources,
            log_fn=_log,
            job=job,
        )
        result.pages_ingested = md_result.files_processed
        result.chunks_created += md_result.chunks_created
        result.pages_failed += md_result.files_failed
    else:
        _log("No markdown pages to ingest.")

    if crawl.pdfs:
        _log(f"Ingesting {len(crawl.pdfs)} PDF resource(s)…")
        uploads = []
        for pdf in crawl.pdfs:
            # Prefer stable web__ source names so re-crawls replace cleanly.
            uploads.append(_BytesUpload(pdf.source_name, pdf.content))
            # Persist a copy under website_crawl for audit.
            pdf_path = _website_output_dir() / pdf.source_name
            pdf_path.write_bytes(pdf.content)
        pdf_result = ingest_uploaded_files(
            uploads,
            replace_existing_sources=replace_existing_sources,
            log_fn=_log,
            job=job,
            extra_metadata_by_name={
                pdf.source_name: {
                    "url": pdf.url,
                    "content_type": "pdf_resource",
                    "ministry": pdf.ministry_label,
                    "domain": pdf.domain,
                }
                for pdf in crawl.pdfs
            },
        )
        result.pdfs_ingested = pdf_result.files_processed
        result.chunks_created += pdf_result.chunks_created
        result.pdfs_failed += pdf_result.files_failed
    else:
        _log("No PDF resources discovered.")

    _log(
        "Website crawl ingest summary: "
        f"pages_fetched={result.pages_fetched}, pages_ingested={result.pages_ingested}, "
        f"pdfs_fetched={result.pdfs_fetched}, pdfs_ingested={result.pdfs_ingested}, "
        f"chunks_created={result.chunks_created}, domains={','.join(result.domains_touched)}"
    )
    return result


def enqueue_website_crawl_job(
    *,
    started_by: str,
    replace_existing_sources: bool = True,
) -> IngestionJob:
    """Queue a background crawl+ingest job using the existing ingestion worker pool."""
    from .tasks import enqueue_website_crawl

    job = IngestionJob.objects.create(
        started_by=started_by,
        job_kind="website",
        replace_existing_sources=replace_existing_sources,
        status="running",
        files_received=0,
    )
    IngestionJobLog.objects.create(job=job, message="Website crawl job queued for background processing.")
    enqueue_website_crawl(job_id=job.id, replace_existing_sources=replace_existing_sources)
    return job
