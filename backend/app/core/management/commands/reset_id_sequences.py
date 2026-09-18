"""Advance Postgres serial sequences to MAX(id) after a data-only catalog restore."""
from django.core.management.base import BaseCommand

from core.postgres_sequences import reset_id_sequences


class Command(BaseCommand):
    help = "Set each Postgres id sequence to MAX(pk) so ingest can create new IngestionJob rows."

    def handle(self, *args, **options):
        updated = reset_id_sequences()
        if updated:
            self.stdout.write(self.style.SUCCESS(f"Advanced {updated} id sequence(s)."))
        else:
            self.stdout.write("No Postgres id sequences to update (SQLite or empty schema).")
