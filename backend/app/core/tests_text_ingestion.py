"""Admin ingest accepts raw .txt / .md and chunks the original text."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.ingestion_service import (
    DOCUMENT_EXTENSIONS,
    _decode_text_bytes,
    document_scripture_topic_metadata,
    ingest_uploaded_files,
    is_document_filename,
)
from core.models import IngestedDocument, IngestionJob


class DocumentFilenameTests(SimpleTestCase):
    def test_document_extensions_include_plain_text(self):
        self.assertEqual(DOCUMENT_EXTENSIONS, {".pdf", ".docx", ".txt", ".md"})
        self.assertTrue(is_document_filename("The Giver and His Gifts - Full Transcript.txt"))
        self.assertTrue(is_document_filename("notes.MD"))
        self.assertTrue(is_document_filename("slides.docx"))
        self.assertFalse(is_document_filename("clip.mp4"))
        self.assertFalse(is_document_filename("sheet.xlsx"))


class ScriptureTopicMetadataTests(SimpleTestCase):
    def test_indexes_cited_verses_and_skips_bible_sources(self):
        meta = document_scripture_topic_metadata(
            "Hope",
            "God so loved the world, John 3:16-17.",
            is_bible=False,
        )
        self.assertEqual(meta["scripture_refs"], ["John 3:16", "John 3:17"])
        self.assertEqual(
            document_scripture_topic_metadata("NKJV", "John 3:16", is_bible=True),
            {},
        )


class DecodeTextBytesTests(SimpleTestCase):
    def test_utf8_bom_and_windows_1252(self):
        self.assertEqual(_decode_text_bytes(b"\xef\xbb\xbfChapter 1\nThe gift"), "Chapter 1\nThe gift")
        self.assertEqual(_decode_text_bytes("caf\u00e9 notes".encode("utf-8")), "café notes")
        self.assertEqual(_decode_text_bytes("caf\xe9 notes".encode("latin-1")), "café notes")


class TextUploadIngestTests(TestCase):
    def _ingest(self, upload, **env):
        logs = []
        fake_embeddings = MagicMock()
        fake_embeddings.embed_documents.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)
        fake_qdrant = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            patches = {
                "INGESTION_UPLOAD_DIR": tmp,
                **env,
            }
            with patch.dict(os.environ, patches), patch(
                "core.ingestion_service.admin_ingestion_dir", return_value=Path(tmp)
            ), patch(
                "core.ingestion_service.get_embeddings", return_value=fake_embeddings
            ), patch(
                "core.ingestion_service.QdrantClient", return_value=fake_qdrant
            ), patch(
                "core.ingestion_service.ensure_sermon_collection"
            ), patch(
                "core.ingestion_service.ensure_payload_indexes"
            ), patch(
                "core.ingestion_service._extract_pdf_text", return_value="EXTRACTED FROM PDF"
            ):
                result = ingest_uploaded_files([upload], log_fn=logs.append)
            pdf_path = Path(tmp) / f"{Path(upload.name).stem}.pdf"
            pdf_bytes = pdf_path.read_bytes() if pdf_path.is_file() else b""
            return result, bool(pdf_bytes), pdf_bytes, fake_qdrant, logs

    def test_txt_chunks_original_text_and_writes_library_pdf(self):
        body = (
            "Chapter 1\n\n"
            "The Holy Spirit is a gift from the Father to the church. "
            "Every believer can receive this gift and walk in it daily, as John 3:16-17 teaches.\n\n"
            "Chapter 2\n\n"
            "The gifts are given so the body of Christ can be built up in love."
        )
        upload = SimpleUploadedFile(
            "The Giver and His Gifts - Full Transcript.txt",
            body.encode("utf-8"),
            content_type="text/plain",
        )
        result, pdf_exists, pdf_bytes, qdrant, logs = self._ingest(upload)

        self.assertEqual(result.files_received, 1, logs)
        self.assertEqual(result.files_processed, 1, logs)
        self.assertEqual(result.files_failed, 0, logs)
        self.assertGreater(result.chunks_created, 0)
        self.assertTrue(pdf_exists)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertNotIn(b"truncated", pdf_bytes)

        doc = IngestedDocument.objects.get(source_name="The Giver and His Gifts - Full Transcript.pdf")
        self.assertEqual(doc.original_extension, ".txt")
        self.assertEqual(doc.source_kind, "document")
        self.assertIn("Giver", doc.title)
        refs = (doc.topic_metadata or {}).get("scripture_refs") or []
        self.assertIn("John 3:16", refs)
        self.assertIn("John 3:17", refs)

        upserted = qdrant.upsert.call_args.kwargs["points"]
        texts = " ".join(point.payload["text"] for point in upserted)
        self.assertIn("Holy Spirit is a gift", texts)
        self.assertNotIn("EXTRACTED FROM PDF", texts)
        self.assertTrue(
            any("library PDF from .txt" in line for line in logs)
        )

    def test_markdown_keeps_headings_and_skips_pdf_extract(self):
        body = "# Kings and Priests\n\nJesus made us kings and priests unto God.\n"
        upload = SimpleUploadedFile("Kings_and_Priests.md", body.encode("utf-8"), content_type="text/markdown")
        result, pdf_exists, pdf_bytes, qdrant, logs = self._ingest(upload)

        self.assertEqual(result.files_processed, 1, logs)
        self.assertTrue(pdf_exists)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        doc = IngestedDocument.objects.get(source_name="Kings_and_Priests.pdf")
        self.assertEqual(doc.original_extension, ".md")
        texts = " ".join(point.payload["text"] for point in qdrant.upsert.call_args.kwargs["points"])
        self.assertIn("kings and priests", texts.lower())
        self.assertNotIn("EXTRACTED FROM PDF", texts)
        self.assertTrue(any("library PDF from .md" in line for line in logs))

    def test_unsupported_type_is_failed_not_ingested(self):
        upload = SimpleUploadedFile("notes.xlsx", b"not-a-document", content_type="application/vnd.ms-excel")
        result, pdf_exists, _pdf_bytes, qdrant, _logs = self._ingest(upload)
        self.assertEqual(result.files_processed, 0)
        self.assertEqual(result.files_failed, 1)
        self.assertFalse(pdf_exists)
        qdrant.upsert.assert_not_called()
        self.assertEqual(IngestedDocument.objects.count(), 0)


class TextIngestionAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_ingestion_page_accepts_txt_and_markdown(self):
        template = Path(__file__).resolve().parent / "templates" / "admin" / "core" / "ingestion.html"
        body = template.read_text(encoding="utf-8")
        self.assertIn('accept=".docx,.pdf,.txt,.md"', body)
        self.assertIn('allowedExtensions = [".pdf", ".docx", ".txt", ".md"]', body)
        self.assertIn("Only PDF, DOCX, TXT, and Markdown files are allowed", body)
        self.assertIn("TXT, or Markdown files", body)

    @patch("core.admin.enqueue_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_ingestion_post_accepts_txt(self, _stage, mock_enqueue):
        upload = SimpleUploadedFile(
            "Working At God's Altar - Full Transcript.txt",
            b"Chapter 1\nServe at the altar.",
            content_type="text/plain",
        )
        response = self.client.post(
            reverse("admin:core_ingestion"),
            {"documents": upload, "hide_from_library": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        job = IngestionJob.objects.get(id=payload["job_id"])
        self.assertFalse(job.in_library)
        mock_enqueue.assert_called_once()

    def test_ingestion_post_rejects_spreadsheet(self):
        upload = SimpleUploadedFile("notes.xlsx", b"abc", content_type="application/vnd.ms-excel")
        response = self.client.post(
            reverse("admin:core_ingestion"),
            {"documents": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Markdown", response.json()["error"])
        self.assertEqual(IngestionJob.objects.count(), 0)
