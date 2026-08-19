"""Ingest local video files through the Whisper + normalize pipeline."""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import IngestionJob, IngestionJobLog
from core.video_ingestion import ingest_video_files, is_video_filename


class _PathUpload:
    def __init__(self, path: Path):
        self.name = path.name
        self._path = path

    def read(self) -> bytes:
        return self._path.read_bytes()


class Command(BaseCommand):
    help = "Transcribe video files with Whisper and ingest timestamped transcripts into Qdrant."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="Video files to ingest.")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing sources with the same filename stem.",
        )

    def handle(self, *args, **options):
        files = []
        for raw in options["paths"]:
            path = Path(raw).expanduser().resolve()
            if not path.is_file():
                raise CommandError(f"Not a file: {path}")
            if not is_video_filename(path.name):
                raise CommandError(f"Unsupported video type: {path.name}")
            files.append(_PathUpload(path))

        job = IngestionJob.objects.create(
            started_by="manage.py ingest_videos",
            job_kind="video",
            replace_existing_sources=bool(options["replace"]),
            status="running",
            files_received=len(files),
        )
        IngestionJobLog.objects.create(job=job, message="CLI video ingestion started.")

        def log_fn(message: str) -> None:
            self.stdout.write(message)
            IngestionJobLog.objects.create(job=job, message=message)

        try:
            result = ingest_video_files(
                files,
                replace_existing_sources=bool(options["replace"]),
                log_fn=log_fn,
                job=job,
            )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
            raise CommandError(str(exc)) from exc

        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {result.files_processed}/{result.files_received} videos, "
                f"chunks={result.chunks_created}, skipped={result.files_skipped_as_duplicates}, "
                f"failed={result.files_failed}."
            )
        )
