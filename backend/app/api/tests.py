from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import Profile
from core.models import ChurchEvent


@override_settings(GOOGLE_CLIENT_ID="test-google-client.apps.googleusercontent.com")
class AuthConfigViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_returns_public_google_client_id(self):
        res = self.client.get("/api/auth/config/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["google_configured"])
        self.assertEqual(
            res.data["google_client_id"],
            "test-google-client.apps.googleusercontent.com",
        )

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_returns_empty_when_not_configured(self):
        res = self.client.get("/api/auth/config/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["google_configured"])
        self.assertEqual(res.data["google_client_id"], "")


class AuthCsrfSessionTests(TestCase):
    """Flutter web sends the Django session cookie but not X-CSRFToken."""

    def setUp(self):
        self.member = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
            first_name="Member",
        )

    def test_register_with_session_cookie_without_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="member@church.org", password="MemberPass123!"))
        res = client.post(
            "/api/auth/register/",
            {
                "name": "New User",
                "email": "new.user@example.com",
                "password": "BrandNewPass123!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("token", res.data)
        self.assertEqual(res.data["user"]["email"], "new.user@example.com")

    def test_login_with_session_cookie_without_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="member@church.org", password="MemberPass123!"))
        res = client.post(
            "/api/auth/login/",
            {"email": "member@church.org", "password": "MemberPass123!"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("token", res.data)

    @override_settings(GOOGLE_CLIENT_ID="test-google-client.apps.googleusercontent.com")
    @patch("api.auth_views.google_id_token.verify_oauth2_token")
    def test_google_auth_with_session_cookie_without_csrf(self, mock_verify):
        mock_verify.return_value = {
            "email": "google.csrf@example.com",
            "email_verified": True,
            "name": "Google CSRF",
            "picture": "",
        }
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="member@church.org", password="MemberPass123!"))
        res = client.post(
            "/api/auth/google/",
            {"id_token": "fake-id-token"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("token", res.data)


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
        self.premium = User.objects.create_user(
            username="premium@church.org",
            email="premium@church.org",
            password="PremiumPass123!",
        )
        self.premium.profile.subscription_status = "active"
        self.premium.profile.save(update_fields=["subscription_status"])
        self.premium_token = Token.objects.create(user=self.premium).key
        self._prayer_payload = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-0100",
            "prayer_text": "Please pray for my family during this season.",
            "is_anonymous": False,
        }

    def test_anonymous_cannot_submit_prayer_request(self):
        res = self.client.post(self.list_url, self._prayer_payload, format="json")
        self.assertIn(res.status_code, (401, 403))

    def test_free_member_cannot_submit_prayer_request(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.post(self.list_url, self._prayer_payload, format="json")
        self.assertEqual(res.status_code, 403)

    def test_premium_can_submit_prayer_request(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.post(self.list_url, self._prayer_payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["success"])

    def test_staff_can_list_prayer_requests(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
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
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
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


class ProductPaywallTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.member = User.objects.create_user(
            username="free@church.org",
            email="free@church.org",
            password="MemberPass123!",
        )
        self.premium = User.objects.create_user(
            username="premium@church.org",
            email="premium@church.org",
            password="PremiumPass123!",
        )
        self.premium.profile.subscription_status = "active"
        self.premium.profile.save(update_fields=["subscription_status"])
        self.staff = User.objects.create_user(
            username="staff@church.org",
            email="staff@church.org",
            password="StaffPass123!",
            is_staff=True,
        )
        self.member_token = Token.objects.create(user=self.member).key
        self.premium_token = Token.objects.create(user=self.premium).key
        self.staff_token = Token.objects.create(user=self.staff).key
        self.event = ChurchEvent.objects.create(
            title="Sunday gathering",
            location="Main campus",
            host_name="Pastor Don",
            starts_at=timezone.now(),
            is_published=True,
        )

    def _assert_locked(self, method, path, **kwargs):
        anon = getattr(self.client, method)(path, **kwargs)
        self.assertIn(anon.status_code, (401, 403), path)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        free = getattr(self.client, method)(path, **kwargs)
        self.assertEqual(free.status_code, 403, path)
        self.client.credentials()

    def test_anonymous_and_free_are_locked_out_of_product_apis(self):
        self._assert_locked("get", "/api/church-events/")
        self._assert_locked("get", f"/api/church-events/{self.event.pk}/")
        self._assert_locked("get", "/api/media/")
        self._assert_locked("get", "/api/ingested-documents/")
        self._assert_locked("post", "/api/chat/", data={"query": "Hope in Scripture?"}, format="json")
        self._assert_locked("post", "/api/chat/warmup/", data={}, format="json")
        self._assert_locked(
            "post",
            "/api/translate/",
            data={"texts": ["Hello"], "language": "es"},
            format="json",
        )

    def test_premium_can_read_events_and_media(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        events = self.client.get("/api/church-events/")
        self.assertEqual(events.status_code, 200)
        self.assertEqual(len(events.data["results"]), 1)
        media = self.client.get("/api/media/")
        self.assertEqual(media.status_code, 200)
        docs = self.client.get("/api/ingested-documents/")
        self.assertEqual(docs.status_code, 200)

    def test_staff_can_read_events_without_paying(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token}")
        res = self.client.get("/api/church-events/")
        self.assertEqual(res.status_code, 200)


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


@override_settings(BILLING_MOCK_CHECKOUT="true")
class ChangePlanTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/billing/change-plan/"
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
        from django.utils import timezone

        self.period_end = timezone.now() + timedelta(days=20)
        profile = self.premium.profile
        profile.subscription_status = "active"
        profile.billing_period = "monthly"
        profile.current_period_end = self.period_end
        profile.save(
            update_fields=[
                "subscription_status",
                "billing_period",
                "current_period_end",
            ]
        )
        self.member_token = Token.objects.create(user=self.member).key
        self.premium_token = Token.objects.create(user=self.premium).key

    def test_free_member_cannot_change_plan(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_requires_billing_period(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_monthly_premium_can_schedule_yearly(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        self.assertEqual(res.status_code, 200)
        user = res.data["user"]
        self.assertTrue(user["is_premium"])
        self.assertEqual(user["billing_period"], "monthly")
        self.assertEqual(user["pending_billing_period"], "yearly")
        self.assertFalse(user["cancel_at_period_end"])
        self.assertIsNotNone(user["current_period_end"])

        self.premium.profile.refresh_from_db()
        self.assertEqual(self.premium.profile.billing_period, "monthly")
        self.assertEqual(self.premium.profile.pending_billing_period, "yearly")
        self.assertEqual(self.premium.profile.current_period_end, self.period_end)

    def test_already_on_plan_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        res = self.client.post(self.url, {"billing_period": "monthly"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_scheduling_the_same_pending_plan_is_idempotent(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        first = self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        self.assertEqual(first.status_code, 200)
        second = self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["user"]["pending_billing_period"], "yearly")

    def test_can_revert_pending_yearly_switch(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        res = self.client.post(self.url, {"billing_period": "monthly"}, format="json")
        self.assertEqual(res.status_code, 200)
        user = res.data["user"]
        self.assertEqual(user["billing_period"], "monthly")
        self.assertEqual(user["pending_billing_period"], "")

    def test_unsubscribe_clears_pending_plan_change(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        res = self.client.post("/api/billing/cancel-subscription/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["user"]["cancel_at_period_end"])
        self.assertEqual(res.data["user"]["pending_billing_period"], "")

    def test_yearly_price_applies_after_current_period(self):
        from django.utils import timezone

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        self.client.post(self.url, {"billing_period": "yearly"}, format="json")

        profile = self.premium.profile
        profile.refresh_from_db()
        profile.current_period_end = timezone.now() - timedelta(minutes=1)
        profile.save(update_fields=["current_period_end"])

        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        user = res.data["user"]
        self.assertTrue(user["is_premium"])
        self.assertEqual(user["billing_period"], "yearly")
        self.assertEqual(user["pending_billing_period"], "")
        self.assertIsNotNone(user["current_period_end"])
        self.premium.profile.refresh_from_db()
        self.assertGreater(
            self.premium.profile.current_period_end, timezone.now()
        )

    def test_changing_plan_resumes_a_scheduled_cancel(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.premium_token}")
        self.client.post("/api/billing/cancel-subscription/", {}, format="json")
        res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")
        self.assertEqual(res.status_code, 200)
        user = res.data["user"]
        self.assertFalse(user["cancel_at_period_end"])
        self.assertEqual(user["pending_billing_period"], "yearly")
        self.assertEqual(user["billing_period"], "monthly")


@override_settings(
    BILLING_MOCK_CHECKOUT="false",
    STRIPE_SECRET_KEY="sk_test_change_plan",
    STRIPE_PUBLISHABLE_KEY="pk_test_change_plan",
    STRIPE_PRICE_MONTHLY="price_month",
    STRIPE_PRICE_YEARLY="price_year",
)
class ChangePlanStripeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/billing/change-plan/"
        self.premium = User.objects.create_user(
            username="stripe@church.org",
            email="stripe@church.org",
            password="PremiumPass123!",
            first_name="Stripe",
            last_name="Member",
        )
        from django.utils import timezone

        profile = self.premium.profile
        profile.subscription_status = "active"
        profile.billing_period = "monthly"
        profile.stripe_customer_id = "cus_test"
        profile.stripe_subscription_id = "sub_test"
        profile.current_period_end = timezone.now() + timedelta(days=12)
        profile.save()
        self.token = Token.objects.create(user=self.premium).key

    def _subscription(self, *, schedule=None, cancel_at_period_end=False):
        import time

        period_end = int(time.time()) + 86400 * 12
        start = int(time.time()) - 86400 * 18
        return {
            "id": "sub_test",
            "status": "active",
            "cancel_at_period_end": cancel_at_period_end,
            "current_period_end": period_end,
            "start_date": start,
            "schedule": schedule,
            "customer": "cus_test",
            "items": {
                "data": [
                    {
                        "id": "si_1",
                        "quantity": 1,
                        "price": {
                            "id": "price_month",
                            "recurring": {"interval": "month"},
                        },
                    }
                ]
            },
        }

    def test_monthly_to_yearly_creates_stripe_schedule(self):
        from unittest.mock import patch

        subscription = self._subscription()
        schedule = {
            "id": "sub_sched_1",
            "phases": [
                {
                    "start_date": subscription["start_date"],
                    "items": [{"price": "price_month", "quantity": 1}],
                }
            ],
        }
        with (
            patch("api.billing_views.stripe.Subscription.retrieve", return_value=subscription),
            patch(
                "api.billing_views.stripe.SubscriptionSchedule.create",
                return_value=schedule,
            ) as create_sched,
            patch("api.billing_views.stripe.SubscriptionSchedule.modify") as modify_sched,
            patch("api.billing_views.stripe.Subscription.modify"),
        ):
            self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
            res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")

        self.assertEqual(res.status_code, 200)
        create_sched.assert_called_once_with(from_subscription="sub_test")
        modify_sched.assert_called_once()
        kwargs = modify_sched.call_args.kwargs
        self.assertEqual(kwargs["end_behavior"], "release")
        self.assertEqual(kwargs["proration_behavior"], "none")
        self.assertEqual(len(kwargs["phases"]), 2)
        self.assertEqual(kwargs["phases"][0]["end_date"], subscription["current_period_end"])
        self.assertEqual(kwargs["phases"][1]["items"][0]["price"], "price_year")
        self.assertEqual(res.data["user"]["billing_period"], "monthly")
        self.assertEqual(res.data["user"]["pending_billing_period"], "yearly")

    def test_reverting_pending_change_releases_stripe_schedule(self):
        from unittest.mock import patch

        profile = self.premium.profile
        profile.pending_billing_period = "yearly"
        profile.save(update_fields=["pending_billing_period"])
        subscription = self._subscription(schedule="sub_sched_1")
        with (
            patch("api.billing_views.stripe.Subscription.retrieve", return_value=subscription),
            patch("api.billing_views.stripe.SubscriptionSchedule.release") as release,
        ):
            self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
            res = self.client.post(self.url, {"billing_period": "monthly"}, format="json")

        self.assertEqual(res.status_code, 200)
        release.assert_called_once_with("sub_sched_1")
        self.assertEqual(res.data["user"]["pending_billing_period"], "")
        self.assertEqual(res.data["user"]["billing_period"], "monthly")

    def test_stripe_invalid_request_returns_400_json_not_502(self):
        import stripe

        subscription = self._subscription()
        schedule = {
            "id": "sub_sched_1",
            "phases": [
                {
                    "start_date": subscription["start_date"],
                    "items": [{"price": "price_month", "quantity": 1}],
                }
            ],
        }
        error = stripe.error.InvalidRequestError(
            "Received unknown parameter: phases[1][items][0][price_data]",
            "phases",
        )
        with (
            patch("api.billing_views.stripe.Subscription.retrieve", return_value=subscription),
            patch(
                "api.billing_views.stripe.SubscriptionSchedule.create",
                return_value=schedule,
            ),
            patch(
                "api.billing_views.stripe.SubscriptionSchedule.modify",
                side_effect=error,
            ),
            patch("api.billing_views.stripe.SubscriptionSchedule.release") as release,
        ):
            self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
            res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")

        self.assertEqual(res.status_code, 400)
        self.assertIn("detail", res.data)
        self.assertIn("price_data", str(res.data["detail"]))
        self.assertNotEqual(res.status_code, 502)
        self.premium.profile.refresh_from_db()
        self.assertEqual(self.premium.profile.pending_billing_period, "")
        release.assert_called_once_with("sub_sched_1")


@override_settings(
    BILLING_MOCK_CHECKOUT="false",
    STRIPE_SECRET_KEY="sk_test_change_plan",
    STRIPE_PUBLISHABLE_KEY="pk_test_change_plan",
    STRIPE_PRICE_MONTHLY="",
    STRIPE_PRICE_YEARLY="",
)
class ChangePlanCreatesCatalogPriceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/billing/change-plan/"
        self.premium = User.objects.create_user(
            username="inline@church.org",
            email="inline@church.org",
            password="PremiumPass123!",
            first_name="Inline",
            last_name="Member",
        )
        profile = self.premium.profile
        profile.subscription_status = "active"
        profile.billing_period = "monthly"
        profile.stripe_customer_id = "cus_test"
        profile.stripe_subscription_id = "sub_test"
        profile.current_period_end = timezone.now() + timedelta(days=12)
        profile.save()
        self.token = Token.objects.create(user=self.premium).key

    def test_yearly_schedule_uses_catalog_price_id_not_price_data(self):
        import time

        period_end = int(time.time()) + 86400 * 12
        start = int(time.time()) - 86400 * 18
        subscription = {
            "id": "sub_test",
            "status": "active",
            "cancel_at_period_end": False,
            "current_period_end": period_end,
            "start_date": start,
            "schedule": None,
            "customer": "cus_test",
            "items": {
                "data": [
                    {
                        "id": "si_1",
                        "quantity": 1,
                        "price": {
                            "id": "price_adhoc_month",
                            "recurring": {"interval": "month"},
                        },
                    }
                ]
            },
        }
        schedule = {
            "id": "sub_sched_1",
            "phases": [
                {
                    "start_date": start,
                    "items": [{"price": "price_adhoc_month", "quantity": 1}],
                }
            ],
        }
        with (
            patch("api.billing_views.stripe.Subscription.retrieve", return_value=subscription),
            patch(
                "api.billing_views.stripe.Price.list",
                return_value={"data": []},
            ) as price_list,
            patch(
                "api.billing_views.stripe.Product.create",
                return_value={"id": "prod_year"},
            ),
            patch(
                "api.billing_views.stripe.Price.create",
                return_value={"id": "price_created_year"},
            ) as price_create,
            patch(
                "api.billing_views.stripe.SubscriptionSchedule.create",
                return_value=schedule,
            ),
            patch("api.billing_views.stripe.SubscriptionSchedule.modify") as modify_sched,
            patch("api.billing_views.stripe.Subscription.modify"),
        ):
            self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
            res = self.client.post(self.url, {"billing_period": "yearly"}, format="json")

        self.assertEqual(res.status_code, 200, res.data)
        price_list.assert_called()
        self.assertEqual(price_create.call_args.kwargs["lookup_key"], "pastor_ai_premium_yearly")
        kwargs = modify_sched.call_args.kwargs
        new_item = kwargs["phases"][1]["items"][0]
        self.assertEqual(new_item["price"], "price_created_year")
        self.assertNotIn("price_data", new_item)
        self.assertEqual(kwargs["phases"][0]["items"][0]["price"], "price_adhoc_month")
        self.assertEqual(res.data["user"]["billing_period"], "monthly")
        self.assertEqual(res.data["user"]["pending_billing_period"], "yearly")


_ADMIN_TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@override_settings(
    BILLING_MOCK_CHECKOUT="true",
    STORAGES=_ADMIN_TEST_STORAGES,
)
class PaidAccountAdminPersistenceTests(TestCase):
    """Signup + pay must land on the admin Users list with an Active subscription."""

    def setUp(self):
        self.api = APIClient()

    def test_register_then_pay_persists_profile_and_admin_users_list(self):
        register = self.api.post(
            "/api/auth/register/",
            {
                "name": "Paid Member",
                "email": "paid.member@example.com",
                "password": "BrandNewPass123!",
            },
            format="json",
        )
        self.assertEqual(register.status_code, 201, register.data)
        token = register.data["token"]
        user_id = register.data["user"]["id"]

        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        pay = self.api.post(
            "/api/billing/mock-activate/",
            {"billing_period": "yearly"},
            format="json",
        )
        self.assertEqual(pay.status_code, 200, pay.data)
        self.assertTrue(pay.data["user"]["is_premium"])
        self.assertEqual(pay.data["user"]["subscription_status"], "active")
        self.assertEqual(pay.data["user"]["billing_period"], "yearly")

        user = User.objects.select_related("profile").get(pk=user_id)
        user.profile.refresh_from_db()
        self.assertEqual(user.email, "paid.member@example.com")
        self.assertEqual(user.profile.subscription_status, "active")
        self.assertEqual(user.profile.billing_period, "yearly")
        self.assertTrue(user.profile.is_premium)

        staff = User.objects.create_superuser(
            username="admin@church.org",
            email="admin@church.org",
            password="AdminPass123!",
        )
        admin_client = Client()
        admin_client.force_login(staff)
        users_page = admin_client.get(f"/{settings.ADMIN_URL_PATH}/auth/user/")
        self.assertEqual(users_page.status_code, 200)
        self.assertContains(users_page, "paid.member@example.com")
        self.assertContains(users_page, "Active")
        self.assertContains(users_page, "Yearly")

        change_page = admin_client.get(
            f"/{settings.ADMIN_URL_PATH}/auth/user/{user_id}/change/"
        )
        self.assertEqual(change_page.status_code, 200)
        self.assertContains(change_page, "Subscription status")
        self.assertContains(change_page, 'value="active"', html=False)

        profiles_page = admin_client.get(f"/{settings.ADMIN_URL_PATH}/api/profile/")
        self.assertEqual(profiles_page.status_code, 200)
        self.assertContains(profiles_page, "paid.member@example.com")

    def test_mock_activate_with_admin_session_cookie_without_csrf(self):
        staff = User.objects.create_user(
            username="staff@church.org",
            email="staff@church.org",
            password="StaffPass123!",
            is_staff=True,
        )
        member = User.objects.create_user(
            username="buyer@church.org",
            email="buyer@church.org",
            password="MemberPass123!",
        )
        token = Token.objects.create(user=member).key
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="staff@church.org", password="StaffPass123!"))
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        res = client.post(
            "/api/billing/mock-activate/",
            {"billing_period": "monthly"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        member.profile.refresh_from_db()
        self.assertEqual(member.profile.subscription_status, "active")
        self.assertNotEqual(res.data["user"]["email"], staff.email)

    def test_users_and_profiles_are_in_pastoral_admin_nav(self):
        from core.admin import _split_admin_navigation

        staff = User.objects.create_superuser(
            username="nav-admin@church.org",
            email="nav-admin@church.org",
            password="AdminPass123!",
        )
        request = RequestFactory().get(f"/{settings.ADMIN_URL_PATH}/")
        request.user = staff
        _content, pastoral, _advanced = _split_admin_navigation(request)
        names = {model.get("object_name") for model in pastoral}
        self.assertIn("User", names)
        self.assertIn("Profile", names)


@override_settings(STORAGES=_ADMIN_TEST_STORAGES)
class AdminAddUserProfileTests(TestCase):
    """Admin Users → Add must not INSERT a second Profile for the new user."""

    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="admin@church.org",
            email="admin@church.org",
            password="AdminPass123!",
        )
        self.client = Client()
        self.client.force_login(self.staff)
        self.add_url = f"/{settings.ADMIN_URL_PATH}/auth/user/add/"

    def test_add_user_creates_exactly_one_profile(self):
        response = self.client.post(
            self.add_url,
            {
                "username": "grokbot1@gmail.com",
                "password1": "GrokBotPass123!",
                "password2": "GrokBotPass123!",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302, response.content[:2000])
        user = User.objects.get(username="grokbot1@gmail.com")
        self.assertEqual(user.email, "grokbot1@gmail.com")
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)

    def test_add_user_posted_profile_inline_does_not_duplicate(self):
        response = self.client.post(
            self.add_url,
            {
                "username": "grokbot2@gmail.com",
                "password1": "GrokBotPass123!",
                "password2": "GrokBotPass123!",
                "profile-TOTAL_FORMS": "1",
                "profile-INITIAL_FORMS": "0",
                "profile-MIN_NUM_FORMS": "0",
                "profile-MAX_NUM_FORMS": "1",
                "profile-0-subscription_status": "active",
                "profile-0-billing_period": "monthly",
                "profile-0-pending_billing_period": "",
                "profile-0-avatar_url": "",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302, response.content[:2000])
        user = User.objects.get(username="grokbot2@gmail.com")
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)
