import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import PasswordResetCode


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
            first_name="Member",
        )
        self.user.profile.email_verified = False
        self.user.profile.save(update_fields=["email_verified"])
        self.old_token = Token.objects.create(user=self.user)

    def _request(self, email="member@church.org"):
        return self.client.post(
            "/api/auth/forgot-password/",
            {"email": email},
            format="json",
        )

    def _reset(self, code, password="BrandNewPass123!", email="member@church.org"):
        return self.client.post(
            "/api/auth/reset-password/",
            {"email": email, "code": code, "new_password": password},
            format="json",
        )

    def _code_from_inbox(self):
        self.assertGreaterEqual(len(mail.outbox), 1)
        match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_unknown_email_does_not_send_or_reveal_the_account(self):
        res = self._request("nobody@church.org")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["detail"], self._request("member@church.org").data["detail"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("code", res.data)

    def test_password_account_receives_a_code_and_can_sign_in_with_the_new_password(self):
        res = self._request()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertNotIn("code", res.data)
        self.assertIn("reset your nordin's ai password", mail.outbox[-1].body.lower())
        code = self._code_from_inbox()

        reset = self._reset(code)
        self.assertEqual(reset.status_code, 200, reset.data)

        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass123!"))
        self.assertFalse(self.user.check_password("MemberPass123!"))
        self.assertTrue(self.user.profile.email_verified)
        self.assertFalse(Token.objects.filter(key=self.old_token.key).exists())

        old_login = self.client.post(
            "/api/auth/login/",
            {"email": "member@church.org", "password": "MemberPass123!"},
            format="json",
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/api/auth/login/",
            {"email": "member@church.org", "password": "BrandNewPass123!"},
            format="json",
        )
        self.assertEqual(new_login.status_code, 200, new_login.data)

    def test_wrong_code_does_not_change_the_password(self):
        self._request()
        res = self._reset("000000")
        self.assertEqual(res.status_code, 400, res.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("MemberPass123!"))

    def test_expired_code_is_rejected(self):
        self._request()
        code = self._code_from_inbox()
        PasswordResetCode.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        res = self._reset(code)
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("expired", res.data["detail"].lower())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("MemberPass123!"))

    def test_too_many_wrong_attempts_burn_the_code(self):
        self._request()
        code = self._code_from_inbox()
        for _ in range(4):
            res = self._reset("111111")
            self.assertIn("incorrect", res.data["detail"].lower())
        locked = self._reset("111111")
        self.assertIn("too many", locked.data["detail"].lower())
        res = self._reset(code)
        self.assertEqual(res.status_code, 400, res.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("MemberPass123!"))

    def test_google_only_account_is_told_to_use_google(self):
        google_user = User.objects.create_user(
            username="google@church.org",
            email="google@church.org",
        )
        google_user.set_unusable_password()
        google_user.save(update_fields=["password"])

        res = self._request("google@church.org")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("Sign in with Google", mail.outbox[-1].body)
        self.assertIsNone(re.search(r"\b\d{6}\b", mail.outbox[-1].body))
        reset = self._reset("123456", email="google@church.org")
        self.assertEqual(reset.status_code, 400, reset.data)
        google_user.refresh_from_db()
        self.assertFalse(google_user.has_usable_password())

    def test_second_request_is_rate_limited(self):
        first = self._request()
        self.assertEqual(first.status_code, 200, first.data)
        second = self._request()
        self.assertEqual(second.status_code, 429, second.data)
        self.assertIn("wait", second.data["detail"].lower())

    def test_weak_password_is_rejected(self):
        self._request()
        code = self._code_from_inbox()
        res = self._reset(code, password="password")
        self.assertEqual(res.status_code, 400, res.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("MemberPass123!"))

    def test_missing_mail_config_does_not_pretend_the_code_was_sent(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
            EMAIL_HOST="",
            GMAIL_SERVICE_ACCOUNT_JSON="",
            GMAIL_SERVICE_ACCOUNT_FILE="",
        ):
            with patch("api.password_reset.gmail_is_configured", return_value=False):
                res = self._request()
        self.assertEqual(res.status_code, 503, res.data)
        self.assertEqual(PasswordResetCode.objects.filter(user=self.user).count(), 0)

    def test_inactive_user_is_treated_as_unknown(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        res = self._request()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(mail.outbox), 0)
