"""Process disk-backed video/audio ingestion jobs outside gunicorn."""
from __future__ import annotations

import logging
import os
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from core.ingestion_tasks import _run_video_ingestion_job
from core.models import IngestionJob, IngestionJobLog
from core.video_job_queue import load_video_job_uploads, video_job_has_staging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run queued Whisper media jobs from persistent staging. "
        "Survives gunicorn restarts; already-ingested files are skipped by hash."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one job, then exit.")
        parser.add_argument(
            "--poll",
            type=float,
            default=float(os.environ.get("VIDEO_INGEST_WORKER_POLL_S", "5")),
            help="Seconds to wait when the queue is empty.",
        )
        parser.add_argument(
            "--empty-grace-minutes",
            type=int,
            default=int(os.environ.get("VIDEO_INGEST_EMPTY_GRACE_MINUTES", "30")),
            help="Fail running jobs with no staging files after this many minutes.",
        )

    def handle(self, *args, **options):
        once = bool(options["once"])
        poll_s = max(1.0, float(options["poll"]))
        empty_grace = max(1, int(options["empty_grace_minutes"]))
        self.stdout.write("Video ingestion worker started.")
        while True:
            close_old_connections()
            processed = self._process_next(empty_grace)
            if once:
                return
            if not processed:
                time.sleep(poll_s)

    def _process_next(self, empty_grace_minutes: int) -> bool:
        jobs = IngestionJob.objects.filter(
            job_kind="video",
            status="running",
            finished_at__isnull=True,
        ).order_by("id")
        for job in jobs:
            uploads, replace_existing = load_video_job_uploads(job.id)
            if uploads:
                self.stdout.write(f"Processing video job #{job.id} ({len(uploads)} file(s)).")
                # The dedicated worker already serializes one job at a time.
                _run_video_ingestion_job(
                    job.id,
                    uploads,
                    replace_existing,
                    wait_for_turn=False,
                )
                return True

            last_activity = job.updated_at or job.created_at
            idle = timezone.now() - last_activity
            if idle >= timezone.timedelta(minutes=empty_grace_minutes) and not video_job_has_staging(job.id):
                job.status = "failed"
                job.error_message = "Video ingestion staging files were missing after restart."
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
                IngestionJobLog.objects.create(job=job, message=job.error_message)
                self.stdout.write(f"Job #{job.id} failed: staging missing.")
                return True
        return False
