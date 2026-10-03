from datetime import datetime, timezone as datetime_timezone

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import SiteBanner
from core.site_banner import compose_banner_message, format_banner_time

_ADMIN_TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


class SiteBannerMessageTests(TestCase):
    def test_formats_clock_times(self):
        noon = datetime(2026, 10, 3, 12, 5, tzinfo=datetime_timezone.utc)
        midnight = datetime(2026, 10, 3, 0, 30, tzinfo=datetime_timezone.utc)
        afternoon = datetime(2026, 10, 3, 14, 0, tzinfo=datetime_timezone.utc)
        self.assertEqual(format_banner_time(noon), "Oct 3, 2026, 12:05 PM")
        self.assertEqual(format_banner_time(midnight), "Oct 3, 2026, 12:30 AM")
        self.assertEqual(format_banner_time(afternoon), "Oct 3, 2026, 2:00 PM")

    def test_downtime_sentence(self):
        banner = SiteBanner(
            mode=SiteBanner.MODE_DOWNTIME,
            reason="scheduled maintenance",
            starts_label="Oct 3, 2026, 2:00 PM",
            ends_label="Oct 3, 2026, 6:00 PM",
        )
        self.assertEqual(
            compose_banner_message(banner),
            "Due to scheduled maintenance the service will be down from "
            "Oct 3, 2026, 2:00 PM to Oct 3, 2026, 6:00 PM.",
        )

    def test_custom_message_is_used_as_written(self):
        banner = SiteBanner(
            mode=SiteBanner.MODE_CUSTOM,
            custom_message="  The office is closed Friday.  ",
        )
        self.assertEqual(compose_banner_message(banner), "The office is closed Friday.")


class SiteBannerAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_banner_is_hidden_by_default(self):
        res = self.client.get("/api/site-banner/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {"enabled": False, "message": ""})
        self.assertIn("no-store", res["Cache-Control"])

    def test_downtime_banner_is_public(self):
        SiteBanner.objects.create(
            enabled=True,
            mode=SiteBanner.MODE_DOWNTIME,
            reason="a power outage",
            starts_at=datetime(2026, 10, 3, 14, 0, tzinfo=datetime_timezone.utc),
            ends_at=datetime(2026, 10, 3, 18, 0, tzinfo=datetime_timezone.utc),
            starts_label="Oct 3, 2026, 2:00 PM",
            ends_label="Oct 3, 2026, 6:00 PM",
        )
        res = self.client.get("/api/site-banner/")
        self.assertEqual(
            res.data["message"],
            "Due to a power outage the service will be down from "
            "Oct 3, 2026, 2:00 PM to Oct 3, 2026, 6:00 PM.",
        )
        self.assertTrue(res.data["enabled"])

    def test_custom_banner_and_toggle_off(self):
        banner = SiteBanner.objects.create(
            enabled=True,
            mode=SiteBanner.MODE_CUSTOM,
            custom_message="We will be back after the retreat.",
        )
        res = self.client.get("/api/site-banner/")
        self.assertEqual(res.data["message"], "We will be back after the retreat.")

        banner.enabled = False
        banner.save()
        hidden = self.client.get("/api/site-banner/")
        self.assertEqual(hidden.data, {"enabled": False, "message": ""})

    def test_terms_page_includes_banner_markup(self):
        SiteBanner.objects.create(
            enabled=True,
            mode=SiteBanner.MODE_CUSTOM,
            custom_message='Down <script>alert("x")</script>',
        )
        res = self.client.get("/subscription-terms/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"background:#FFD100", res.content)
        self.assertIn(b"color:#475569", res.content)
        self.assertIn(b"Down &lt;script&gt;", res.content)
        self.assertNotIn(b"<script>alert", res.content)
        self.assertIn(b"$15 per month", res.content)


@override_settings(STORAGES=_ADMIN_TEST_STORAGES)
class SiteBannerAdminTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="admin@church.org",
            email="admin@church.org",
            password="AdminPass123!",
        )
        self.client = Client()
        self.client.force_login(self.staff)
        self.url = reverse("admin:core_site_banner")

    def test_non_staff_is_redirected(self):
        visitor = Client()
        res = visitor.get(self.url)
        self.assertEqual(res.status_code, 302)

    def test_staff_form_shows_both_message_types(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Show banner on the website")
        self.assertContains(res, "Due to")
        self.assertContains(res, "the service will be down from")
        self.assertContains(res, "Custom message")

    def test_save_downtime_banner_and_turn_it_off(self):
        res = self.client.post(
            self.url,
            {
                "enabled": "on",
                "mode": "downtime",
                "reason": "scheduled maintenance",
                "starts_at": "2026-10-03T14:00:00Z",
                "ends_at": "2026-10-03T18:00:00Z",
                "starts_label": "Oct 3, 2026, 2:00 PM",
                "ends_label": "Oct 3, 2026, 6:00 PM",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Website banner is on.")
        banner = SiteBanner.load()
        self.assertTrue(banner.enabled)
        public = APIClient().get("/api/site-banner/")
        self.assertEqual(
            public.data["message"],
            "Due to scheduled maintenance the service will be down from "
            "Oct 3, 2026, 2:00 PM to Oct 3, 2026, 6:00 PM.",
        )

        off = self.client.post(
            self.url,
            {
                "mode": "downtime",
                "reason": "scheduled maintenance",
                "starts_at": "2026-10-03T14:00:00Z",
                "ends_at": "2026-10-03T18:00:00Z",
                "starts_label": "Oct 3, 2026, 2:00 PM",
                "ends_label": "Oct 3, 2026, 6:00 PM",
            },
            follow=True,
        )
        self.assertContains(off, "Website banner is off.")
        self.assertFalse(SiteBanner.load().enabled)
        hidden = APIClient().get("/api/site-banner/")
        self.assertFalse(hidden.data["enabled"])

    def test_save_custom_message(self):
        res = self.client.post(
            self.url,
            {
                "enabled": "on",
                "mode": "custom",
                "custom_message": "  Chapel is closed today.  ",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        banner = SiteBanner.load()
        self.assertEqual(banner.mode, SiteBanner.MODE_CUSTOM)
        self.assertEqual(banner.custom_message, "Chapel is closed today.")
        public = APIClient().get("/api/site-banner/")
        self.assertEqual(public.data["message"], "Chapel is closed today.")

    def test_enabled_downtime_requires_a_complete_window(self):
        res = self.client.post(
            self.url,
            {
                "enabled": "on",
                "mode": "downtime",
                "reason": "maintenance",
                "starts_at": "2026-10-03T18:00:00Z",
                "ends_at": "2026-10-03T14:00:00Z",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "The end time must be after the start time.")
        self.assertFalse(SiteBanner.load().enabled)

        missing = self.client.post(
            self.url,
            {"enabled": "on", "mode": "custom", "custom_message": "   "},
        )
        self.assertContains(missing, "Fill in the banner message.")
        self.assertFalse(SiteBanner.load().enabled)

    def test_home_page_links_to_the_banner(self):
        from django.conf import settings

        from core.admin import _split_admin_navigation

        request = RequestFactory().get(f"/{settings.ADMIN_URL_PATH}/")
        request.user = self.staff
        _content, pastoral, _advanced = _split_admin_navigation(request)
        names = {model.get("object_name") for model in pastoral}
        self.assertIn("SiteBannerTool", names)

        res = self.client.get(f"/{settings.ADMIN_URL_PATH}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Website banner")
        self.assertContains(res, reverse("admin:core_site_banner"))
