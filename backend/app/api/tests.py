from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


@override_settings(GOOGLE_CLIENT_ID="test-google-client.apps.googleusercontent.com")
class AuthConfigViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_returns_public_google_client_id(self):
        res = self.client.get("/api/auth/config/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["google_configured"])
        self.assertEqual(res.data["google_client_id"], "test-google-client.apps.googleusercontent.com")

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_returns_empty_when_not_configured(self):
        res = self.client.get("/api/auth/config/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["google_configured"])
        self.assertEqual(res.data["google_client_id"], "")


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


@override_settings(BILLING_MOCK_CHECKOUT="true")
class CancelSubscriptionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/billing/cancel-subscription/"
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
        self.premium.profile.billing_period = "monthly"
        self.premium.profile.save(update_fields=["subscription_status", "billing_period"])
        self.member_token = Token.objects.create(user=self.member).key
        self.premium_token = Token.objects.create(user=self.premium).key

    def test_free_member_cannot_unsubscribe(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_premium_unsubscribe_keeps_access_until_period_end(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, 200)
        user = res.data["user"]
        self.assertTrue(user["is_premium"])
        self.assertEqual(user["subscription_status"], "active")
        self.assertTrue(user["cancel_at_period_end"])
        self.assertIsNotNone(user["current_period_end"])

        self.premium.profile.refresh_from_db()
        self.assertTrue(self.premium.profile.is_premium)
        self.assertTrue(self.premium.profile.cancel_at_period_end)

    def test_premium_access_ends_after_canceled_period(self):
        from datetime import timedelta

        from django.utils import timezone

        profile = self.premium.profile
        profile.subscription_status = "active"
        profile.cancel_at_period_end = True
        profile.current_period_end = timezone.now() - timedelta(minutes=1)
        profile.save()

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["user"]["is_premium"])
        self.assertEqual(res.data["user"]["subscription_status"], "canceled")
        self.assertFalse(res.data["user"]["cancel_at_period_end"])


@override_settings(
    STRIPE_SECRET_KEY="sk_test_x",
    STRIPE_PUBLISHABLE_KEY="pk_test_x",
    BILLING_MOCK_CHECKOUT="false",
)
class CheckoutSessionStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="buyer@church.org",
            email="buyer@church.org",
            password="BuyerPass123!",
        )
        self.token = Token.objects.create(user=self.user).key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    @patch("api.billing_views.stripe.Subscription.retrieve")
    @patch("api.billing_views.stripe.checkout.Session.retrieve")
    def test_complete_session_grants_premium(self, mock_retrieve, mock_sub_retrieve):
        mock_retrieve.return_value = {
            "id": "cs_test_1",
            "status": "complete",
            "payment_status": "paid",
            "client_reference_id": str(self.user.id),
            "customer": "cus_test_1",
            "subscription": "sub_test_1",
            "metadata": {"billing_period": "monthly"},
        }
        mock_sub_retrieve.return_value = {
            "id": "sub_test_1",
            "status": "active",
            "customer": "cus_test_1",
            "cancel_at_period_end": False,
            "current_period_end": 1893456000,
            "items": {"data": [{"price": {"recurring": {"interval": "month"}}}]},
        }

        res = self.client.get("/api/billing/session-status/?session_id=cs_test_1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "complete")
        self.assertTrue(res.data["user"]["is_premium"])
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.subscription_status, "active")
        self.assertEqual(self.user.profile.stripe_subscription_id, "sub_test_1")


@override_settings(
    STRIPE_SECRET_KEY="sk_test_x",
    STRIPE_PUBLISHABLE_KEY="pk_test_x",
    BILLING_MOCK_CHECKOUT="false",
)
class SyncSubscriptionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="sync@church.org",
            email="sync@church.org",
            password="SyncPass123!",
        )
        self.user.profile.stripe_customer_id = "cus_test_sync"
        self.user.profile.save(update_fields=["stripe_customer_id"])
        self.token = Token.objects.create(user=self.user).key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    @patch("api.billing_views.stripe.Subscription.list")
    def test_sync_subscription_restores_premium(self, mock_list):
        mock_list.return_value = {
            "data": [
                {
                    "id": "sub_test_sync",
                    "status": "active",
                    "customer": "cus_test_sync",
                    "cancel_at_period_end": False,
                    "current_period_end": 1893456000,
                    "items": {"data": [{"price": {"recurring": {"interval": "year"}}}]},
                }
            ]
        }

        res = self.client.post("/api/billing/sync-subscription/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["user"]["is_premium"])
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.subscription_status, "active")
        self.assertEqual(self.user.profile.billing_period, "yearly")
