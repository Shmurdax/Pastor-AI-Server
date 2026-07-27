"""Background worker entry for website crawl + RAG ingest."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from ..ingestion_tasks import _wait_for_turn
from ..models import IngestionJob, IngestionJobLog

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("WEBSITE_CRAWL_BACKGROUND_WORKERS", "1")))


def enqueue_website_crawl(*, job_id: int, replace_existing_sources: bool) -> None:
    _executor.submit(_run_website_crawl_job, job_id, replace_existing_sources)


def _run_website_crawl_job(job_id: int, replace_existing_sources: bool) -> None:
    close_old_connections()
    try:
        job = IngestionJob.objects.get(id=job_id)
    except IngestionJob.DoesNotExist:
        close_old_connections()
        return

    def log_job(message_text: str) -> None:
        IngestionJobLog.objects.create(job=job, message=message_text)

    _wait_for_turn(job_id, log_job)

    try:
        # Local import avoids circular import at module load.
        from .pipeline import run_website_crawl_and_ingest

        log_job("Website crawl started in background worker.")
        result = run_website_crawl_and_ingest(
            replace_existing_sources=replace_existing_sources,
            log_fn=None,  # pipeline writes IngestionJobLog when job is passed
            job=job,
        )
        job.files_received = result.pages_fetched + result.pdfs_fetched
        job.files_processed = result.pages_ingested + result.pdfs_ingested
        job.files_failed = result.pages_failed + result.pdfs_failed
        job.chunks_created = result.chunks_created
        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "files_received",
                "files_processed",
                "files_failed",
                "chunks_created",
                "status",
                "finished_at",
            ]
        )
        log_job("Website crawl job finished.")
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        IngestionJobLog.objects.create(job=job, message=f"Website crawl failed: {exc}")
        logger.exception("Website crawl job %s failed", job_id)
    finally:
        close_old_connections()
