"""
Publish admin Embedded Videos into MediaVideo so GET /api/media/ stays complete.

Usage:
  cd backend/app
  python manage.py sync_embedded_media
"""

from django.core.management.base import BaseCommand

from api.media_catalog import ensure_media_videos_from_embedded, public_media_catalog


class Command(BaseCommand):
    help = "Create missing MediaVideo rows from admin Embedded Videos Vimeo embeds."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Syncing embedded Vimeo media into MediaVideo…"))
        result = ensure_media_videos_from_embedded()
        catalog = public_media_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"embedded={result['embedded']} created={result['created']} "
                f"public_catalog={len(catalog)}"
            )
        )
