"""Copy Vimeo folder titles onto ingested videos named by Vimeo ID."""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from core.vimeo_titles import (
    DEFAULT_VIMEO_FOLDER_URL,
    VimeoTitleError,
    apply_titles_from_vimeo_folder,
)


class Command(BaseCommand):
    help = (
        "Replace numeric Vimeo-ID titles on ingested videos with the names "
        "from a Vimeo folder. Requires a personal access token with public "
        "and private scopes (the folder is not readable anonymously)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--folder-url",
            default=os.getenv("VIMEO_FOLDER_URL", DEFAULT_VIMEO_FOLDER_URL),
            help="Vimeo folder URL that contains the ingested videos.",
        )
        parser.add_argument(
            "--token",
            default="",
            help="Vimeo personal access token. Defaults to VIMEO_ACCESS_TOKEN.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing titles.",
        )
        parser.add_argument(
            "--skip-qdrant",
            action="store_true",
            help="Only update Django titles (leave Qdrant payload titles as-is).",
        )

    def handle(self, *args, **options):
        token = (options["token"] or os.getenv("VIMEO_ACCESS_TOKEN", "")).strip()
        if not token:
            raise CommandError(
                "Pass --token or set VIMEO_ACCESS_TOKEN. Create a token at "
                "https://developer.vimeo.com/apps with public + private scopes."
            )
        try:
            mapping, result = apply_titles_from_vimeo_folder(
                folder_url=options["folder_url"],
                token=token,
                dry_run=options["dry_run"],
                update_qdrant=not options["skip_qdrant"],
            )
        except VimeoTitleError as exc:
            raise CommandError(str(exc)) from exc

        prefix = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(
            f"{prefix} {result.updated} video title(s). "
            f"Already matched: {result.already_matched}. "
            f"No Vimeo name: {result.unmatched}. "
            f"Folder titles loaded: {len(mapping)}."
        )
        if result.qdrant_updated:
            self.stdout.write(f"Qdrant payload titles updated on {result.qdrant_updated} chunk(s).")
        if result.sidecars_updated:
            self.stdout.write(f"Transcript sidecars updated: {result.sidecars_updated}.")
        for source_name, old_title, new_title in result.sample_updates:
            self.stdout.write(f"  {source_name}: {old_title} → {new_title}")
        if result.unmatched_ids:
            self.stdout.write(
                "Unmatched IDs (first 20): " + ", ".join(result.unmatched_ids)
            )
