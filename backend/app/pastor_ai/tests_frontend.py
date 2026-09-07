import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from pastor_ai.frontend import _index_html_with_runtime_injections


class FrontendRuntimeInjectTests(SimpleTestCase):
    def test_injects_warmup_script_before_body_close(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "index.html"
            path.write_text("<html><body><div id=app></div></body></html>", encoding="utf-8")
            html = _index_html_with_runtime_injections(path)
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
            html = _index_html_with_runtime_injections(path)
        self.assertEqual(html.count("__pastorVllmWarmup"), 1)

    @override_settings(GOOGLE_CLIENT_ID="demo-client.apps.googleusercontent.com")
    def test_injects_google_signin_client_id_meta(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "index.html"
            path.write_text("<html><head></head><body></body></html>", encoding="utf-8")
            html = _index_html_with_runtime_injections(path)
        self.assertIn('name="google-signin-client_id"', html)
        self.assertIn('content="demo-client.apps.googleusercontent.com"', html)

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_skips_google_meta_when_unconfigured(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "index.html"
            path.write_text("<html><head></head><body></body></html>", encoding="utf-8")
            html = _index_html_with_runtime_injections(path)
        self.assertNotIn("google-signin-client_id", html)
