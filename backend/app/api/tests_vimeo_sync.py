from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from unittest.mock import patch

from api.models import MediaVideo
from api.vimeo_sync import (
    _extract_vimeo_id_and_hash,
    privacy_hash_from_video,
    sync_vimeo_media,
)


class VimeoPrivacyHashTests(SimpleTestCase):
    def test_extracts_hash_from_unlisted_uri(self):
        video_id, privacy_hash = _extract_vimeo_id_and_hash("/videos/403856658:6bce8bb9e6")
        self.assertEqual(video_id, "403856658")
        self.assertEqual(privacy_hash, "6bce8bb9e6")

    def test_reads_hash_from_player_embed_url(self):
        hash_value = privacy_hash_from_video(
            {
                "player_embed_url": "https://player.vimeo.com/video/403856658?h=6bce8bb9e6",
                "link": "https://vimeo.com/403856658",
            }
        )
        self.assertEqual(hash_value, "6bce8bb9e6")

    def test_uri_hash_wins_over_embed_url(self):
        hash_value = privacy_hash_from_video(
            {"player_embed_url": "https://player.vimeo.com/video/1?h=aaaaaaaaaa"},
            uri_hash="bbbbbbbbbb",
        )
        self.assertEqual(hash_value, "bbbbbbbbbb")


class VimeoSyncHashPersistenceTests(TestCase):
    @patch("api.vimeo_sync._fetch_folder_videos")
    def test_sync_stores_embed_privacy_hash(self, fetch_videos):
        fetch_videos.return_value = [
            {
                "uri": "/videos/403856658",
                "name": "April 10",
                "description": "",
                "duration": 90,
                "player_embed_url": "https://player.vimeo.com/video/403856658?h=6bce8bb9e6",
                "link": "https://vimeo.com/403856658",
                "created_time": timezone.now().isoformat(),
                "pictures": {},
            }
        ]
        result = sync_vimeo_media(token="token", folder_id="24205069", user_id="21759939")
        self.assertEqual(result["created"], 1)
        row = MediaVideo.objects.get(vimeo_id="403856658")
        self.assertEqual(row.privacy_hash, "6bce8bb9e6")
        self.assertEqual(row.title, "April 10")
