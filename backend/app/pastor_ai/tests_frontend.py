import tempfile
import unittest
from pathlib import Path

from django.test import TestCase, override_settings


class VimeoEmbedFrameTests(TestCase):
    def test_vimeo_embed_allows_same_origin_iframe(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text(
                "<html><body><div id=app></div></body></html>",
                encoding="utf-8",
            )
            (root / "vimeo_embed.html").write_text(
                "<html><body>vimeo relay</body></html>",
                encoding="utf-8",
            )
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                embed = self.client.get("/vimeo_embed.html")
                home = self.client.get("/")
        self.assertEqual(embed.status_code, 200)
        self.assertEqual(embed["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(embed, "vimeo relay")
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home["X-Frame-Options"], "DENY")
        self.assertNotContains(home, "/api/chat/warmup/")
        self.assertNotContains(home, "__pastorVllmWarmup")

    def test_vimeo_embed_survives_stale_flutter_build(self):
        """Media page iframes /vimeo_embed.html; sermon-sources do not need it."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text(
                "<html><body><div id=app></div></body></html>",
                encoding="utf-8",
            )
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                embed = self.client.get("/vimeo_embed.html?id=403856658&h=6bce8bb9e6")
        self.assertEqual(embed.status_code, 200)
        self.assertEqual(embed["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(embed, "player.vimeo.com/video/")
        self.assertContains(embed, "dnt=1")


if __name__ == "__main__":
    unittest.main()
