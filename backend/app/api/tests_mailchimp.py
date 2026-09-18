from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from api.mailchimp import (
    MailchimpError,
    collect_exportable_members,
    member_email,
    subscriber_hash,
    upsert_members,
)
from api.models import MailchimpExportRun


def _user(**kwargs):
    defaults = {
        "username": "member@church.org",
        "email": "member@church.org",
        "password": "MemberPass123!",
        "first_name": "Member",
        "last_name": "Nordin",
    }
    defaults.update(kwargs)
    password = defaults.pop("password")
    return User.objects.create_user(password=password, **defaults)


class CollectExportableMembersTests(TestCase):
    def test_includes_active_login_email(self):
        user = _user()
        members = collect_exportable_members()
        self.assertEqual([m.email for m in members], [user.email])
        self.assertEqual(members[0].first_name, "Member")
        self.assertEqual(members[0].last_name, "Nordin")

    def test_skips_inactive_and_admin_localhost(self):
        _user(username="gone@church.org", email="gone@church.org", is_active=False)
        _user(username="admin", email="admin@localhost")
        _user(username="bad", email="not-an-email")
        members = collect_exportable_members()
        self.assertEqual(members, [])

    def test_falls_back_to_username_when_email_blank(self):
        user = User.objects.create_user(
            username="google.user@example.com",
            email="",
            password="MemberPass123!",
            first_name="Google",
        )
        self.assertEqual(member_email(user), "google.user@example.com")
        members = collect_exportable_members()
        self.assertEqual([m.email for m in members], ["google.user@example.com"])

    def test_dedupes_selected_queryset(self):
        first = _user()
        second = _user(username="other@church.org", email="member@church.org")
        members = collect_exportable_members(User.objects.filter(pk__in=[first.pk, second.pk]))
        self.assertEqual([m.email for m in members], ["member@church.org"])


class UpsertMembersTests(TestCase):
    def setUp(self):
        self.member = _user()
        self.members = collect_exportable_members()

    def test_raises_when_not_configured(self):
        with self.assertRaises(MailchimpError):
            upsert_members(self.members)

    @override_settings(MAILCHIMP_API_KEY="abc-us21", MAILCHIMP_AUDIENCE_ID="aud123")
    @patch("api.mailchimp.requests.Session")
    def test_adds_new_member_and_tags(self, session_cls):
        session = session_cls.return_value
        session.get.return_value.status_code = 404
        session.get.return_value.json.return_value = {}
        session.put.return_value.status_code = 200
        session.post.return_value.status_code = 204

        result = upsert_members(self.members)

        self.assertEqual(result.added, 1)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
        email_hash = subscriber_hash(self.member.email)
        session.put.assert_called_once()
        put_url, put_kwargs = session.put.call_args[0][0], session.put.call_args[1]
        self.assertIn(email_hash, put_url)
        self.assertEqual(put_kwargs["json"]["status_if_new"], "subscribed")
        self.assertNotIn("status", put_kwargs["json"])
        self.assertEqual(put_kwargs["json"]["merge_fields"]["FNAME"], "Member")
        session.post.assert_called_once()
        self.assertIn("/tags", session.post.call_args[0][0])
        self.assertEqual(
            session.post.call_args[1]["json"]["tags"][0]["name"],
            "nordin-ai",
        )

    @override_settings(MAILCHIMP_API_KEY="abc-us21", MAILCHIMP_AUDIENCE_ID="aud123")
    @patch("api.mailchimp.requests.Session")
    def test_updates_existing_subscribed_member(self, session_cls):
        session = session_cls.return_value
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"status": "subscribed"}
        session.put.return_value.status_code = 200
        session.post.return_value.status_code = 204

        result = upsert_members(self.members)

        self.assertEqual(result.added, 0)
        self.assertEqual(result.updated, 1)
        session.put.assert_called_once()

    @override_settings(MAILCHIMP_API_KEY="abc-us21", MAILCHIMP_AUDIENCE_ID="aud123")
    @patch("api.mailchimp.requests.Session")
    def test_skips_unsubscribed_without_put(self, session_cls):
        session = session_cls.return_value
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"status": "unsubscribed"}

        result = upsert_members(self.members)

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.added, 0)
        session.put.assert_not_called()
        session.post.assert_not_called()

    @override_settings(MAILCHIMP_API_KEY="abc-us21", MAILCHIMP_AUDIENCE_ID="aud123")
    @patch("api.mailchimp.requests.Session")
    def test_counts_put_failure(self, session_cls):
        session = session_cls.return_value
        session.get.return_value.status_code = 404
        session.put.return_value.status_code = 400
        session.put.return_value.json.return_value = {"detail": "Invalid email"}
        session.put.return_value.text = "Invalid email"

        result = upsert_members(self.members)

        self.assertEqual(result.failed, 1)
        self.assertTrue(result.errors[0].startswith(self.member.email))


_ADMIN_TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@override_settings(
    STORAGES=_ADMIN_TEST_STORAGES,
    MAILCHIMP_API_KEY="abc-us21",
    MAILCHIMP_AUDIENCE_ID="aud123",
)
class MailchimpAdminExportTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="admin@church.org",
            email="admin@church.org",
            password="AdminPass123!",
        )
        self.member = _user()
        self.client = Client()
        self.client.force_login(self.staff)
        self.url = reverse("admin:core_mailchimp_export")

    def test_non_staff_is_redirected(self):
        visitor = Client()
        res = visitor.get(self.url)
        self.assertEqual(res.status_code, 302)

    @patch("api.mailchimp_admin.audience_status")
    def test_staff_get_shows_preview_count(self, mock_status):
        mock_status.return_value.configured = True
        mock_status.return_value.connected = True
        mock_status.return_value.audience_name = "Nordin AI"
        mock_status.return_value.error = ""
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Export members to Mailchimp")
        self.assertContains(res, "2")  # staff + member

    @patch("api.mailchimp_admin.upsert_members")
    @patch("api.mailchimp_admin.dump_persistent_postgres")
    def test_staff_post_records_run_counts(self, _dump, mock_upsert):
        from api.mailchimp import ExportResult

        mock_upsert.return_value = ExportResult(added=1, updated=1, skipped=0, failed=0)
        res = self.client.post(self.url, {}, follow=True)
        self.assertEqual(res.status_code, 200)
        run = MailchimpExportRun.objects.get()
        self.assertEqual(run.added, 1)
        self.assertEqual(run.updated, 1)
        self.assertEqual(run.candidate_count, 2)
        self.assertContains(res, "Added 1")

    @patch("api.mailchimp_admin.upsert_members")
    @patch("api.mailchimp_admin.dump_persistent_postgres")
    def test_users_changelist_action_exports_selection(self, _dump, mock_upsert):
        from api.mailchimp import ExportResult

        mock_upsert.return_value = ExportResult(added=1)
        users_url = f"/{settings.ADMIN_URL_PATH}/auth/user/"
        res = self.client.post(
            users_url,
            {
                "action": "export_selected_to_mailchimp",
                "_selected_action": [str(self.member.pk)],
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        mock_upsert.assert_called_once()
        exported = [m.email for m in mock_upsert.call_args[0][0]]
        self.assertEqual(exported, [self.member.email])
        self.assertEqual(MailchimpExportRun.objects.count(), 1)

    def test_mailchimp_is_in_pastoral_admin_nav(self):
        from core.admin import _split_admin_navigation

        request = RequestFactory().get(f"/{settings.ADMIN_URL_PATH}/")
        request.user = self.staff
        _content, pastoral, _advanced = _split_admin_navigation(request)
        names = {model.get("object_name") for model in pastoral}
        self.assertIn("MailchimpExportTool", names)
        self.assertIn("User", names)

    def test_home_page_has_mailchimp_card(self):
        res = self.client.get(f"/{settings.ADMIN_URL_PATH}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Mailchimp audience")
        self.assertContains(res, reverse("admin:core_mailchimp_export"))
