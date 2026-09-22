"""Tests for Premium chat token budgets, daily pacing, and secret rollover."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import Profile
from api.token_quota import (
    admin_adjust_tokens,
    check_chat_allowed,
    daily_token_budget,
    ensure_monthly_grant,
    monthly_token_limit,
    period_key_for,
    record_token_usage,
    should_enforce_token_limits,
)


class TokenQuotaHelpersTests(TestCase):
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

    def test_monthly_defaults(self):
        self.assertEqual(monthly_token_limit(), 100000)
        self.assertEqual(daily_token_budget(), 100000 // 30)

    def test_superuser_is_exempt(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertFalse(should_enforce_token_limits(self.user))
        gate = check_chat_allowed(self.user)
        self.assertTrue(gate.allowed)

    def test_non_premium_not_enforced(self):
        self.profile.subscription_status = Profile.SubscriptionStatus.FREE
        self.profile.save(update_fields=["subscription_status"])
        self.assertFalse(should_enforce_token_limits(self.user))

    def test_monthly_grant_and_secret_rollover(self):
        self.assertTrue(ensure_monthly_grant(self.profile))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 100000)
        self.assertEqual(self.profile.token_period_key, period_key_for())

        # Spend some, then pretend a new month arrives — unused balance rolls over.
        self.profile.token_balance = 40000
        self.profile.token_period_key = "2020-01"
        self.profile.save(update_fields=["token_balance", "token_period_key"])
        self.assertTrue(ensure_monthly_grant(self.profile))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 140000)
        self.assertEqual(self.profile.token_period_key, period_key_for())

        # Same month again does not double-grant.
        self.assertFalse(ensure_monthly_grant(self.profile))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 140000)

    def test_daily_limit_starts_cooldown(self):
        ensure_monthly_grant(self.profile)
        daily = daily_token_budget()
        gate = record_token_usage(self.user, daily)
        self.assertIsNotNone(gate)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.code, "token_daily_limit")
        self.assertIn("run out of responses", gate.error.lower())
        self.assertGreater(gate.retry_after_seconds, 0)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.tokens_spent, daily)
        self.assertEqual(self.profile.token_balance, 100000 - daily)
        self.assertIsNotNone(self.profile.token_cooldown_until)

        blocked = check_chat_allowed(self.user)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.code, "token_cooldown")

    def test_admin_adjust_tokens(self):
        ensure_monthly_grant(self.profile)
        admin_adjust_tokens(self.profile, 5000)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 105000)
        admin_adjust_tokens(self.profile, -2000)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 103000)
        admin_adjust_tokens(self.profile, -999999)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.token_balance, 0)

    def test_balance_exhausted_message(self):
        ensure_monthly_grant(self.profile)
        self.profile.token_balance = 0
        self.profile.save(update_fields=["token_balance"])
        gate = check_chat_allowed(self.user)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.code, "token_balance_exhausted")


@override_settings(ROOT_URLCONF="pastor_ai.urls")
class ChatTokenGateAPITests(TestCase):
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

    def test_chat_rejects_during_cooldown(self):
        ensure_monthly_grant(self.profile)
        self.profile.token_cooldown_until = timezone.now() + timedelta(days=2)
        self.profile.save(update_fields=["token_cooldown_until"])

        res = self.client.post(
            "/api/chat/",
            {"query": "What is grace?", "session_id": "t1"},
            format="json",
        )
        self.assertEqual(res.status_code, 429)
        self.assertIn("run out of responses", res.data.get("error", "").lower())
        self.assertEqual(res.data.get("code"), "token_cooldown")

    def test_superuser_chat_not_gated(self):
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save(update_fields=["is_superuser", "is_staff"])
        self.profile.token_cooldown_until = timezone.now() + timedelta(days=2)
        self.profile.token_balance = 0
        self.profile.save(update_fields=["token_cooldown_until", "token_balance"])

        # Gate must not fire; the request may still fail later if vLLM is down.
        # Patch the heavy RAG path so we only assert the token gate is skipped.
        with mock.patch("core.views.get_chat_llm") as mocked_llm:
            mocked_llm.side_effect = RuntimeError("stop-after-gate")
            res = self.client.post(
                "/api/chat/",
                {"query": "Hello", "session_id": "t2"},
                format="json",
            )
        # Superuser passed the quota gate; failure is the mocked RAG error (500).
        self.assertEqual(res.status_code, 500)
        self.assertNotEqual(res.data.get("code"), "token_cooldown")
