"""Tests for the Premium-only shared monthly platform token pool."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import PlatformTokenMeter, Profile
from api.token_quota import (
    admin_clear_chat_restriction,
    admin_set_chat_restriction,
    calendar_period_key,
    check_chat_allowed,
    platform_monthly_token_budget,
    platform_usage_snapshot,
    record_token_usage,
    should_enforce_token_limits,
    should_meter_usage,
)


class PlatformTokenQuotaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="test-pass-123",
        )
        self.profile = self.user.profile
        self.profile.subscription_status = Profile.SubscriptionStatus.ACTIVE
        self.profile.email_verified = True
        self.profile.save()

    def test_budget_default(self):
        self.assertEqual(platform_monthly_token_budget(), 34000000)

    def test_only_premium_is_enforced_and_metered(self):
        self.assertTrue(should_enforce_token_limits(self.user))
        self.assertTrue(should_meter_usage(self.user))

        self.profile.subscription_status = Profile.SubscriptionStatus.FREE
        self.profile.save(update_fields=["subscription_status"])
        self.assertFalse(should_enforce_token_limits(self.user))
        self.assertFalse(should_meter_usage(self.user))

    def test_superuser_is_exempt_even_if_premium(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertFalse(should_enforce_token_limits(self.user))
        self.assertFalse(should_meter_usage(self.user))
        gate = check_chat_allowed(self.user)
        self.assertTrue(gate.allowed)
        # Superuser usage does not burn the Premium pool.
        record_token_usage(self.user, 5000)
        used, _budget, _remaining = platform_usage_snapshot()
        self.assertEqual(used, 0)

    def test_record_usage_increments_platform_meter(self):
        record_token_usage(self.user, 1200)
        record_token_usage(self.user, 800)
        used, budget, remaining = platform_usage_snapshot()
        self.assertEqual(used, 2000)
        self.assertEqual(budget, 34000000)
        self.assertEqual(remaining, 34000000 - 2000)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.tokens_spent, 2000)
        meter = PlatformTokenMeter.objects.get(period_key=calendar_period_key())
        self.assertEqual(meter.tokens_used, 2000)

    def test_platform_exhausted_blocks_premium(self):
        PlatformTokenMeter.objects.create(
            period_key=calendar_period_key(),
            tokens_used=platform_monthly_token_budget(),
        )
        gate = check_chat_allowed(self.user)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.code, "platform_token_budget_exhausted")
        self.assertIn("used up your allotted responses", gate.error.lower())
        self.assertGreater(gate.retry_after_seconds, 0)

    def test_admin_user_restriction_still_works(self):
        admin_set_chat_restriction(self.profile, hours=24)
        blocked = check_chat_allowed(self.user)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.code, "token_cooldown")
        admin_clear_chat_restriction(self.profile)
        allowed = check_chat_allowed(self.user)
        self.assertTrue(allowed.allowed)


@override_settings(ROOT_URLCONF="pastor_ai.urls")
class PlatformTokenGateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="gated@example.com",
            email="gated@example.com",
            password="test-pass-123",
        )
        self.profile = self.user.profile
        self.profile.subscription_status = Profile.SubscriptionStatus.ACTIVE
        self.profile.email_verified = True
        self.profile.save()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_chat_rejects_when_platform_pool_empty(self):
        PlatformTokenMeter.objects.create(
            period_key=calendar_period_key(),
            tokens_used=platform_monthly_token_budget(),
        )
        res = self.client.post(
            "/api/chat/",
            {"query": "What is grace?", "session_id": "t1"},
            format="json",
        )
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.data.get("code"), "platform_token_budget_exhausted")
        self.assertIn("used up your allotted responses", res.data.get("error", "").lower())

    def test_superuser_not_gated_when_pool_empty(self):
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save(update_fields=["is_superuser", "is_staff"])
        PlatformTokenMeter.objects.create(
            period_key=calendar_period_key(),
            tokens_used=platform_monthly_token_budget(),
        )
        with mock.patch("core.views.get_chat_llm") as mocked_llm:
            mocked_llm.side_effect = RuntimeError("stop-after-gate")
            res = self.client.post(
                "/api/chat/",
                {"query": "Hello", "session_id": "t2"},
                format="json",
            )
        self.assertEqual(res.status_code, 500)
        self.assertNotEqual(res.data.get("code"), "platform_token_budget_exhausted")
