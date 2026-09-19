"""
Publish admin Embedded Videos into MediaVideo so GET /api/media/ stays complete.

Usage:
  cd backend/app
  python manage.py sync_embedded_media
"""

from django.core.management.base import BaseCommand

from api.media_catalog import (
    ensure_media_videos_from_embedded,
    load_committed_vimeo_folder_catalog,
    public_media_catalog,
)


class Command(BaseCommand):
    help = "Load the committed Vimeo folder catalog and admin Embedded Videos into MediaVideo."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Loading committed Vimeo folder embeds…"))
        folder = load_committed_vimeo_folder_catalog()
        self.stdout.write(
            self.style.NOTICE("Syncing admin Embedded Videos into MediaVideo…")
        )
        result = ensure_media_videos_from_embedded()
        catalog = public_media_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"folder_loaded={folder['loaded']} folder_created={folder['created']} "
                f"folder_updated={folder['updated']} "
                f"embedded={result['embedded']} created={result['created']} "
                f"public_catalog={len(catalog)}"
            )
        )
