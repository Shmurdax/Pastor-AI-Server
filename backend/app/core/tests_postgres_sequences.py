"""Stale Postgres sequences must not 500 Admin Document Ingestion."""

from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from core.postgres_sequences import create_ingestion_job, reset_id_sequences
from core.models import IngestionJob


class ResetIdSequencesTests(SimpleTestCase):
    def test_sqlite_is_a_noop(self):
        self.assertEqual(reset_id_sequences(), 0)

    def test_postgres_advances_each_serial_sequence_to_max_pk(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ('"public"."core_ingestionjob"', '"id"', "public.core_ingestionjob_id_seq"),
        ]
        conn = MagicMock()
        conn.vendor = "postgresql"
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch("core.postgres_sequences.connections", {"default": conn}):
            self.assertEqual(reset_id_sequences(), 1)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn("pg_get_serial_sequence", statements[0])
        self.assertIn("setval", statements[1])
        self.assertIn("core_ingestionjob", statements[1])
        self.assertEqual(cursor.execute.call_args_list[1].args[1], ["public.core_ingestionjob_id_seq"])


class CreateIngestionJobTests(TestCase):
    def test_creates_a_document_job(self):
        job = create_ingestion_job(
            started_by="admin",
            job_kind="document",
            status="running",
            files_received=1,
        )
        self.assertIsNotNone(job.id)
        self.assertEqual(job.started_by, "admin")
        self.assertEqual(IngestionJob.objects.filter(id=job.id).count(), 1)

    def test_retries_after_duplicate_primary_key(self):
        real_create = IngestionJob.objects.create
        calls = {"n": 0}

        def flaky_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError(
                    'duplicate key value violates unique constraint "core_ingestionjob_pkey"'
                )
            return real_create(**kwargs)

        with patch.object(IngestionJob.objects, "create", side_effect=flaky_create), patch(
            "core.postgres_sequences.reset_id_sequences", return_value=1
        ) as reset:
            job = create_ingestion_job(
                started_by="admin",
                job_kind="document",
                status="running",
            )

        reset.assert_called_once()
        self.assertEqual(calls["n"], 2)
        self.assertEqual(job.started_by, "admin")
