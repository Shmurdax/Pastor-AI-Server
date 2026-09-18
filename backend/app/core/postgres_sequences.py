"""Keep Postgres serial/identity sequences ahead of existing primary keys.

``pg_restore --data-only`` (the git seed catalog) inserts explicit IDs and can
leave ``core_ingestionjob_id_seq`` behind ``MAX(id)``. The next
``IngestionJob.objects.create()`` then 500s with a duplicate pkey.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, connections, transaction

logger = logging.getLogger(__name__)


def reset_id_sequences(*, using: str = "default") -> int:
    """Set each public serial/identity sequence to MAX(pk), or 1 if the table is empty.

    No-op on SQLite (local tests). Returns the number of sequences updated.
    """
    conn = connections[using]
    if conn.vendor != "postgresql":
        return 0

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                quote_ident(n.nspname) || '.' || quote_ident(c.relname) AS table_name,
                quote_ident(a.attname) AS column_name,
                pg_get_serial_sequence(
                    format('%I.%I', n.nspname, c.relname),
                    a.attname
                ) AS seq
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relkind = 'r'
              AND n.nspname = 'public'
              AND pg_get_serial_sequence(
                    format('%I.%I', n.nspname, c.relname),
                    a.attname
                  ) IS NOT NULL
            """
        )
        rows = cursor.fetchall()
        updated = 0
        for table_name, column_name, seq in rows:
            if not seq:
                continue
            cursor.execute(
                f"""
                SELECT setval(
                    %s,
                    COALESCE((SELECT MAX({column_name}) FROM {table_name}), 1),
                    (SELECT MAX({column_name}) FROM {table_name}) IS NOT NULL
                )
                """,
                [seq],
            )
            updated += 1
    if updated:
        logger.info("Advanced %s Postgres id sequence(s) to MAX(pk).", updated)
    return updated


def create_ingestion_job(**kwargs):
    """Insert an IngestionJob, healing a stale id sequence after a pkey collision."""
    from .models import IngestionJob

    try:
        with transaction.atomic():
            return IngestionJob.objects.create(**kwargs)
    except IntegrityError:
        logger.warning(
            "IngestionJob insert hit a duplicate primary key; resetting Postgres sequences and retrying."
        )
        reset_id_sequences()
        return IngestionJob.objects.create(**kwargs)
