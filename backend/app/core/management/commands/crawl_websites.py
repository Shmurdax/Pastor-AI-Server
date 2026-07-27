"""
Crawl allowlisted Nordins / ministry websites and ingest into Qdrant.

Usage:
  cd backend/app
  python manage.py crawl_websites
  python manage.py crawl_websites --no-replace
  python manage.py crawl_websites --delay 0.5
"""

from django.core.management.base import BaseCommand

from core.website_crawl.pipeline import run_website_crawl_and_ingest


class Command(BaseCommand):
    help = "Crawl thenordins.org + sister ministry sites and ingest public pages into Qdrant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-replace",
            action="store_true",
            help="Do not replace existing sources with the same source_name (default replaces).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.35,
            help="Polite delay in seconds between HTTP requests (default 0.35).",
        )
        parser.add_argument(
            "--ignore-robots",
            action="store_true",
            help="Do not consult robots.txt (not recommended).",
        )

    def handle(self, *args, **options):
        replace = not options["no_replace"]
        self.stdout.write(self.style.NOTICE("Starting allowlisted website crawl…"))

        def log_fn(message: str) -> None:
            self.stdout.write(message)

        result = run_website_crawl_and_ingest(
            replace_existing_sources=replace,
            log_fn=log_fn,
            delay_s=options["delay"],
            respect_robots=not options["ignore_robots"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"pages_fetched={result.pages_fetched} pages_ingested={result.pages_ingested} "
                f"pdfs_fetched={result.pdfs_fetched} pdfs_ingested={result.pdfs_ingested} "
                f"chunks_created={result.chunks_created}"
            )
        )
