import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.media_catalog import (
    VIMEO_FOLDER_CATALOG_PATH,
    ensure_media_videos_from_embedded,
    load_committed_vimeo_folder_catalog,
    public_media_catalog,
)
from api.models import MediaVideo
from api.vimeo_sync import sync_vimeo_media
from core.embedded_videos import EmbeddedVideo
from core.models import IngestedDocument


class PublicMediaCatalogTests(TestCase):
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

    def test_api_includes_ingested_vimeo_embeds_without_mediavideo_rows(self):
        IngestedDocument.objects.create(
            source_name="403856658.m4a",
            title="April 10",
            file_hash="a" * 64,
            original_extension=".m4a",
            source_kind="video",
            chunk_count=2,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "403856658.m4a").write_bytes(b"audio")
            (root / "403856658.transcript.json").write_text(
                json.dumps({"segments_normalized": [{"start": 0, "end": 2, "text": "Amen."}]}),
                encoding="utf-8",
            )
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                res = self.client.get("/api/media/")
                catalog = public_media_catalog()

        self.assertEqual(res.status_code, 200)
        ids = [row["vimeo_id"] for row in res.data["results"]]
        self.assertIn("403856658", ids)
        matched = next(row for row in res.data["results"] if row["vimeo_id"] == "403856658")
        self.assertEqual(matched["title"], "April 10")
        self.assertTrue(matched["is_published"])
        self.assertEqual(matched["access_tier"], "premium")
        self.assertIn("1217796650", ids)
        self.assertEqual(len({row["vimeo_id"] for row in catalog}), len(catalog))

    def test_unpublished_folder_row_still_appears_when_backend_embed_exists(self):
        MediaVideo.objects.create(
            vimeo_id="403856658",
            privacy_hash="6bce8bb9e6",
            title="April 10",
            published_at=timezone.now(),
            duration_seconds=90,
            is_published=False,
        )
        IngestedDocument.objects.create(
            source_name="april_10_v1_240p.mp4",
            title="April 10 V1 240p",
            file_hash="b" * 64,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "april_10_v1_240p.mp4").write_bytes(b"video")
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                res = self.client.get("/api/media/")

        self.assertEqual(res.status_code, 200)
        matched = next(row for row in res.data["results"] if row["vimeo_id"] == "403856658")
        self.assertEqual(matched["privacy_hash"], "6bce8bb9e6")
        self.assertEqual(matched["duration_label"], "1:30")
        self.assertTrue(matched["is_published"])

    def test_published_folder_videos_without_local_files_stay_in_catalog(self):
        MediaVideo.objects.create(
            vimeo_id="555000111",
            title="Folder Only Devotional",
            published_at=timezone.now(),
            is_published=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=Path(tmp)):
                res = self.client.get("/api/media/")

        self.assertEqual(res.status_code, 200)
        ids = [row["vimeo_id"] for row in res.data["results"]]
        self.assertIn("555000111", ids)

    def test_ensure_creates_missing_mediavideo_rows(self):
        IngestedDocument.objects.create(
            source_name="403856658.m4a",
            title="April 10",
            file_hash="c" * 64,
            original_extension=".m4a",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "403856658.m4a").write_bytes(b"audio")
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                result = ensure_media_videos_from_embedded()
                again = ensure_media_videos_from_embedded()

        self.assertGreaterEqual(result["created"], 1)
        self.assertEqual(again["created"], 0)
        row = MediaVideo.objects.get(vimeo_id="403856658")
        self.assertEqual(row.title, "April 10")
        self.assertTrue(row.is_published)

    def test_catalog_includes_every_backend_embed(self):
        videos = [
            EmbeddedVideo(
                vimeo_id=str(100000000 + index),
                watch_url=f"https://vimeo.com/{100000000 + index}",
                embed_url=f"https://player.vimeo.com/video/{100000000 + index}",
                title=f"Devotional {index:03d}",
                privacy_hash="abc123" if index % 2 == 0 else "",
            )
            for index in range(300)
        ]
        with patch("api.media_catalog.list_embedded_videos", return_value=videos):
            catalog = public_media_catalog()
        self.assertEqual(len(catalog), 300)
        self.assertEqual(
            {row["vimeo_id"] for row in catalog},
            {video.vimeo_id for video in videos},
        )
        self.assertTrue(all(row["is_published"] for row in catalog))
        even = next(row for row in catalog if row["vimeo_id"] == "100000000")
        self.assertEqual(even["privacy_hash"], "abc123")

    def test_committed_folder_json_upserts_embed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "folder.json"
            catalog.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "vimeo_id": "898217873",
                                "privacy_hash": "1cea8cfd54",
                                "title": "January 4",
                                "published_at": "2023-12-27T23:20:00Z",
                                "duration_seconds": 900,
                                "embed_url": "https://player.vimeo.com/video/898217873?h=1cea8cfd54",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = load_committed_vimeo_folder_catalog(catalog)
            again = load_committed_vimeo_folder_catalog(catalog)
        self.assertEqual(result["created"], 1)
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["updated"], 1)
        row = MediaVideo.objects.get(vimeo_id="898217873")
        self.assertEqual(row.privacy_hash, "1cea8cfd54")
        self.assertEqual(row.title, "January 4")
        self.assertTrue(row.is_published)

    def test_missing_folder_json_is_a_noop(self):
        result = load_committed_vimeo_folder_catalog(Path("/tmp/does-not-exist-folder.json"))
        self.assertEqual(result, {"loaded": 0, "created": 0, "updated": 0})
        self.assertEqual(MediaVideo.objects.count(), 0)

    def test_committed_folder_json_contains_every_live_vimeo_embed(self):
        self.assertTrue(VIMEO_FOLDER_CATALOG_PATH.is_file())
        payload = json.loads(VIMEO_FOLDER_CATALOG_PATH.read_text(encoding="utf-8"))
        videos = payload["videos"]
        self.assertEqual(payload["count"], 369)
        self.assertEqual(len(videos), 369)
        titles = {item["title"] for item in videos}
        self.assertIn("January 4", titles)
        self.assertIn("December 31", titles)
        self.assertTrue(
            all(
                str(item.get("embed_url") or "").startswith("https://player.vimeo.com/video/")
                and str(item.get("privacy_hash") or "").strip()
                for item in videos
            )
        )
        result = load_committed_vimeo_folder_catalog()
        self.assertEqual(result["loaded"], 369)
        self.assertEqual(result["created"], 369)
        january = MediaVideo.objects.get(vimeo_id="898217873")
        self.assertEqual(january.title, "January 4")
        self.assertEqual(january.privacy_hash, "1cea8cfd54")
        self.assertEqual(MediaVideo.objects.filter(is_published=True).count(), 369)


class VimeoSyncUnpublishGuardTests(TestCase):
    @patch("api.vimeo_sync._fetch_folder_videos")
    def test_empty_folder_does_not_unpublish_existing_rows(self, fetch_videos):
        fetch_videos.return_value = []
        MediaVideo.objects.create(
            vimeo_id="403856658",
            title="April 10",
            published_at=timezone.now(),
            is_published=True,
        )
        result = sync_vimeo_media(token="token", folder_id="24205069", user_id="21759939")
        self.assertEqual(result["fetched"], 0)
        self.assertEqual(result["unpublished"], 0)
        self.assertTrue(MediaVideo.objects.get(vimeo_id="403856658").is_published)

    @patch("api.vimeo_sync._fetch_folder_videos")
    def test_folder_sync_keeps_embedded_ingest_matches(self, fetch_videos):
        fetch_videos.return_value = [
            {
                "uri": "/videos/999000111",
                "name": "Still in folder",
                "description": "",
                "duration": 30,
                "created_time": timezone.now().isoformat(),
                "pictures": {},
            }
        ]
        MediaVideo.objects.create(
            vimeo_id="403856658",
            privacy_hash="6bce8bb9e6",
            title="April 10",
            published_at=timezone.now(),
            is_published=True,
        )
        MediaVideo.objects.create(
            vimeo_id="888000222",
            title="Removed from folder",
            published_at=timezone.now(),
            is_published=True,
        )
        IngestedDocument.objects.create(
            source_name="april_10_v1_240p.mp4",
            title="April 10 V1 240p",
            file_hash="d" * 64,
            original_extension=".mp4",
            source_kind="video",
            chunk_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "april_10_v1_240p.mp4").write_bytes(b"video")
            with patch("core.embedded_videos.admin_video_ingestion_dir", return_value=root):
                result = sync_vimeo_media(token="token", folder_id="24205069", user_id="21759939")

        self.assertEqual(result["created"], 1)
        self.assertTrue(MediaVideo.objects.get(vimeo_id="403856658").is_published)
        self.assertFalse(MediaVideo.objects.get(vimeo_id="888000222").is_published)
