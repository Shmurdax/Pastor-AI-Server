from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings


class VimeoEmbedFrameOptionsTests(TestCase):
    def test_vimeo_embed_allows_same_origin_iframe(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vimeo_embed.html").write_text("<html></html>", encoding="utf-8")
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                response = self.client.get("/vimeo_embed.html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_home_stays_clickjack_denied(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
