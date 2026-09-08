import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from api.models import MediaVideo
from core.embedded_videos import (
    get_embedded_video,
    list_embedded_videos,
    parse_vimeo_id,
    parse_vimeo_id_from_filename,
    segments_from_sidecar_payload,
    sermon_date_key,
    vimeo_embed_url,
)
from core.models import IngestedDocument


class EmbeddedVideoMatchingTests(TestCase):
    def test_parses_vimeo_ids_from_numeric_stems(self):
        self.assertEqual(parse_vimeo_id("1217796650"), "1217796650")
        self.assertEqual(parse_vimeo_id_from_filename("1217796650.m4a"), "1217796650")
        self.assertIsNone(parse_vimeo_id("sermon"))
        self.assertIsNone(parse_vimeo_id_from_filename("faith_that_moves.mp4"))

    def test_sermon_date_key_from_titles_and_filenames(self):
        self.assertEqual(sermon_date_key("April 10"), "04-10")
        self.assertEqual(sermon_date_key("Copy of January 4"), "01-04")
        self.assertEqual(sermon_date_key("april_10_v1_240p.mp4"), "04-10")
        self.assertEqual(sermon_date_key("april_1_v1 (240p).mp4"), "04-01")
        self.assertEqual(sermon_date_key("mar_19_v1_240p.mp4"), "03-19")
        self.assertEqual(sermon_date_key("Mar 19"), "03-19")
        self.assertEqual(sermon_date_key("may_15_v2 (240p).mp4"), "05-15")
        self.assertIsNone(sermon_date_key("faith_that_moves.mp4"))

    def test_embed_url_includes_privacy_hash(self):
        self.assertEqual(
            vimeo_embed_url("403856658", "6bce8bb9e6"),
            "https://player.vimeo.com/video/403856658?h=6bce8bb9e6",
        )

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

    def test_matches_downloaded_mp4_to_vimeo_date_title(self):
        MediaVideo.objects.create(
            vimeo_id="403856658",
            privacy_hash="6bce8bb9e6",
            title="April 10",
            published_at=timezone.now(),
            duration_seconds=120,
        )
        IngestedDocument.objects.create(
            source_name="april_10_v1_240p.mp4",
            title="April 10 V1 240p",
            file_hash="d" * 64,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=4,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "april_10_v1_240p.mp4").write_bytes(b"video")
            (root / "april_10_v1_240p.transcript.json").write_text(
                json.dumps(
                    {
                        "title": "April 10 V1 240p",
                        "source_name": "april_10_v1_240p.mp4",
                        "whisper_model": "base",
                        "segments_normalized": [
                            {"start": 1, "end": 4, "text": "Open your Bibles to John."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            videos = list_embedded_videos(root)
            video = get_embedded_video("403856658", upload_dir=root)
        matched = [item for item in videos if item.vimeo_id == "403856658"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].title, "April 10")
        self.assertEqual(matched[0].source_name, "april_10_v1_240p.mp4")
        self.assertTrue(matched[0].matched_by_date)
        self.assertTrue(matched[0].has_transcript)
        self.assertEqual(
            matched[0].embed_url,
            "https://player.vimeo.com/video/403856658?h=6bce8bb9e6",
        )
        self.assertEqual(
            matched[0].watch_url,
            "https://vimeo.com/403856658/6bce8bb9e6",
        )
        self.assertIsNotNone(video)
        self.assertEqual(video.title, "April 10")
        self.assertEqual(video.embed_src, "https://player.vimeo.com/video/403856658?h=6bce8bb9e6&dnt=1")
        self.assertEqual(video.segments[0].text, "Open your Bibles to John.")
        self.assertEqual(video.transcript_source, "april_10_v1_240p.transcript.json")

    def test_prefers_original_vimeo_title_over_copy_of(self):
        MediaVideo.objects.create(
            vimeo_id="100000111",
            title="Copy of January 5",
            published_at=timezone.now(),
        )
        MediaVideo.objects.create(
            vimeo_id="100000222",
            title="January 5",
            published_at=timezone.now(),
        )
        IngestedDocument.objects.create(
            source_name="january_5_v1_240p.mp4",
            title="January 5 V1 240p",
            file_hash="e" * 64,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "january_5_v1_240p.mp4").write_bytes(b"video")
            video = get_embedded_video("100000222", upload_dir=root)
            self.assertIsNotNone(video)
            self.assertEqual(video.source_name, "january_5_v1_240p.mp4")
            self.assertIsNone(get_embedded_video("100000111", upload_dir=root))

    def test_duplicate_date_picks_newer_vimeo_id(self):
        MediaVideo.objects.create(
            vimeo_id="416114132",
            title="May 15",
            published_at=timezone.now(),
        )
        MediaVideo.objects.create(
            vimeo_id="418905841",
            title="May 15",
            published_at=timezone.now(),
        )
        IngestedDocument.objects.create(
            source_name="may_15_v2 (240p).mp4",
            title="May 15 V2 240p",
            file_hash="f" * 64,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "may_15_v2 (240p).mp4").write_bytes(b"video")
            video = get_embedded_video("418905841", upload_dir=root)
            self.assertIsNotNone(video)
            self.assertEqual(video.source_name, "may_15_v2 (240p).mp4")
            self.assertIsNone(get_embedded_video("416114132", upload_dir=root))

    def test_unmatched_catalog_video_is_not_listed(self):
        MediaVideo.objects.create(
            vimeo_id="402000000",
            title="February 1",
            published_at=timezone.now(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            videos = list_embedded_videos(Path(tmp))
        self.assertFalse(any(item.vimeo_id == "402000000" for item in videos))


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
        prefix = f"/{settings.ADMIN_URL_PATH}"
        self.assertEqual(reverse("admin:core_embedded_videos"), f"{prefix}/core/embedded-videos/")
        self.assertEqual(
            reverse("admin:core_embedded_video_detail", args=["1217796650"]),
            f"{prefix}/core/embedded-videos/1217796650/",
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

    def test_list_page_includes_date_matched_download(self):
        MediaVideo.objects.create(
            vimeo_id="403856658",
            privacy_hash="6bce8bb9e6",
            title="April 10",
            published_at=timezone.now(),
        )
        IngestedDocument.objects.create(
            source_name="april_10_v1_240p.mp4",
            title="April 10 V1 240p",
            file_hash="aa" * 32,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=2,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "april_10_v1_240p.mp4").write_bytes(b"video")
            (root / "april_10_v1_240p.transcript.json").write_text(
                json.dumps({"segments_normalized": [{"start": 0, "end": 2, "text": "Amen."}]}),
                encoding="utf-8",
            )
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                response = self.client.get(reverse("admin:core_embedded_videos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "April 10")
        self.assertContains(response, "403856658")
        self.assertContains(response, "april_10_v1_240p.mp4")
        self.assertContains(response, "Matched by sermon date")
        self.assertContains(response, "player.vimeo.com/video/403856658?h=6bce8bb9e6")

    def test_detail_embeds_date_matched_download(self):
        MediaVideo.objects.create(
            vimeo_id="403856658",
            privacy_hash="6bce8bb9e6",
            title="April 10",
            published_at=timezone.now(),
        )
        IngestedDocument.objects.create(
            source_name="april_10_v1_240p.mp4",
            title="April 10 V1 240p",
            file_hash="ab" * 32,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "april_10_v1_240p.mp4").write_bytes(b"video")
            (root / "april_10_v1_240p.transcript.json").write_text(
                json.dumps(
                    {
                        "source_name": "april_10_v1_240p.mp4",
                        "segments_normalized": [
                            {"start": 3, "end": 8, "text": "This is the day the Lord has made."},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["403856658"])
                )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player.vimeo.com/video/403856658?h=6bce8bb9e6")
        self.assertContains(response, "april_10_v1_240p.mp4")
        self.assertContains(response, "This is the day the Lord has made.")
        self.assertContains(response, "00:03–00:08")

    def test_unknown_detail_is_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=Path(tmp)):
                response = self.client.get(
                    reverse("admin:core_embedded_video_detail", args=["424242424"])
                )
        self.assertEqual(response.status_code, 404)

    def test_admin_home_card_links_to_embedded_videos(self):
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Embedded Videos")
        self.assertContains(response, reverse("admin:core_embedded_videos"))
