import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List

from django.db import close_old_connections
from django.utils import timezone

from .ingestion_service import ingest_uploaded_files
from .models import IngestionJob, IngestionJobLog
from .persist_db import dump_persistent_postgres

logger = logging.getLogger(__name__)


@dataclass
class StagedUpload:
    original_name: str
    staged_path: str


class _DiskUpload:
    def __init__(self, original_name: str, staged_path: str):
        self.name = original_name
        self._path = Path(staged_path)

    def read(self) -> bytes:
        return self._path.read_bytes()


_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("INGESTION_BACKGROUND_WORKERS", "1")))


def enqueue_ingestion_job(job_id: int, staged_uploads: List[StagedUpload], replace_existing_sources: bool) -> None:
    _executor.submit(_run_ingestion_job, job_id, staged_uploads, replace_existing_sources)


def enqueue_video_ingestion_job(job_id: int, staged_uploads: List[StagedUpload], replace_existing_sources: bool) -> None:
    """Persist a disk manifest; the dedicated video-ingest worker runs Whisper.

    Gunicorn's ThreadPoolExecutor dies on ``start.sh`` / worker recycle, so
    video jobs must not transcribe inside the web process.
    """
    from .video_job_queue import persist_video_job_manifest

    persist_video_job_manifest(job_id, staged_uploads, replace_existing_sources)


def _touch_job(job: IngestionJob) -> None:
    job.save(update_fields=["updated_at"])


def _run_ingestion_job(job_id: int, staged_uploads: List[StagedUpload], replace_existing_sources: bool) -> None:
    close_old_connections()
    try:
        job = IngestionJob.objects.get(id=job_id)
    except IngestionJob.DoesNotExist:
        _cleanup_staging_files(staged_uploads)
        close_old_connections()
        return

    def log_job(message_text: str) -> None:
        IngestionJobLog.objects.create(job=job, message=message_text)
        _touch_job(job)

    _wait_for_turn(job_id, log_job)

    uploads = [_DiskUpload(item.original_name, item.staged_path) for item in staged_uploads]
    try:
        log_job("Ingestion job started in background worker.")
        ingest_uploaded_files(
            uploads,
            replace_existing_sources=replace_existing_sources,
            log_fn=log_job,
            job=job,
        )
        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
        log_job("Ingestion job finished.")
    except Exception as exc:
        logger.exception("Ingestion job %s failed", job_id)
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        log_job(f"Ingestion failed: {exc}")
    finally:
        dump_persistent_postgres()
        _cleanup_staging_files(staged_uploads)
        close_old_connections()


def _run_video_ingestion_job(
    job_id: int,
    staged_uploads: List[StagedUpload],
    replace_existing_sources: bool,
    *,
    wait_for_turn: bool = True,
) -> None:
    close_old_connections()
    try:
        job = IngestionJob.objects.get(id=job_id)
    except IngestionJob.DoesNotExist:
        _cleanup_staging_files(staged_uploads)
        close_old_connections()
        return

    def log_job(message_text: str) -> None:
        IngestionJobLog.objects.create(job=job, message=message_text)
        _touch_job(job)

    if wait_for_turn:
        _wait_for_turn(job_id, log_job)

    uploads = [_DiskUpload(item.original_name, item.staged_path) for item in staged_uploads]
    try:
        log_job("Video ingestion job started in background worker.")
        from .video_ingestion import ingest_video_files

        ingest_video_files(
            uploads,
            replace_existing_sources=replace_existing_sources,
            log_fn=log_job,
            job=job,
        )
        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at", "updated_at"])
        log_job("Video ingestion job finished.")
    except Exception as exc:
        logger.exception("Video ingestion job %s failed", job_id)
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        log_job(f"Video ingestion failed: {exc}")
    finally:
        dump_persistent_postgres()
        _cleanup_staging_files(staged_uploads)
        close_old_connections()


def _cleanup_staging_files(staged_uploads: List[StagedUpload]) -> None:
    parent_dirs = {Path(item.staged_path).parent for item in staged_uploads}
    for file_item in staged_uploads:
        Path(file_item.staged_path).unlink(missing_ok=True)
    for directory in parent_dirs:
        shutil.rmtree(directory, ignore_errors=True)


def _wait_for_turn(job_id: int, log_fn) -> None:
    """
    Serialize ingestion execution order across queued jobs.

    Multiple gunicorn processes can each run background threads. This guard keeps
    the oldest unfinished running job active first so we don't overload host CPU/RAM
    by embedding multiple large batches in parallel.
    """
    poll_s = float(os.environ.get("INGESTION_QUEUE_POLL_S", "2"))
    announced_wait = False
    while True:
        earlier_running = IngestionJob.objects.filter(
            status="running",
            finished_at__isnull=True,
            id__lt=job_id,
        ).exists()
        if not earlier_running:
            return
        if not announced_wait:
            log_fn("Waiting for earlier ingestion jobs to finish (queued).")
            announced_wait = True
        time.sleep(poll_s)
