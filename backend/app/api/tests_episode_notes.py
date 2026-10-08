import ast
import inspect
import os
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from fpdf import FPDF
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.episode_notes import (
    extract_note_topics,
    import_episode_notes,
    reflow_note_text,
)
from api.models import EpisodeNote, MediaVideo
from core.embedded_videos import parse_episode_date, sermon_date_key
from core.models import IngestedChunk, IngestedDocument


def _pdf_bytes(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def _note_text() -> str:
    return (
        "Day 135 May 15\n\n"
        "The Queen of Sheba traveled across the desert to visit Solomon.\n"
        "Sheba came with hard questions. Solomon had the anointing.\n\n"
        "#TheNameOfTheLord\n"
        "#makemeamagnet\n"
    )


class EpisodeDateParseTests(SimpleTestCase):
    def test_filename_patterns_keep_the_year(self):
        expected = datetime(2026, 5, 15).date()
        self.assertEqual(parse_episode_date("May 15_2026.pdf"), expected)
        self.assertEqual(parse_episode_date("May 15, 2026.pdf"), expected)
        self.assertEqual(parse_episode_date("May_15_2026.pdf"), expected)
        self.assertEqual(parse_episode_date("May 15th, 2026"), expected)

    def test_month_and_day_without_a_year_are_not_an_episode_date(self):
        self.assertIsNone(parse_episode_date("May 15"))
        self.assertIsNone(parse_episode_date("may_15_v2 (240p).mp4"))
        self.assertEqual(sermon_date_key("May 15_2026.pdf"), "05-15")
        self.assertEqual(sermon_date_key("may_15_v2 (240p).mp4"), "05-15")

    def test_invalid_calendar_dates_are_rejected(self):
        self.assertIsNone(parse_episode_date("February 31_2026.pdf"))

    def test_reflow_unwraps_lines_and_keeps_bullets_and_hashtags(self):
        raw = (
            "The Queen of Sheba traveled\n"
            "across the desert.\n"
            "\n"
            "•\n"
            "She came to test Solomon\n"
            "with hard questions.\n"
            "\n"
            "#TheNameOfTheLord\n"
            "-- 1 of 2 --\n"
        )
        text = reflow_note_text(raw)
        self.assertIn("The Queen of Sheba traveled across the desert.", text)
        self.assertIn("• She came to test Solomon with hard questions.", text)
        self.assertIn("#TheNameOfTheLord", text)
        self.assertNotIn("1 of 2", text)

    def test_topics_prefer_hashtags_then_repeated_words(self):
        topics = extract_note_topics(reflow_note_text(_note_text()))
        self.assertIn("TheNameOfTheLord", topics)
        self.assertIn("makemeamagnet", topics)
        self.assertIn("sheba", topics)
        self.assertNotIn("walkthroughtheword", [item.lower() for item in topics])

    def test_module_does_not_call_the_knowledge_base(self):
        source = inspect.getsource(__import__("api.episode_notes", fromlist=["episode_notes"]))
        imported: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported.extend(alias.name for alias in node.names)
        blob = " ".join(imported).lower()
        self.assertNotIn("qdrant", blob)
        self.assertNotIn("ingest_uploaded_files", blob)
        self.assertNotIn("ingesteddocument", blob)


class EpisodeNoteImportTests(TestCase):
    def setUp(self):
        self.may_2025 = MediaVideo.objects.create(
            vimeo_id="may-2025",
            title="May 15",
            description="Previous year",
            published_at=timezone.make_aware(datetime(2025, 5, 15, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        self.may_2026 = MediaVideo.objects.create(
            vimeo_id="may-2026",
            title="Copy of May 15",
            description="Queen of Sheba study",
            published_at=timezone.make_aware(datetime(2026, 5, 15, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        self.unpublished = MediaVideo.objects.create(
            vimeo_id="june-hidden",
            title="June 2",
            description="",
            published_at=timezone.make_aware(datetime(2026, 6, 2, 15, 0)),
            duration_seconds=600,
            is_published=False,
        )

    def test_import_links_the_matching_year_and_skips_the_knowledge_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            stored = root / "stored"
            inbox.mkdir()
            (inbox / "May 15_2026.pdf").write_bytes(_pdf_bytes(_note_text()))
            (inbox / "June 2_2026.pdf").write_bytes(_pdf_bytes("Day 153 June 2\n\nA quiet reading."))
            (inbox / "outline.pdf").write_bytes(_pdf_bytes("No date in this name."))
            (inbox / "notes.txt").write_text("ignore me", encoding="utf-8")

            with patch.dict(os.environ, {"EPISODE_NOTES_DIR": str(stored)}), patch(
                "core.ingestion_service.ingest_uploaded_files"
            ) as ingest:
                first = StringIO()
                call_command("import_episode_notes", str(inbox), stdout=first)
                ingest.assert_not_called()
                self.assertIn("created=2", first.getvalue())
                self.assertIn("June 2_2026.pdf", first.getvalue())
                self.assertIn("outline.pdf", first.getvalue())

                second = StringIO()
                call_command("import_episode_notes", str(inbox), stdout=second)
                self.assertIn("created=0", second.getvalue())
                self.assertIn("updated=2", second.getvalue())

            self.assertEqual(IngestedDocument.objects.count(), 0)
            self.assertEqual(IngestedChunk.objects.count(), 0)
            self.assertEqual(EpisodeNote.objects.count(), 2)

            linked = EpisodeNote.objects.get(episode_date=datetime(2026, 5, 15).date())
            self.assertEqual(linked.media_video_id, self.may_2026.id)
            self.assertNotEqual(linked.media_video_id, self.may_2025.id)
            self.assertIn("Sheba", linked.search_text)
            self.assertIn("TheNameOfTheLord", linked.topics)
            stored_pdf = stored / "2026-05-15.pdf"
            self.assertTrue(stored_pdf.is_file())
            self.assertTrue(stored_pdf.read_bytes().startswith(b"%PDF"))
            self.assertEqual(stored_pdf.parent.resolve(), stored.resolve())

            unlinked = EpisodeNote.objects.get(episode_date=datetime(2026, 6, 2).date())
            self.assertIsNone(unlinked.media_video_id)

    def test_import_keeps_a_note_when_pdf_text_has_a_broken_character(self):
        class FakePage:
            def extract_text(self):
                return (
                    "The Queen of Sheba \ud83d traveled far. \ud83d\ude00\n\n"
                    "#TheNameOfTheLord\n"
                )

        class FakeReader:
            def __init__(self, path):
                self.pages = [FakePage()]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            (inbox / "May 15_2026.pdf").write_bytes(_pdf_bytes(_note_text()))
            with patch.dict(os.environ, {"EPISODE_NOTES_DIR": str(root / "stored")}), patch(
                "pypdf.PdfReader", FakeReader
            ):
                import_episode_notes(inbox)

        note = EpisodeNote.objects.get(episode_date=datetime(2026, 5, 15).date())
        note.search_text.encode("utf-8")
        self.assertIn("Sheba", note.search_text)
        self.assertIn("😀", note.search_text)
        self.assertNotRegex(note.search_text, r"[\ud800-\udfff]")
        self.assertIn("TheNameOfTheLord", note.topics)

    def test_note_links_when_the_only_video_for_that_day_is_another_year(self):
        march = MediaVideo.objects.create(
            vimeo_id="mar-16-2020",
            title="Mar 16",
            description="",
            published_at=timezone.make_aware(datetime(2020, 3, 16, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            (inbox / "Mar 16_2026.pdf").write_bytes(_pdf_bytes("Day 75 March 16\n\nA reading for the day."))
            with patch.dict(os.environ, {"EPISODE_NOTES_DIR": str(root / "stored")}):
                result = import_episode_notes(inbox)
        self.assertEqual(result["unlinked"], [])
        note = EpisodeNote.objects.get(episode_date=datetime(2026, 3, 16).date())
        self.assertEqual(note.media_video_id, march.id)

    def test_same_day_prefers_the_closer_published_video(self):
        later = MediaVideo.objects.create(
            vimeo_id="may-2026-later",
            title="May 15",
            description="",
            published_at=timezone.make_aware(datetime(2026, 5, 20, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            (inbox / "May 15_2026.pdf").write_bytes(_pdf_bytes(_note_text()))
            with patch.dict(os.environ, {"EPISODE_NOTES_DIR": str(root / "stored")}):
                import_episode_notes(inbox)
        note = EpisodeNote.objects.get(episode_date=datetime(2026, 5, 15).date())
        self.assertEqual(note.media_video_id, self.may_2026.id)
        self.assertNotEqual(note.media_video_id, later.id)


class EpisodeNoteApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.member = User.objects.create_user(
            username="free-notes@church.org",
            email="free-notes@church.org",
            password="MemberPass123!",
        )
        self.premium = User.objects.create_user(
            username="premium-notes@church.org",
            email="premium-notes@church.org",
            password="PremiumPass123!",
        )
        self.premium.profile.subscription_status = "active"
        self.premium.profile.save(update_fields=["subscription_status"])
        self.member_token = Token.objects.create(user=self.member).key
        self.premium_token = Token.objects.create(user=self.premium).key

        self.may_video = MediaVideo.objects.create(
            vimeo_id="may-api",
            title="May 15",
            description="Devotional",
            published_at=timezone.make_aware(datetime(2026, 5, 15, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        self.other_video = MediaVideo.objects.create(
            vimeo_id="june-api",
            title="June 2",
            description="Another day",
            published_at=timezone.make_aware(datetime(2026, 6, 2, 15, 0)),
            duration_seconds=600,
            is_published=True,
        )
        self.note = EpisodeNote.objects.create(
            media_video=self.may_video,
            episode_date=datetime(2026, 5, 15).date(),
            original_filename="May 15_2026.pdf",
            stored_filename="2026-05-15.pdf",
            search_text="The Queen of Sheba traveled to Solomon. #TheNameOfTheLord",
            topics=["TheNameOfTheLord", "sheba", "solomon"],
            content_hash="a" * 64,
        )
        self.unlinked = EpisodeNote.objects.create(
            media_video=None,
            episode_date=datetime(2026, 6, 3).date(),
            original_filename="June 3_2026.pdf",
            stored_filename="2026-06-03.pdf",
            search_text="Unlinked note about Sheba should not be public.",
            topics=["sheba"],
            content_hash="b" * 64,
        )

    def test_media_api_returns_notes_and_filters_by_keyword_and_topic(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        listing = self.client.get("/api/media/")
        self.assertEqual(listing.status_code, 200)
        by_title = {row["title"]: row for row in listing.data["results"]}
        self.assertEqual(by_title["May 15"]["note"]["id"], self.note.id)
        self.assertEqual(by_title["May 15"]["note"]["episode_date"], "2026-05-15")
        self.assertIn("TheNameOfTheLord", by_title["May 15"]["note"]["topics"])
        self.assertTrue(by_title["May 15"]["note"]["has_notes"])
        self.assertIsNone(by_title["June 2"]["note"])

        keyword = self.client.get("/api/media/", {"q": "sheba"})
        self.assertEqual(keyword.status_code, 200)
        self.assertEqual([row["vimeo_id"] for row in keyword.data["results"]], ["may-api"])
        self.assertIn("Sheba", keyword.data["results"][0]["note"]["snippet"])

        topic = self.client.get("/api/media/", {"topic": "thenameofthelord"})
        self.assertEqual(topic.status_code, 200)
        self.assertEqual([row["vimeo_id"] for row in topic.data["results"]], ["may-api"])

        topics = self.client.get("/api/media/topics/")
        self.assertEqual(topics.status_code, 200)
        self.assertIn("TheNameOfTheLord", topics.data["results"])
        self.assertIn("sheba", topics.data["results"])

        detail = self.client.get(f"/api/episode-notes/{self.note.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Sheba", detail.data["body"])
        missing = self.client.get(f"/api/episode-notes/{self.unlinked.id}/")
        self.assertEqual(missing.status_code, 404)

        docs = self.client.get("/api/ingested-documents/")
        self.assertEqual(docs.status_code, 200)
        self.assertEqual(docs.data["documents"], [])

    def test_note_file_is_the_original_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-05-15.pdf"
            path.write_bytes(_pdf_bytes("Queen of Sheba"))
            self.note.stored_filename = path.name
            self.note.save(update_fields=["stored_filename"])
            with patch.dict(os.environ, {"EPISODE_NOTES_DIR": tmp}):
                self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
                response = self.client.get(f"/api/episode-notes/{self.note.id}/file/")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_free_members_cannot_read_notes(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        self.assertEqual(self.client.get("/api/media/").status_code, 403)
        self.assertEqual(self.client.get("/api/media/topics/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/episode-notes/{self.note.id}/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/episode-notes/{self.note.id}/file/").status_code, 403)
