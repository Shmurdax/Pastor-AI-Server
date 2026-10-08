"""
Import a folder of dated study-note PDFs and link each file to a video.

Usage:
  cd backend/app
  python manage.py import_episode_notes /path/to/notes

Filenames look like ``May 15_2026.pdf``. Notes are stored for the watch page
and media search only. They are not ingested into the knowledge base.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.episode_notes import import_episode_notes


class Command(BaseCommand):
    help = (
        "Import dated episode-note PDFs and link them to MediaVideo. "
        "Does not add the notes to the knowledge base."
    )

    def add_arguments(self, parser):
        parser.add_argument("directory", help="Folder of PDFs named like May 15_2026.pdf")

    def handle(self, *args, **options):
        directory = Path(options["directory"])
        self.stdout.write(self.style.NOTICE(f"Importing episode notes from {directory}…"))
        try:
            result = import_episode_notes(directory)
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"created={result['created']} updated={result['updated']} "
                f"unlinked={len(result['unlinked'])} undated={len(result['undated'])}"
            )
        )
        if result["unlinked"]:
            self.stdout.write("Unlinked (no matching published video):")
            for name in result["unlinked"]:
                self.stdout.write(f"  {name}")
        if result["undated"]:
            self.stdout.write("Skipped (filename has no month, day, and year):")
            for name in result["undated"]:
                self.stdout.write(f"  {name}")
