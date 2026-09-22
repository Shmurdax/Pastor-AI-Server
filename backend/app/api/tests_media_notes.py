from pathlib import Path
from unittest.mock import patch
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.dropbox_notes import (
    DropboxNotesError,
    dropbox_notes_configured,
    enqueue_dropbox_notes_ingest,
    list_dropbox_note_files,
)
from api.media_notes import attach_notes_to_media_videos, notes_match_score
from api.models import MediaVideo
from core.models import IngestedDocument


def _doc(**kwargs):
    defaults = {
        "source_name": "January 4.pdf",
        "title": "January 4",
        "file_hash": "a" * 64,
        "original_extension": ".pdf",
        "source_kind": "document",
        "chunk_count": 1,
        "in_library": True,
    }
    defaults.update(kwargs)
    return IngestedDocument.objects.create(**defaults)


def _video(**kwargs):
    defaults = {
        "vimeo_id": "403856658",
        "title": "January 4",
        "published_at": timezone.now(),
        "is_published": True,
    }
    defaults.update(kwargs)
    return MediaVideo.objects.create(**defaults)


class NotesMatchScoreTests(TestCase):
    def test_date_only_title_matches(self):
        self.assertGreaterEqual(notes_match_score("January 4", "January 4.pdf", "January 4"), 70)
        self.assertGreaterEqual(notes_match_score("Copy of April 10", "april_10.pdf", "April 10"), 70)

    def test_topical_sermon_does_not_auto_match(self):
        self.assertEqual(
            notes_match_score("Faith That Moves Mountains", "faith.pdf", "January 4"),
            0,
        )
        self.assertLess(
            notes_match_score("Christmas Eve December 24 Candlelight", "xmas.pdf", "December 24"),
            70,
        )


class AttachMediaNotesTests(TestCase):
    def test_attaches_date_named_notes_to_matching_video(self):
        video = _video()
        notes = _doc()
        stats = attach_notes_to_media_videos()
        video.refresh_from_db()
        self.assertEqual(stats["attached"], 1)
        self.assertEqual(video.notes_document_id, notes.id)

    def test_does_not_overwrite_manual_notes(self):
        kept = _doc(source_name="kept.pdf", title="Kept Notes", file_hash="b" * 64)
        video = _video(notes_document=kept, notes_document_manual=True)
        _doc(source_name="January 4.pdf", title="January 4", file_hash="c" * 64)
        attach_notes_to_media_videos()
        video.refresh_from_db()
        self.assertEqual(video.notes_document_id, kept.id)

    def test_does_not_attach_unrelated_sermon_pdf(self):
        video = _video()
        _doc(
            source_name="Faith That Moves Mountains.pdf",
            title="Faith That Moves Mountains",
            file_hash="d" * 64,
        )
        attach_notes_to_media_videos()
        video.refresh_from_db()
        self.assertIsNone(video.notes_document_id)


class DropboxNotesTests(TestCase):
    def test_lists_document_files_and_skips_other_types(self):
        payload = {
            "entries": [
                {
                    ".tag": "file",
                    "name": "January 4.pdf",
                    "path_display": "/WTTW/2024/January 4.pdf",
                },
                {".tag": "file", "name": "clip.mp4", "path_display": "/WTTW/clip.mp4"},
                {".tag": "folder", "name": "2024", "path_display": "/WTTW/2024"},
            ],
            "has_more": False,
        }

        class _Response:
            status_code = 200
            text = ""

            def json(self):
                return payload

        with patch("api.dropbox_notes.requests.post", return_value=_Response()):
            files = list_dropbox_note_files(token="token", folder="/WTTW")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].ingest_name, "January 4 2024.pdf")

    def test_enqueue_downloads_and_queues_ingest(self):
        list_payload = {
            "entries": [
                {
                    ".tag": "file",
                    "name": "January 4.pdf",
                    "path_display": "/Notes/January 4.pdf",
                }
            ],
            "has_more": False,
        }

        class _ListResponse:
            status_code = 200
            text = ""

            def json(self):
                return list_payload

        class _DownloadResponse:
            status_code = 200
            text = ""
            content = b"%PDF-1.4 notes"

        def fake_post(url, **kwargs):
            if url.endswith("/files/list_folder"):
                return _ListResponse()
            if url.endswith("/files/download"):
                return _DownloadResponse()
            raise AssertionError(url)

        with patch("api.dropbox_notes.requests.post", side_effect=fake_post):
            with patch("api.dropbox_notes.enqueue_ingestion_job") as enqueue:
                with tempfile.TemporaryDirectory() as tmp:
                    with override_settings(BASE_DIR=tmp):
                        job = enqueue_dropbox_notes_ingest(token="token", folder="/Notes")
                        self.assertEqual(job.files_received, 1)
                        enqueue.assert_called_once()
                        staged = enqueue.call_args[0][1]
                        self.assertEqual(staged[0].original_name, "January 4.pdf")
                        self.assertTrue(Path(staged[0].staged_path).is_file())

    def test_missing_token_is_a_clear_error(self):
        with self.assertRaises(DropboxNotesError):
            list_dropbox_note_files(token="", folder="/Notes")

    def test_configured_requires_token_and_folder(self):
        self.assertFalse(dropbox_notes_configured(token="", folder="/Notes", shared_url=""))
        self.assertTrue(dropbox_notes_configured(token="sl.abc", folder="/Notes", shared_url=""))


@override_settings(
    ROOT_URLCONF="pastor_ai.urls",
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
)
class MediaNotesApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="premium@test.com",
            email="premium@test.com",
            password="PremiumPass123!",
        )
        self.user.profile.subscription_status = "active"
        self.user.profile.save(update_fields=["subscription_status"])
        self.token = Token.objects.create(user=self.user).key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_media_list_includes_notes_url(self):
        notes = _doc()
        _video(notes_document=notes)
        res = self.client.get("/api/media/")
        self.assertEqual(res.status_code, 200)
        row = res.data["results"][0]
        self.assertEqual(row["notes_document_id"], notes.id)
        self.assertEqual(row["notes_title"], "January 4")
        self.assertIn("/api/media/403856658/notes/", row["notes_file_url"])

    def test_notes_file_serves_attached_pdf(self):
        import tempfile

        notes = _doc()
        _video(notes_document=notes)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "January 4.pdf"
            pdf.write_bytes(b"%PDF-1.4 notes")
            with patch("core.views.ingested_media_path", return_value=pdf):
                res = self.client.get("/api/media/403856658/notes/")
        self.assertEqual(res.status_code, 200)
        body = b"".join(res.streaming_content)
        self.assertIn(b"%PDF-1.4", body)

    def test_notes_file_404_when_unattached(self):
        _video()
        res = self.client.get("/api/media/403856658/notes/")
        self.assertEqual(res.status_code, 404)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
)
class DropboxNotesAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_admin_page_and_home_card(self):
        prefix = f"/{settings.ADMIN_URL_PATH}"
        self.assertEqual(reverse("admin:core_dropbox_notes"), f"{prefix}/core/dropbox-notes/")
        home = self.client.get(f"{prefix}/")
        self.assertContains(home, "Dropbox notes")
        self.assertContains(home, reverse("admin:core_dropbox_notes"))
        page = self.client.get(reverse("admin:core_dropbox_notes"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Download notes from Dropbox")
        self.assertContains(page, "DROPBOX_ACCESS_TOKEN")
