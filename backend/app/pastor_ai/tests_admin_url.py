from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from pastor_ai.admin_url import (
    DEFAULT_ADMIN_URL_PATH,
    frontend_catch_all_pattern,
    is_admin_request_path,
    normalize_admin_url_path,
)
from pastor_ai.robots import NOINDEX_HEADER_VALUE, path_requires_noindex


class NormalizeAdminUrlPathTests(SimpleTestCase):
    def test_default_when_empty(self):
        self.assertEqual(normalize_admin_url_path(""), DEFAULT_ADMIN_URL_PATH)
        self.assertEqual(normalize_admin_url_path("  /  "), DEFAULT_ADMIN_URL_PATH)

    def test_strips_slashes_and_non_alnum(self):
        self.assertEqual(
            normalize_admin_url_path("/rB4zKwO2wTBCD3pAxRIdTWsvw0w8/"),
            "rB4zKwO2wTBCD3pAxRIdTWsvw0w8",
        )
        self.assertEqual(normalize_admin_url_path("abc-def_ghi1234"), "abcdefghi1234")

    def test_rejects_reserved_and_short_paths(self):
        with self.assertRaises(ValueError):
            normalize_admin_url_path("admin")
        with self.assertRaises(ValueError):
            normalize_admin_url_path("api")
        with self.assertRaises(ValueError):
            normalize_admin_url_path("short")

    def test_frontend_pattern_excludes_secret_admin(self):
        pattern = frontend_catch_all_pattern("rB4zKwO2wTBCD3pAxRIdTWsvw0w8")
        self.assertIn("rB4zKwO2wTBCD3pAxRIdTWsvw0w8/", pattern)
        self.assertIn("api/", pattern)


@override_settings(
    ROOT_URLCONF="pastor_ai.urls",
    FRONTEND_BUILD_DIR="/nonexistent-frontend-for-admin-url-tests",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class AdminUrlRoutingTests(TestCase):
    def test_public_admin_paths_are_404(self):
        for path in ("/admin/", "/admin/login/", "/admin/core/ingestion/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)

    def test_secret_admin_login_is_reachable(self):
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/login/", follow=False)
        self.assertIn(response.status_code, (200, 302))
        self.assertNotEqual(response.status_code, 404)

    def test_secret_admin_home_requires_staff(self):
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/{settings.ADMIN_URL_PATH}/login/", response["Location"])

    def test_staff_can_open_secret_admin_home(self):
        User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="staff", password="pass")
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/")
        self.assertEqual(response.status_code, 200)

    def test_robots_txt_does_not_advertise_secret_path(self):
        response = self.client.get("/robots.txt")
        body = response.content.decode()
        self.assertIn("Disallow: /admin/", body)
        self.assertNotIn(settings.ADMIN_URL_PATH, body)

    def test_secret_admin_has_noindex_header(self):
        response = self.client.get(f"/{settings.ADMIN_URL_PATH}/login/")
        self.assertEqual(response["X-Robots-Tag"], NOINDEX_HEADER_VALUE)

    def test_path_requires_noindex_covers_decoy_and_secret(self):
        self.assertTrue(path_requires_noindex("/admin/"))
        self.assertTrue(path_requires_noindex(f"/{settings.ADMIN_URL_PATH}/"))
        self.assertTrue(path_requires_noindex(f"/{settings.ADMIN_URL_PATH}/login/"))
        self.assertTrue(is_admin_request_path("/admin/", settings.ADMIN_URL_PATH))
        self.assertFalse(is_admin_request_path("/", settings.ADMIN_URL_PATH))
