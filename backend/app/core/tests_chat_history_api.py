from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import UserChatHistory

User = get_user_model()


class ChatHistoryAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="history_user",
            email="history@example.com",
            password="pass12345",
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()

    def test_requires_auth(self):
        res = self.client.get("/api/chat/history/")
        self.assertEqual(res.status_code, 401)

    def test_get_empty_then_put_and_get(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        empty = self.client.get("/api/chat/history/")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data["entries"], [])

        payload = {
            "entries": [
                {
                    "sessionId": "abc-123",
                    "title": "What is faith?",
                    "updatedAt": 100,
                    "messages": [{"role": "user", "text": "What is faith?"}],
                }
            ],
            "active_session_id": "abc-123",
            "schema_version": 1,
        }
        put = self.client.put("/api/chat/history/", payload, format="json")
        self.assertEqual(put.status_code, 200)
        self.assertEqual(len(put.data["entries"]), 1)

        got = self.client.get("/api/chat/history/")
        self.assertEqual(got.data["active_session_id"], "abc-123")
        self.assertEqual(got.data["entries"][0]["sessionId"], "abc-123")
        self.assertEqual(UserChatHistory.objects.filter(user=self.user).count(), 1)

    def test_put_drops_entries_without_session_id(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        put = self.client.put(
            "/api/chat/history/",
            {
                "entries": [
                    {"title": "bad"},
                    {"sessionId": "ok", "title": "good", "updatedAt": 1, "messages": []},
                ]
            },
            format="json",
        )
        self.assertEqual(put.status_code, 200)
        self.assertEqual(len(put.data["entries"]), 1)
        self.assertEqual(put.data["entries"][0]["sessionId"], "ok")


class LiveChatHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="live_user",
            email="live@example.com",
            password="pass12345",
        )

    def test_upsert_shows_prompt_immediately_then_grows_answer(self):
        from .live_chat_history import upsert_live_chat_turn

        upsert_live_chat_turn(
            user=self.user,
            client_session_id="faith-live",
            user_query="Recount what Pastor Don believes about faith?",
            answer="",
            streaming=True,
        )
        row = UserChatHistory.objects.get(user=self.user)
        self.assertEqual(row.active_session_id, "faith-live")
        self.assertEqual(row.entries[0]["messages"][0]["text"], "Recount what Pastor Don believes about faith?")
        self.assertEqual(row.entries[0]["messages"][1]["text"], "")
        self.assertTrue(row.entries[0]["messages"][1]["streaming"])

        upsert_live_chat_turn(
            user=self.user,
            client_session_id="faith-live",
            user_query="Recount what Pastor Don believes about faith?",
            answer="Faith is trust in God.",
            streaming=True,
        )
        row.refresh_from_db()
        self.assertEqual(len(row.entries[0]["messages"]), 2)
        self.assertEqual(row.entries[0]["messages"][1]["text"], "Faith is trust in God.")

        upsert_live_chat_turn(
            user=self.user,
            client_session_id="faith-live",
            user_query="Recount what Pastor Don believes about faith?",
            answer='Faith is trust in God. "Without faith it is impossible to please God."',
            sources=["Faith That Works"],
            streaming=False,
        )
        row.refresh_from_db()
        self.assertNotIn("streaming", row.entries[0]["messages"][1])
        self.assertEqual(row.entries[0]["messages"][1]["sources"], ["Faith That Works"])

    def test_put_does_not_clobber_in_flight_stream(self):
        from .live_chat_history import upsert_live_chat_turn

        upsert_live_chat_turn(
            user=self.user,
            client_session_id="faith-live",
            user_query="What is faith?",
            answer="Faith is trust in God.",
            streaming=True,
        )
        token = Token.objects.create(user=self.user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        put = client.put(
            "/api/chat/history/",
            {
                "entries": [
                    {
                        "sessionId": "faith-live",
                        "title": "What is faith?",
                        "updatedAt": 999999,
                        "messages": [{"role": "user", "text": "What is faith?"}],
                    }
                ],
                "active_session_id": "other",
                "schema_version": 1,
            },
            format="json",
        )
        self.assertEqual(put.status_code, 200)
        self.assertEqual(len(put.data["entries"][0]["messages"]), 2)
        self.assertTrue(put.data["entries"][0]["messages"][1]["streaming"])
        self.assertEqual(put.data["active_session_id"], "faith-live")

        got = client.get("/api/chat/history/")
        self.assertEqual(got["Cache-Control"], "private, no-store")
        self.assertEqual(got.data["entries"][0]["messages"][1]["text"], "Faith is trust in God.")
