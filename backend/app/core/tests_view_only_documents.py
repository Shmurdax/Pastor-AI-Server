import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import IngestedDocument, IngestionJob


def _make_doc(**kwargs):
    defaults = {
        "source_name": "hope.pdf",
        "title": "Hope In Christ",
        "file_hash": "a" * 64,
        "original_extension": ".pdf",
        "source_kind": "document",
        "view_only": False,
        "chunk_count": 1,
    }
    defaults.update(kwargs)
    return IngestedDocument.objects.create(**defaults)


class ViewOnlyIngestionAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_ingestion_page_includes_make_view_only_checkbox(self):
        template = Path(__file__).resolve().parent / "templates" / "admin" / "core" / "ingestion.html"
        body = template.read_text(encoding="utf-8")
        self.assertIn('name="view_only"', body)
        self.assertIn("Make view only", body)
        self.assertIn('name="hide_from_library"', body)
        self.assertIn("Keep out of sermon library", body)
        self.assertIn("hidden from sermon sources", body)

    @patch("core.admin.enqueue_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_ingestion_post_hides_from_library_when_checked(self, _stage, mock_enqueue):
        upload = SimpleUploadedFile("nkjv.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(
            reverse("admin:core_ingestion"),
            {"documents": upload, "hide_from_library": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        job = IngestionJob.objects.get(id=response.json()["job_id"])
        self.assertFalse(job.in_library)
        self.assertFalse(job.view_only)

    @patch("core.admin.enqueue_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_ingestion_post_persists_view_only_on_job(self, _stage, mock_enqueue):
        upload = SimpleUploadedFile("book.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(
            reverse("admin:core_ingestion"),
            {"documents": upload, "view_only": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["ok"])
        job = IngestionJob.objects.get(id=payload["job_id"])
        self.assertTrue(job.view_only)
        mock_enqueue.assert_called_once()

    @patch("core.admin.enqueue_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_ingestion_post_defaults_view_only_off(self, _stage, mock_enqueue):
        upload = SimpleUploadedFile("notes.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(
            reverse("admin:core_ingestion"),
            {"documents": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content)
        job = IngestionJob.objects.get(id=response.json()["job_id"])
        self.assertFalse(job.view_only)
        self.assertTrue(job.in_library)
        mock_enqueue.assert_called_once()


class ViewOnlyDocumentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.premium = User.objects.create_user(
            username="premium@church.org",
            email="premium@church.org",
            password="PremiumPass123!",
        )
        self.premium.profile.subscription_status = "active"
        self.premium.profile.save(update_fields=["subscription_status"])
        self.token = Token.objects.create(user=self.premium).key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_list_includes_view_only_and_source_kind_filter(self):
        _make_doc(title="Book Transcript", source_name="book.pdf", view_only=True)
        _make_doc(
            title="Sunday Notes",
            source_name="sunday.pdf",
            file_hash="b" * 64,
            view_only=False,
        )
        _make_doc(
            title="Video Talk",
            source_name="talk.m4a",
            file_hash="c" * 64,
            source_kind="video",
            original_extension=".m4a",
        )

        all_docs = self.client.get("/api/ingested-documents/")
        self.assertEqual(all_docs.status_code, 200)
        by_title = {item["title"]: item for item in all_docs.data["documents"]}
        self.assertTrue(by_title["Book Transcript"]["view_only"])
        self.assertFalse(by_title["Sunday Notes"]["view_only"])

        pdfs = self.client.get("/api/ingested-documents/", {"source_kind": "document"})
        self.assertEqual(pdfs.status_code, 200)
        titles = {item["title"] for item in pdfs.data["documents"]}
        self.assertEqual(titles, {"Book Transcript", "Sunday Notes"})

    def test_hidden_from_library_is_omitted_and_file_404s(self):
        visible = _make_doc(title="Sunday Notes", source_name="sunday.pdf")
        hidden = _make_doc(
            title="New King James Version",
            source_name="nkjv.pdf",
            file_hash="d" * 64,
            in_library=False,
        )
        listed = self.client.get("/api/ingested-documents/")
        self.assertEqual(listed.status_code, 200)
        titles = {item["title"] for item in listed.data["documents"]}
        self.assertIn(visible.title, titles)
        self.assertNotIn(hidden.title, titles)

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "nkjv.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 bible")
            with patch.dict(os.environ, {"INGESTION_UPLOAD_DIR": tmp}):
                by_id = self.client.get(f"/api/ingested-documents/{hidden.id}/file/")
                by_name = self.client.get("/sermons/New King James Version.pdf")
        self.assertEqual(by_id.status_code, 404)
        self.assertEqual(by_name.status_code, 404)

    def test_view_only_file_is_inline_without_original_filename(self):
        doc = _make_doc(title="Secret Book", source_name="secret-book.pdf", view_only=True)
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "secret-book.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 view-only")
            with patch.dict(os.environ, {"INGESTION_UPLOAD_DIR": tmp}):
                response = self.client.get(f"/api/ingested-documents/{doc.id}/file/?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn('filename="document.pdf"', response["Content-Disposition"])
        self.assertNotIn("secret-book", response["Content-Disposition"])
        self.assertNotIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_downloadable_file_keeps_original_filename(self):
        doc = _make_doc(title="Sunday Notes", source_name="sunday-notes.pdf", view_only=False)
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sunday-notes.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 notes")
            with patch.dict(os.environ, {"INGESTION_UPLOAD_DIR": tmp}):
                inline = self.client.get(f"/api/ingested-documents/{doc.id}/file/")
                attached = self.client.get(f"/api/ingested-documents/{doc.id}/file/?download=1")
        self.assertEqual(inline.status_code, 200)
        self.assertIn("inline", inline["Content-Disposition"])
        self.assertIn("sunday-notes.pdf", inline["Content-Disposition"])
        self.assertNotEqual(inline.headers.get("Cache-Control"), "private, no-store")
        self.assertEqual(attached.status_code, 200)
        self.assertIn("attachment", attached["Content-Disposition"])
        self.assertIn("sunday-notes.pdf", attached["Content-Disposition"])

    def test_admin_url_for_ingestion_still_resolves(self):
        prefix = f"/{settings.ADMIN_URL_PATH}"
        self.assertEqual(reverse("admin:core_ingestion"), f"{prefix}/core/ingestion/")


class HiddenLibraryChatSourceTests(TestCase):
    def _chunk(self, *, source, file_hash, title=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            page_content="The Holy Spirit is a gift.",
            metadata={
                "source": source,
                "file_hash": file_hash,
                "title": title or source,
            },
        )

    def test_hidden_books_are_dropped_from_chat_sermon_sources(self):
        from core.chat_retrieval import ensure_source_media_mix, sources_cited_in_answer
        from core.views import _doc_source_label, visible_chat_source_docs

        visible = _make_doc(title="Sunday Notes", source_name="sunday.pdf", file_hash="s" * 64)
        hidden = _make_doc(
            title="The Giver and His Gifts",
            source_name="The Giver and His Gifts - Full Transcript.pdf",
            file_hash="g" * 64,
            in_library=False,
        )
        bible = _make_doc(
            title="New King James Version",
            source_name="nkjv.pdf",
            file_hash="n" * 64,
            in_library=False,
        )
        docs = [
            self._chunk(source=hidden.source_name, file_hash=hidden.file_hash, title=hidden.title),
            self._chunk(source=visible.source_name, file_hash=visible.file_hash, title=visible.title),
            self._chunk(source=bible.source_name, file_hash=bible.file_hash, title=bible.title),
        ]
        public = visible_chat_source_docs(docs)
        self.assertEqual(len(public), 1)
        self.assertEqual(_doc_source_label(public[0]), "Sunday Notes")

        answer = (
            "As The Giver and His Gifts teaches, the Holy Spirit is a gift. "
            "Sunday Notes also says to walk in love. New King James Version 1 Corinthians 12:7."
        )
        cited = sources_cited_in_answer(public, answer, _doc_source_label, limit=5)
        mixed = ensure_source_media_mix(
            cited or ["Sunday Notes"],
            public,
            _doc_source_label,
            min_count=1,
            limit=5,
            query="spiritual gifts",
        )
        labels = " ".join(mixed).lower()
        self.assertTrue(any("sunday" in item.lower() for item in mixed), mixed)
        self.assertNotIn("giver", labels)
        self.assertNotIn("king james", labels)

    def test_unmatched_chunks_still_appear_as_sources(self):
        from core.views import visible_chat_source_docs

        orphan = self._chunk(source="Walking in Love.pdf", file_hash="z" * 64, title="Walking in Love")
        public = visible_chat_source_docs([orphan])
        self.assertEqual(len(public), 1)
