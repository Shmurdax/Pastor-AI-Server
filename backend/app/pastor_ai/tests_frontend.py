import tempfile
import unittest
from pathlib import Path

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings


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
        self.assertEqual(home["Permissions-Policy"], "payment=*")
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


class LandingVideoServingTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get_video(self, http_range: str | None = None):
        from pastor_ai.frontend import serve_frontend

        extra = {"HTTP_RANGE": http_range} if http_range else {}
        request = self.factory.get("/videos/landing.mp4", **extra)
        return serve_frontend(request, path="videos/landing.mp4")

    def test_serves_permanent_web_copy_when_build_omits_it(self):
        payload = b"\x00\x00\x00\x18ftypmp42landing"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            build = root / "build" / "web"
            build.mkdir(parents=True)
            (build / "index.html").write_text("<html></html>", encoding="utf-8")
            source = root / "web" / "videos"
            source.mkdir(parents=True)
            (source / "landing.mp4").write_bytes(payload)
            with override_settings(FRONTEND_BUILD_DIR=str(build)):
                response = self._get_video()
                body = b"".join(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertTrue(response["Cache-Control"].startswith("public"))
        self.assertEqual(body, payload)

    def test_build_copy_wins_over_permanent_source(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "videos").mkdir()
            (root / "videos" / "landing.mp4").write_bytes(b"BUILD")
            source = root / "web" / "videos"
            source.mkdir(parents=True)
            (source / "landing.mp4").write_bytes(b"SOURCE")
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                response = self._get_video()
                body = b"".join(response)
        self.assertEqual(body, b"BUILD")

    def test_range_request_returns_a_slice(self):
        payload = b"0123456789abcdef"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "videos").mkdir()
            (root / "videos" / "landing.mp4").write_bytes(payload)
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                response = self._get_video(http_range="bytes=4-7")
                body = b"".join(response)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 4-7/{len(payload)}")
        self.assertEqual(response["Content-Length"], "4")
        self.assertEqual(body, b"4567")

    def test_unsatisfiable_range_is_416(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "videos").mkdir()
            (root / "videos" / "landing.mp4").write_bytes(b"abcd")
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                response = self._get_video(http_range="bytes=20-30")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */4")

    def test_missing_landing_video_is_404(self):
        repo = Path(__file__).resolve().parents[3] / "frontend"
        if (repo / "web" / "videos" / "landing.mp4").is_file() or (
            repo / "build" / "web" / "videos" / "landing.mp4"
        ).is_file():
            self.skipTest("local landing video is present")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            with override_settings(FRONTEND_BUILD_DIR=str(root)):
                with self.assertRaises(Http404):
                    self._get_video()


if __name__ == "__main__":
    unittest.main()
