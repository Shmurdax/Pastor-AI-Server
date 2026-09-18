"""Index cited verses on already-ingested sermon PDFs for catalog search.

Example::

    python manage.py backfill_document_scripture_refs
    python manage.py backfill_document_scripture_refs --force --limit 20
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.bible_refs import scripture_refs_from_metadata
from core.ingestion_service import (
    _extract_pdf_text,
    _is_bible_source,
    document_scripture_topic_metadata,
)
from core.models import IngestedDocument
from core.storage_paths import ingested_media_path


class Command(BaseCommand):
    help = "Extract scripture refs from stored sermon PDFs for document-browser verse search."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        limit = int(options.get("limit") or 0)
        force = bool(options.get("force"))
        updated = 0
        skipped = 0
        missing = 0

        qs = IngestedDocument.objects.filter(source_kind="document").order_by("id")
        for doc in qs:
            if limit and updated >= limit:
                break
            name = f"{doc.source_name} {doc.title}"
            if _is_bible_source(name):
                skipped += 1
                continue
            existing = scripture_refs_from_metadata(doc.topic_metadata)
            if existing and not force:
                skipped += 1
                continue
            path = ingested_media_path(doc.source_name, doc.source_kind)
            if not path.is_file():
                missing += 1
                continue
            try:
                text = _extract_pdf_text(path)
            except Exception as exc:
                self.stderr.write(f"FAILED {doc.source_name}: {exc}")
                continue
            meta = document_scripture_topic_metadata(doc.title, text, is_bible=False)
            merged = dict(doc.topic_metadata or {})
            merged["scripture_refs"] = meta.get("scripture_refs") or []
            doc.topic_metadata = merged
            doc.save(update_fields=["topic_metadata", "updated_at"])
            updated += 1
            self.stdout.write(
                f"{doc.title}: {len(merged['scripture_refs'])} scripture refs"
            )

        self.stdout.write(
            f"Updated {updated}, skipped {skipped}, missing files {missing}."
        )
