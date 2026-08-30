import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.embedded_videos import (
    get_embedded_video,
    list_embedded_videos,
    parse_vimeo_id,
    parse_vimeo_id_from_filename,
    segments_from_sidecar_payload,
)
from core.models import IngestedDocument


class EmbeddedVideoMatchingTests(TestCase):
    def test_parses_vimeo_ids_from_numeric_stems(self):
        self.assertEqual(parse_vimeo_id("1217796650"), "1217796650")
        self.assertEqual(parse_vimeo_id_from_filename("1217796650.m4a"), "1217796650")
        self.assertIsNone(parse_vimeo_id("sermon"))
        self.assertIsNone(parse_vimeo_id_from_filename("faith_that_moves.mp4"))

    def test_prefers_normalized_sidecar_segments(self):
        segments = segments_from_sidecar_payload(
            {
                "segments_raw": [{"start": 0, "end": 2, "text": "raw hello"}],
                "segments_normalized": [{"start": 12, "end": 34, "text": "Jesus is Lord."}],
            }
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "Jesus is Lord.")
        self.assertEqual(segments[0].range_label, "00:12–00:34")

    def test_featured_vimeo_is_listed_without_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos = list_embedded_videos(Path(tmp))
        self.assertTrue(videos)
        featured = videos[0]
        self.assertEqual(featured.vimeo_id, "1217796650")
        self.assertTrue(featured.featured)
        self.assertFalse(featured.has_transcript)
        self.assertEqual(
            featured.watch_url,
            "https://vimeo.com/1217796650?fl=ip&fe=ec",
        )
        self.assertEqual(featured.embed_url, "https://player.vimeo.com/video/1217796650")

    def test_featured_video_uses_mapped_ingest_transcript(self):
        IngestedDocument.objects.create(
            source_name="382080991.m4a",
            title="382080991",
            file_hash="c" * 64,
            original_extension=".m4a",
            source_kind="video",
            chunk_count=3,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "382080991.m4a").write_bytes(b"audio")
            (root / "382080991.transcript.json").write_text(
                json.dumps(
                    {
                        "title": "382080991",
                        "source_name": "382080991.m4a",
                        "whisper_model": "base",
                        "segments_normalized": [
                            {
                                "start": 0,
                                "end": 14,
                                "text": "With man it may be impossible, but with God it is not.",
                            },
                            {
                                "start": 57,
                                "end": 80,
                                "text": "We're in Genesis 11 today on day four. Yes. January 4th.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            video = get_embedded_video("1217796650", upload_dir=root)
        self.assertIsNotNone(video)
        self.assertTrue(video.has_transcript)
        self.assertEqual(video.source_name, "382080991.m4a")
        self.assertEqual(video.transcript_source, "382080991.transcript.json")
        self.assertEqual(video.title, "Walk Through the Word — January 4")
        self.assertEqual(
            video.segments[1].text,
            "We're in Genesis 11 today on day four. Yes. January 4th.",
        )

    def test_matches_sidecar_and_document_title(self):
        IngestedDocument.objects.create(
            source_name="1217796650.m4a",
            title="Sunday Sermon on Faith",
            file_hash="a" * 64,
            original_extension=".m4a",
            source_kind="video",
            chunk_count=2,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1217796650.m4a").write_bytes(b"audio")
            (root / "1217796650.transcript.json").write_text(
                json.dumps(
                    {
                        "title": "1217796650",
                        "source_name": "1217796650.m4a",
                        "whisper_model": "base",
                        "segments_normalized": [
                            {"start": 5, "end": 12, "text": "Faith without works is dead."},
                            {"start": 12, "end": 20, "text": "James teaches this clearly."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            video = get_embedded_video("1217796650", upload_dir=root)
        self.assertIsNotNone(video)
        self.assertEqual(video.title, "Sunday Sermon on Faith")
        self.assertTrue(video.has_transcript)
        self.assertEqual(video.transcript_segment_count, 2)
        self.assertEqual(video.source_name, "1217796650.m4a")
        self.assertEqual(video.segments[0].text, "Faith without works is dead.")
        self.assertEqual(video.embed_src, "https://player.vimeo.com/video/1217796650?dnt=1")

    def test_unknown_vimeo_id_is_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(get_embedded_video("999999999", upload_dir=Path(tmp)))
            self.assertIsNone(get_embedded_video("not-an-id", upload_dir=Path(tmp)))


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class EmbeddedVideosAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_embedded_video_urls_resolve(self):
        self.assertEqual(reverse("admin:core_embedded_videos"), "/admin/core/embedded-videos/")
        self.assertEqual(
            reverse("admin:core_embedded_video_detail", args=["1217796650"]),
            "/admin/core/embedded-videos/1217796650/",
        )

    def test_anonymous_user_is_redirected(self):
        self.client.logout()
        response = self.client.get(reverse("admin:core_embedded_videos"))
        self.assertEqual(response.status_code, 302)

    def test_non_staff_user_is_redirected(self):
        self.client.logout()
        User.objects.create_user(username="member", password="pass", is_staff=False)
        self.client.login(username="member", password="pass")
        response = self.client.get(reverse("admin:core_embedded_videos"))
        self.assertEqual(response.status_code, 302)

    def test_list_page_includes_featured_vimeo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=Path(tmp)):
                response = self.client.get(reverse("admin:core_embedded_videos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Embedded Videos")
        self.assertContains(response, "1217796650")
        self.assertContains(response, "Watch with transcript")

    def test_detail_embeds_vimeo_and_matched_transcript(self):
        IngestedDocument.objects.create(
            source_name="1217796650.m4a",
            title="Matched Sermon Audio",
            file_hash="b" * 64,
            original_extension=".m4a",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1217796650.m4a").write_bytes(b"audio")
            (root / "1217796650.transcript.json").write_text(
                json.dumps(
                    {
                        "title": "1217796650",
                        "source_name": "1217796650.m4a",
                        "whisper_model": "base",
                        "segments_normalized": [
                            {"start": 8, "end": 16, "text": "The Lord is my shepherd."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["1217796650"])
                )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player.vimeo.com/video/1217796650")
        self.assertContains(response, "https://vimeo.com/1217796650?fl=ip&amp;fe=ec")
        self.assertContains(response, "Matched Sermon Audio")
        self.assertContains(response, "1217796650.m4a")
        self.assertContains(response, "The Lord is my shepherd.")
        self.assertContains(response, "00:08–00:16")
        self.assertContains(response, "player.vimeo.com/api/player.js")
        self.assertContains(response, ".embedded-player-frame iframe")
        self.assertContains(response, "width: 100%")
        self.assertContains(response, "height: 100%")

    def test_detail_shows_empty_transcript_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=Path(tmp)):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["1217796650"])
                )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player.vimeo.com/video/1217796650")
        self.assertContains(response, "No matching transcript was found")

    def test_detail_uses_mapped_ingest_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "382080991.transcript.json").write_text(
                json.dumps(
                    {
                        "title": "382080991",
                        "source_name": "382080991.m4a",
                        "segments_normalized": [
                            {"start": 57, "end": 80, "text": "Genesis 11 today on day four. January 4th."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["1217796650"])
                )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Walk Through the Word — January 4")
        self.assertContains(response, "Genesis 11 today on day four. January 4th.")
        self.assertContains(response, "382080991.transcript.json")
        self.assertNotContains(response, "No matching transcript was found")

    def test_unknown_detail_is_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=Path(tmp)):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["424242424"])
                )
        self.assertEqual(response.status_code, 404)

    def test_admin_home_card_links_to_embedded_videos(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Embedded Videos")
        self.assertContains(response, reverse("admin:core_embedded_videos"))
