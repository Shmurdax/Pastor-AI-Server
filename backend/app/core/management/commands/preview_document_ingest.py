"""Dry-run admin Document Ingestion for local transcript files."""

from django.core.management.base import BaseCommand, CommandError

from core.preview_document_ingest import default_queries_for, format_preview, preview_text_upload


class Command(BaseCommand):
    help = (
        "Dry-run the admin .txt/.md ingest path (cleanup, title, quote chunks, "
        "scripture refs) without writing Qdrant, Postgres, or library PDFs."
    )

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+", help="Transcript files to preview.")
        parser.add_argument(
            "--query",
            action="append",
            default=[],
            help="Optional lexical retrieval probe. Repeatable.",
        )

    def handle(self, *args, **options):
        from pathlib import Path

        reports = []
        for raw_path in options["files"]:
            path = Path(raw_path)
            if not path.is_file():
                raise CommandError(f"File not found: {path}")
            queries = list(options["query"]) or default_queries_for(path.name)
            preview = preview_text_upload(path, queries=queries)
            reports.append(format_preview(preview))
        self.stdout.write("\n\n".join(reports))
