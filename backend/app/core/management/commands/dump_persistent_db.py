"""Dump the app database onto the RunPod persistent volume."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from core.persist_db import dump_path, dump_persistent_postgres


class Command(BaseCommand):
    help = "Dump Postgres onto /workspace/persistent so remigrations keep the document catalog."

    def handle(self, *args, **options):
        if dump_persistent_postgres():
            self.stdout.write(self.style.SUCCESS(f"Wrote persistent Postgres dump {dump_path()}"))
        else:
            self.stderr.write("Postgres persist dump failed (non-fatal).")
