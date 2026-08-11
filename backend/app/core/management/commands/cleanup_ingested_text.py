"""
Preview or apply structured cleanup on extracted document text.

This command cleans text the same way admin Document Ingestion does before
chunking into Qdrant. It never modifies PDF files under uploads/admin_ingestion;
those originals remain available for sermon library links.

Examples:
  python manage.py cleanup_ingested_text --file /tmp/extracted.txt
  python manage.py cleanup_ingested_text --file notes.md --markdown
  python manage.py cleanup_ingested_text --file raw.txt --write /tmp/cleaned.txt
  python manage.py cleanup_ingested_text --demo
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.document_cleanup import (
    clean_extracted_document,
    clean_markdown_document,
    format_cleanup_log,
)


_DEMO_PDF_EXTRACT = """\
Faith That Moves Mountains
Pastor Don Nordin
Page 1 of 4
\x0c
Faith That Moves Mountains
All rights reserved.
Copyright © 2020 Example Ministry.

Today we look at faith that moves moun-
tains. Jesus taught that even a mustard
seed of faith can uproot what looks impos-
sible.

- 2 -
\x0c
Faith That Moves Mountains

When the disciples asked why they could
not cast out the demon, He pointed them
back to prayer and fasting.

Page 3 of 4
\x0c
Faith That Moves Mountains
www.example-ministry.org

Downloaded from the church resource portal.

Believe God for the breakthrough.
"""


class Command(BaseCommand):
    help = (
        "Run structured cleanup on extracted document text (Qdrant path only). "
        "Original PDFs for sermon library links are never modified."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            help="Path to extracted text or markdown to clean.",
        )
        parser.add_argument(
            "--markdown",
            action="store_true",
            help="Use the lighter markdown cleanup path (preserves headings/lists).",
        )
        parser.add_argument(
            "--write",
            type=str,
            help="Optional path to write cleaned text (does not touch source PDFs).",
        )
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Run against a built-in noisy sermon PDF extract sample.",
        )
        parser.add_argument(
            "--stats-only",
            action="store_true",
            help="Print cleanup stats without dumping cleaned text.",
        )

    def handle(self, *args, **options):
        demo = options["demo"]
        file_path = options.get("file")
        if not demo and not file_path:
            raise CommandError("Provide --file PATH or --demo.")

        if demo:
            raw = _DEMO_PDF_EXTRACT
            source_label = "demo_sermon_extract"
            use_markdown = False
        else:
            path = Path(file_path)
            if not path.is_file():
                raise CommandError(f"File not found: {path}")
            raw = path.read_text(encoding="utf-8", errors="replace")
            source_label = path.name
            use_markdown = bool(options["markdown"]) or path.suffix.lower() == ".md"

        if use_markdown:
            result = clean_markdown_document(raw)
            mode = "markdown"
        else:
            result = clean_extracted_document(raw, source_name=source_label)
            mode = "extracted"

        self.stdout.write(self.style.NOTICE(f"Cleanup mode: {mode}"))
        self.stdout.write(format_cleanup_log(result.stats, source_label=source_label))
        self.stdout.write(
            self.style.SUCCESS(
                "Original PDF/DOCX files are not modified; sermon library links "
                "continue to serve uploads/admin_ingestion originals."
            )
        )

        write_path = options.get("write")
        if write_path:
            out = Path(write_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result.text + ("\n" if result.text else ""), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote cleaned text to {out}"))

        if options["stats_only"]:
            return

        self.stdout.write("")
        self.stdout.write("--- cleaned text ---")
        self.stdout.write(result.text)
        self.stdout.write("--- end ---")
