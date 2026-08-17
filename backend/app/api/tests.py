from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


@override_settings(GOOGLE_CLIENT_ID="test-google-client.apps.googleusercontent.com")
class GoogleAuthViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/auth/google/"

    @patch("api.auth_views.google_id_token.verify_oauth2_token")
    def test_google_sign_in_creates_user_and_returns_token(self, mock_verify):
        mock_verify.return_value = {
            "email": "google.user@example.com",
            "email_verified": True,
            "name": "Google User",
            "picture": "https://example.com/avatar.png",
        }

        res = self.client.post(self.url, {"id_token": "fake-id-token"}, format="json")

        self.assertEqual(res.status_code, 201)
        self.assertIn("token", res.data)
        self.assertEqual(res.data["user"]["email"], "google.user@example.com")
        self.assertEqual(res.data["user"]["name"], "Google User")
        self.assertEqual(res.data["user"]["avatar_url"], "https://example.com/avatar.png")

        user = User.objects.get(username="google.user@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(Token.objects.filter(user=user, key=res.data["token"]).exists())
        mock_verify.assert_called_once()

    @patch("api.auth_views.google_id_token.verify_oauth2_token")
    def test_google_sign_in_logs_in_existing_user(self, mock_verify):
        user = User.objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="ExistingPass123",
            first_name="Existing",
        )
        mock_verify.return_value = {
            "email": "existing@example.com",
            "email_verified": True,
            "name": "Existing",
            "picture": "https://example.com/a.png",
        }

        res = self.client.post(self.url, {"id_token": "fake-id-token"}, format="json")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["user"]["email"], "existing@example.com")
        self.assertEqual(User.objects.filter(username="existing@example.com").count(), 1)
        self.assertTrue(user.has_usable_password())

    @patch("api.auth_views.google_id_token.verify_oauth2_token", side_effect=ValueError("bad token"))
    def test_invalid_id_token_returns_401(self, _mock_verify):
        res = self.client.post(self.url, {"id_token": "bad"}, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertIn("detail", res.data)

    def test_missing_id_token_returns_400(self):
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, 400)

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_unconfigured_server_returns_503(self):
        res = self.client.post(self.url, {"id_token": "x"}, format="json")
        self.assertEqual(res.status_code, 503)


class PrayerRequestAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = "/api/prayer-requests/"
        self.staff = User.objects.create_user(
            username="pastor@church.org",
            email="pastor@church.org",
            password="StaffPass123!",
            is_staff=True,
        )
        self.staff_token = Token.objects.create(user=self.staff).key
        self.member = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        self.member_token = Token.objects.create(user=self.member).key

    def test_public_can_submit_prayer_request(self):
        res = self.client.post(
            self.list_url,
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-0100",
                "prayer_text": "Please pray for my family during this season.",
                "is_anonymous": False,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["success"])

    def test_staff_can_list_prayer_requests(self):
        self.client.post(
            self.list_url,
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "prayer_text": "Please pray for healing and peace.",
                "is_anonymous": False,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token}")
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertIn("followed_up", res.data["results"][0])

    def test_non_staff_cannot_list_prayer_requests(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, 403)

    def test_staff_can_patch_follow_up_fields(self):
        create = self.client.post(
            self.list_url,
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "prayer_text": "Please pray for wisdom in a hard decision.",
                "is_anonymous": False,
            },
            format="json",
        )
        prayer_id = create.data["id"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token}")
        res = self.client.patch(
            f"{self.list_url}{prayer_id}/",
            {"followed_up": True, "pastor_notes": "Called and prayed together."},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["followed_up"])
        self.assertEqual(res.data["pastor_notes"], "Called and prayed together.")


class PremiumAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = User.objects.create_user(
            username="staff@church.org",
            email="staff@church.org",
            password="StaffPass123!",
            is_staff=True,
            first_name="Staff",
            last_name="Member",
        )
        self.member = User.objects.create_user(
            username="free@church.org",
            email="free@church.org",
            password="MemberPass123!",
            first_name="Free",
            last_name="Member",
        )
        self.premium = User.objects.create_user(
            username="premium@church.org",
            email="premium@church.org",
            password="PremiumPass123!",
            first_name="Paid",
            last_name="Member",
        )
        self.premium.profile.subscription_status = "active"
        self.premium.profile.save(update_fields=["subscription_status"])
        self.staff_token = Token.objects.create(user=self.staff).key
        self.member_token = Token.objects.create(user=self.member).key
        self.premium_token = Token.objects.create(user=self.premium).key

    def _me(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return self.client.get("/api/auth/me/")

    def test_free_member_is_not_premium(self):
        res = self._me(self.member_token)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["user"]["is_staff"])
        self.assertFalse(res.data["user"]["is_premium"])
        self.assertFalse(self.member.profile.has_premium_access)

    def test_paid_member_is_premium(self):
        res = self._me(self.premium_token)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["user"]["is_staff"])
        self.assertTrue(res.data["user"]["is_premium"])
        self.assertTrue(self.premium.profile.has_premium_access)

    def test_staff_has_premium_access_without_subscription(self):
        self.assertEqual(self.staff.profile.subscription_status, "free")
        self.assertFalse(self.staff.profile.is_premium)
        self.assertTrue(self.staff.profile.has_premium_access)
        res = self._me(self.staff_token)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["user"]["is_staff"])
        self.assertTrue(res.data["user"]["is_premium"])
