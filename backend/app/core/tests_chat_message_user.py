from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.admin import ChatMessageAdmin
from core.models import ChatMessage
from core.scope_gate import OUT_OF_SCOPE_REPLY


class ChatMessageUserModelTests(TestCase):
    def test_chat_message_stores_login_user(self):
        user = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        msg = ChatMessage.objects.create(
            session_id="s:abc",
            user=user,
            user_query="Hello",
            ai_response="Hi there",
        )
        self.assertEqual(msg.user.email, "member@church.org")

    def test_admin_shows_sender_email(self):
        user = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        linked = ChatMessage.objects.create(
            session_id="s:linked",
            user=user,
            user_query="Pray with me",
            ai_response="Of course.",
        )
        anonymous = ChatMessage.objects.create(
            session_id="s:anon",
            user_query="Hello",
            ai_response="Hi",
        )
        admin = ChatMessageAdmin(ChatMessage, AdminSite())
        self.assertEqual(admin.sender_email(linked), "member@church.org")
        self.assertEqual(admin.sender_email(anonymous), "—")
        self.assertIn("sender_email", admin.list_display)

    def test_admin_falls_back_to_username_when_email_blank(self):
        user = User.objects.create_user(
            username="member@church.org",
            email="",
            password="MemberPass123!",
        )
        msg = ChatMessage.objects.create(
            session_id="s:fallback",
            user=user,
            user_query="Hello",
            ai_response="Hi",
        )
        admin = ChatMessageAdmin(ChatMessage, AdminSite())
        self.assertEqual(admin.sender_email(msg), "member@church.org")


class ChatAPIUserLinkTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/chat/"
        self.user = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        self.token = Token.objects.create(user=self.user).key

    @patch("core.views.query_in_scope", return_value=False)
    @patch("core.views.generate_out_of_scope_reply", return_value=OUT_OF_SCOPE_REPLY)
    @patch("core.views.ChatOpenAI", return_value=MagicMock())
    def test_authenticated_chat_links_sender_email(self, _mock_llm, _mock_oos, _mock_scope):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
        res = self.client.post(
            self.url,
            {
                "query": "What does Scripture say about hope?",
                "session_id": "client-session-1",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["answer"], OUT_OF_SCOPE_REPLY)
        msg = ChatMessage.objects.get()
        self.assertEqual(msg.user_id, self.user.id)
        self.assertEqual(msg.user.email, "member@church.org")

    @patch("core.views.query_in_scope", return_value=False)
    @patch("core.views.generate_out_of_scope_reply", return_value=OUT_OF_SCOPE_REPLY)
    @patch("core.views.ChatOpenAI", return_value=MagicMock())
    def test_anonymous_chat_leaves_user_null(self, _mock_llm, _mock_oos, _mock_scope):
        res = self.client.post(
            self.url,
            {
                "query": "What does Scripture say about hope?",
                "session_id": "client-session-anon",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        msg = ChatMessage.objects.get()
        self.assertIsNone(msg.user_id)
