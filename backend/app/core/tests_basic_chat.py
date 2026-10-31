import os
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from api.models import Profile
from core.models import ChatMessage, UserChatHistory

User = get_user_model()


class BasicChatAPITests(APITestCase):
    def setUp(self):
        self.premium = self._user("premium@example.com", premium=True)
        self.free = self._user("free@example.com", premium=False)
        self.passages = [
            {"title": "Faith That Moves", "text": "Faith is trust in God."},
            {"title": "Faith That Moves", "text": "Hope follows faith."},
        ]

    def _user(self, email, *, premium):
        user = User.objects.create_user(username=email, email=email, password="pass12345")
        profile = user.profile
        profile.subscription_status = (
            Profile.SubscriptionStatus.ACTIVE if premium else Profile.SubscriptionStatus.FREE
        )
        profile.email_verified = True
        profile.save(update_fields=["subscription_status", "email_verified"])
        Token.objects.create(user=user)
        return user

    def _auth(self, user):
        token = Token.objects.get(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_get_is_hidden(self):
        self._auth(self.premium)
        res = self.client.get("/api/chat/")
        self.assertEqual(res.status_code, 404)

    def test_requires_login(self):
        res = self.client.post("/api/chat/", {"query": "What is faith?"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_free_account_is_paywalled(self):
        self._auth(self.free)
        res = self.client.post("/api/chat/", {"query": "What is faith?"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_sse_streams_deltas_and_saves_reply(self):
        self._auth(self.premium)
        tokens = iter(["Faith ", "is trust."])

        def fake_retrieve(query, **kwargs):
            self.assertIn("faith", query.lower())
            return list(self.passages)

        def fake_stream(query, passages):
            self.assertEqual(passages[0]["title"], "Faith That Moves")
            yield from tokens

        with patch("core.basic_chat_views.retrieve_passages", fake_retrieve), patch(
            "core.basic_chat_views.stream_llm_tokens", fake_stream
        ):
            res = self.client.post(
                "/api/chat/",
                {"query": "What is faith?", "session_id": "s1", "stream": True},
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
            self.assertEqual(res.status_code, 200)
            self.assertIn("text/event-stream", res["Content-Type"])
            body = b"".join(res.streaming_content).decode()
        self.assertIn('"phase": "retrieving"', body)
        self.assertIn('"type": "delta"', body)
        self.assertIn("Faith ", body)
        self.assertIn("is trust.", body)
        self.assertIn('"type": "done"', body)
        self.assertIn("Faith That Moves", body)
        saved = ChatMessage.objects.get(session_id="s1")
        self.assertEqual(saved.ai_response, "Faith is trust.")
        self.assertEqual(saved.user, self.premium)
        history = self.client.get("/api/chat/history/")
        self.assertEqual(history.status_code, 200)
        entry = history.data["entries"][0]
        self.assertEqual(entry["sessionId"], "s1")
        self.assertEqual(entry["messages"][0]["text"], "What is faith?")
        self.assertEqual(entry["messages"][1]["text"], "Faith is trust.")
        self.assertEqual(entry["messages"][1]["sources"], ["Faith That Moves"])
        self.assertEqual(
            UserChatHistory.objects.get(user=self.premium).active_session_id,
            "s1",
        )

    def test_json_reply_without_stream_flag(self):
        self._auth(self.premium)

        with patch(
            "core.basic_chat_views.retrieve_passages", return_value=self.passages
        ), patch(
            "core.basic_chat_views.stream_llm_tokens",
            return_value=iter(["Hello."]),
        ):
            res = self.client.post(
                "/api/chat/",
                {"query": "What is faith?"},
                format="json",
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["answer"], "Hello.")
        self.assertEqual(res.data["sources"], ["Faith That Moves"])

    def test_sse_keepalives_while_retrieval_is_slow(self):
        self._auth(self.premium)

        def slow_retrieve(query, **kwargs):
            time.sleep(0.3)
            return list(self.passages)

        with patch.dict(os.environ, {"CHAT_KEEPALIVE_S": "0.05"}), patch(
            "core.basic_chat_views.retrieve_passages", slow_retrieve
        ), patch(
            "core.basic_chat_views.stream_llm_tokens",
            return_value=iter(["Hello."]),
        ):
            res = self.client.post(
                "/api/chat/",
                {"query": "What is faith?", "stream": True},
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
            body = b"".join(res.streaming_content).decode()
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(body.count(": keepalive"), 2)
        self.assertIn("Hello.", body)
