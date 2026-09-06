from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from pastor_ai.robots import NOINDEX_HEADER_VALUE, path_requires_noindex


class PathRequiresNoindexTests(SimpleTestCase):
    def test_admin_paths(self):
        self.assertTrue(path_requires_noindex("/admin/"))
        self.assertTrue(path_requires_noindex("/admin/login/"))
        self.assertTrue(path_requires_noindex("/admin/core/ingestion/"))
        self.assertTrue(path_requires_noindex(f"/{settings.ADMIN_URL_PATH}/"))
        self.assertTrue(path_requires_noindex(f"/{settings.ADMIN_URL_PATH}/login/"))

    def test_api_paths(self):
        self.assertTrue(path_requires_noindex("/api/"))
        self.assertTrue(path_requires_noindex("/api/chat/"))
        self.assertTrue(path_requires_noindex("/api/auth/login/"))

    def test_public_paths(self):
        self.assertFalse(path_requires_noindex("/"))
        self.assertFalse(path_requires_noindex("/chat"))
        self.assertFalse(path_requires_noindex("/sermons/example.pdf"))


@override_settings(
    ROOT_URLCONF="pastor_ai.urls",
    DJANGO_USE_SQLITE="1",
    FRONTEND_BUILD_DIR="/nonexistent-frontend-for-robots-tests",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class RobotsAndNoindexIntegrationTests(TestCase):
    def test_robots_txt_blocks_admin_and_api_for_all_agents(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        body = response.content.decode()
        self.assertIn("User-agent: *", body)
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /api/", body)

    def test_admin_login_has_noindex_header(self):
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/login/")
        self.assertEqual(response["X-Robots-Tag"], NOINDEX_HEADER_VALUE)

    def test_public_admin_decoy_has_noindex_header(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["X-Robots-Tag"], NOINDEX_HEADER_VALUE)

    def test_api_chat_has_noindex_header(self):
        response = self.client.post("/api/chat/", data={}, content_type="application/json")
        self.assertEqual(response["X-Robots-Tag"], NOINDEX_HEADER_VALUE)

    def test_warmup_route_starts_worker_without_running_chat(self):
        from unittest.mock import patch

        with patch("core.vllm_warmup.warmup_vllm_worker", return_value={
            "ok": True,
            "warming": True,
            "skipped": False,
        }) as mock_warmup:
            response = self.client.post(
                "/api/chat/warmup/",
                data={},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["warming"])
        mock_warmup.assert_called_once()

    def test_home_does_not_have_noindex_header(self):
        response = self.client.get("/")
        self.assertNotIn("X-Robots-Tag", response)
