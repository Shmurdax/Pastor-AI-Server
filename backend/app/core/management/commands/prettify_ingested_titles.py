"""Backfill prettified titles and near-duplicate keys on existing ingested documents."""

from django.core.management.base import BaseCommand

from core.document_titles import normalize_title_key, prettify_title
from core.models import IngestedDocument


class Command(BaseCommand):
    help = (
        "Rewrite IngestedDocument.title from source_name using prettify_title, "
        "and fill normalized_title. Does not modify on-disk files or Qdrant payloads."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show changes without saving.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of documents to process (0 = all).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        qs = IngestedDocument.objects.all().order_by("id")
        if limit > 0:
            qs = qs[:limit]

        updated = 0
        unchanged = 0
        for doc in qs:
            source = doc.source_name or doc.title or ""
            new_title = prettify_title(source)
            # Keep human website titles that are already sentence-cased.
            if doc.source_kind == "website" and doc.title and not doc.title.isupper():
                new_title = doc.title.strip() or new_title
            new_key = normalize_title_key(new_title)
            if doc.title == new_title and doc.normalized_title == new_key:
                unchanged += 1
                continue
            self.stdout.write(
                f"{'[dry-run] ' if dry_run else ''}"
                f"#{doc.id}: “{doc.title}” → “{new_title}” ({doc.source_name})"
            )
            if not dry_run:
                doc.title = new_title
                doc.normalized_title = new_key
                doc.save(update_fields=["title", "normalized_title", "updated_at"])
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. updated={updated} unchanged={unchanged} dry_run={dry_run}"
            )
        )
