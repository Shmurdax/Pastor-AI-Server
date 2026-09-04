from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import ChatMessage, ResponseReport


class ResponseReportAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/response-reports/"
        self.member = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        self.member_token = Token.objects.create(user=self.member).key
        self.staff = User.objects.create_user(
            username="pastor@church.org",
            email="pastor@church.org",
            password="StaffPass123!",
            is_staff=True,
        )
        self.staff_token = Token.objects.create(user=self.staff).key
        self.message = ChatMessage.objects.create(
            session_id="s:report-test",
            user=self.member,
            user_query="What is grace?",
            ai_response="Grace is God's unearned favor.",
        )

    def _payload(self, **overrides):
        data = {
            "message_id": self.message.id,
            "reason": "inaccurate",
            "details": "This did not match the sermon.",
            "session_id": "browser-session",
        }
        data.update(overrides)
        return data

    def test_public_can_submit_report(self):
        res = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["success"])
        report = ResponseReport.objects.get(pk=res.data["id"])
        self.assertIsNone(report.user)
        self.assertEqual(report.reason, ResponseReport.Reason.INACCURATE)
        self.assertEqual(report.user_query_snapshot, "What is grace?")

    def test_token_submit_attaches_user(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.post(self.url, self._payload(reason="confusing"), format="json")
        self.assertEqual(res.status_code, 201)
        report = ResponseReport.objects.get(pk=res.data["id"])
        self.assertEqual(report.user, self.member)

    def test_session_cookie_without_csrf_can_still_submit(self):
        """Flutter web sends the Django session cookie but not X-CSRFToken."""
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="member@church.org", password="MemberPass123!"))
        res = client.post(self.url, self._payload(reason="other"), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["success"])

    def test_duplicate_open_report_returns_already_reported(self):
        first = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(first.status_code, 201)
        second = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["already_reported"])
        self.assertEqual(second.data["id"], first.data["id"])

    def test_unknown_message_returns_404(self):
        res = self.client.post(self.url, self._payload(message_id=999999), format="json")
        self.assertEqual(res.status_code, 404)

    def test_invalid_reason_returns_400(self):
        res = self.client.post(self.url, self._payload(reason="not-a-reason"), format="json")
        self.assertEqual(res.status_code, 400)

    def test_staff_can_list_reports(self):
        self.client.post(self.url, self._payload(), format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.staff_token}")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["reason"], "inaccurate")

    def test_non_staff_cannot_list_reports(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.member_token}")
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 403)
