"""
Attach ingested study notes to Walk through the Word videos.

Usage:
  cd backend/app
  python manage.py attach_media_notes
"""

from django.core.management.base import BaseCommand

from api.media_notes import attach_notes_to_media_videos


class Command(BaseCommand):
    help = "Match ingested study notes onto published Walk through the Word videos by date or Vimeo id."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Attaching study notes to Walk through the Word videos…"))
        result = attach_notes_to_media_videos()
        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"considered={result['considered']} matched_videos={result['matched_videos']} "
                f"attached={result['attached']} updated={result['updated']} "
                f"skipped_manual={result['skipped_manual']}"
            )
        )
