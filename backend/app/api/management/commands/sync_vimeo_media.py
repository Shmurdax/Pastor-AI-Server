"""
Sync Daily Devotionals from the configured Vimeo Folder.

Usage:
  cd backend/app
  python manage.py sync_vimeo_media
"""

from django.core.management.base import BaseCommand, CommandError

from api.vimeo_sync import VimeoSyncError, sync_vimeo_media


class Command(BaseCommand):
    help = "Sync unlisted Daily Devotionals from the configured Vimeo Folder into MediaVideo."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Syncing Vimeo Folder media…"))
        try:
            result = sync_vimeo_media()
        except VimeoSyncError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"fetched={result['fetched']} created={result['created']} "
                f"updated={result['updated']} unpublished={result['unpublished']}"
            )
        )
