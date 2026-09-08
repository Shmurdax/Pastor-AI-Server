import tempfile
import unittest
from pathlib import Path

from django.test import TestCase, override_settings

from pastor_ai.frontend import _index_html_with_warmup


class FrontendWarmupInjectTests(unittest.TestCase):
    def test_injects_warmup_script_before_body_close(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "index.html"
            path.write_text("<html><body><div id=app></div></body></html>", encoding="utf-8")
            html = _index_html_with_warmup(path)
        self.assertIn("__pastorVllmWarmup", html)
        self.assertIn("/api/chat/warmup/", html)
        self.assertIn("</script></body>", html)

    def test_does_not_duplicate_script(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "index.html"
            path.write_text(
                "<html><body>x<script>window.__pastorVllmWarmup=1</script></body></html>",
                encoding="utf-8",
            )
            html = _index_html_with_warmup(path)
        self.assertEqual(html.count("__pastorVllmWarmup"), 1)


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
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
