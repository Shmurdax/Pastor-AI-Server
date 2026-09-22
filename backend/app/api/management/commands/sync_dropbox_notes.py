"""
Download Walk through the Word study notes from Dropbox, ingest them, and
attach each file to the matching Vimeo video.

Usage:
  cd backend/app
  python manage.py sync_dropbox_notes
  python manage.py sync_dropbox_notes --replace
"""

from django.core.management.base import BaseCommand, CommandError

from api.dropbox_notes import DropboxNotesError, enqueue_dropbox_notes_ingest


class Command(BaseCommand):
    help = "Download Walk through the Word notes from Dropbox and ingest them onto matching videos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace previously ingested files that share the same source name.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Downloading Walk through the Word notes from Dropbox…"))
        try:
            job = enqueue_dropbox_notes_ingest(
                started_by="dropbox-notes",
                replace_existing_sources=bool(options.get("replace")),
            )
        except DropboxNotesError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued ingestion job #{job.id} with {job.files_received} file(s). "
                "Matching notes are attached to Walk through the Word videos when ingest finishes."
            )
        )
