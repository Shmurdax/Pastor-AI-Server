"""Multi-turn chat through ChatAPIView: what each prompt actually contains."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

PRODIGAL = (
    "The older brother stayed outside. The father ran to the younger son. "
    "A husband who will not love his wife sins against the marriage covenant."
)
CAIN = "Cain rose up against Abel his brother in the field."
PENTECOST = (
    "Pentecost filled the room. They spoke in tongues as the Spirit gave utterance."
)
GIFTS = "Spiritual gifts are given so the church can build itself up in love."

OPENING = "Explain the parable of the prodigal son from the sermon notes."
OLDER = "What about the older brother?"
CAIN_Q = "Tell the story of Cain and Abel."
MORE = "Say more about that."
PENTECOST_Q = "Now tell me what Pastor Don teaches about Pentecost."
GIFTS_Q = "I want to talk about something else: spiritual gifts."


def _notes_for(query: str) -> tuple[str, str, str]:
    """Return (body, coverage, label) for a mocked retrieval."""
    text = (query or "").lower()
    scored = (
        ("Prodigal Son", PRODIGAL, ("prodigal", "older brother", "younger son")),
        ("Cain and Abel", CAIN, ("cain", "abel")),
        ("Pentecost", PENTECOST, ("pentecost", "tongues")),
        ("Spiritual Gifts", GIFTS, ("spiritual gifts", "gifts")),
    )
    best_label, best_body, best_score = "", "", 0
    for label, body, keys in scored:
        score = sum(1 for key in keys if key in text)
        if score > best_score:
            best_label, best_body, best_score = label, body, score
    if best_score <= 0:
        return "", "none", ""
    return best_body, "full", best_label


def _focused(_vectorstore, _client, _collection, search_text, rerank_text=None):
    body, coverage, label = _notes_for(rerank_text or search_text)
    if coverage != "full":
        return [], "none"
    doc = SimpleNamespace(
        page_content=body,
        metadata={"source": f"{label}.pdf", "title": label},
    )
    return [doc], "full"


class TopicThreadChatTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="member@church.org",
            email="member@church.org",
            password="MemberPass123!",
        )
        self.user.profile.subscription_status = "active"
        self.user.profile.email_verified = True
        self.user.profile.save(update_fields=["subscription_status", "email_verified"])
        token = Token.objects.create(user=self.user).key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.captured: list[list] = []

    def _llm(self):
        bound = MagicMock()

        def invoke(messages):
            self.captured.append(list(messages))
            question = ""
            notes = ""
            for msg in reversed(messages):
                content = getattr(msg, "content", "") or ""
                if "User question:" in content and not question:
                    question = content.split("User question:", 1)[1].strip().split("\n", 1)[0]
                if "SERMON NOTES:" in content and not notes:
                    notes = content.split("SERMON NOTES:", 1)[1].strip()
            body, _coverage, label = _notes_for(question)
            if not body and "[Note" in notes:
                note_body = notes.split("]", 1)[-1].strip()
                body = note_body
                label = "current"
            if not body:
                body = "the current sermon"
                label = label or "current"
            reply = MagicMock()
            reply.content = f"From the {label} sermon: {body.split('.')[0].strip()}."
            return reply

        bound.invoke.side_effect = invoke
        llm = MagicMock()
        llm.bind.return_value = bound
        return llm

    def _post(self, query: str):
        with (
            patch("core.views.get_chat_llm", return_value=self._llm()),
            patch("core.views._focused_sermon_docs", side_effect=_focused),
            patch("core.views.attach_supporting_scripture", return_value=([], "")),
            patch("core.views._get_embeddings", return_value=MagicMock()),
            patch("core.views.QdrantClient", return_value=MagicMock()),
            patch("core.views.QdrantVectorStore", return_value=MagicMock()),
            patch("core.views.ensure_sermon_collection"),
        ):
            response = self.client.post(
                "/api/chat/",
                {"query": query, "session_id": "topic-thread-session"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        return response.data["answer"]

    def _history_text(self) -> str:
        messages = self.captured[-1]
        parts = []
        for msg in messages[1:-1]:
            role = msg.__class__.__name__.replace("Message", "")
            parts.append(f"{role}: {msg.content}")
        return "\n".join(parts)

    def _notes_text(self) -> str:
        system = self.captured[-1][0].content
        if "REFERENCE NOTES:" not in system:
            return ""
        return system.split("REFERENCE NOTES:", 1)[1].strip()

    def test_full_exchange_drops_unrelated_turns(self):
        transcript = []
        questions = [OPENING, OLDER, CAIN_Q, MORE, PENTECOST_Q, GIFTS_Q, MORE]
        for query in questions:
            before = len(self.captured)
            answer = self._post(query)
            if len(self.captured) == before:
                history = ""
                notes = ""
            else:
                history = self._history_text()
                notes = self._notes_text()
            transcript.append((query, history, notes, answer))

        opening_q, opening_history, opening_notes, _opening_answer = transcript[0]
        self.assertEqual(opening_q, OPENING)
        self.assertEqual(opening_history, "")
        self.assertIn("younger son", opening_notes)

        _older_q, older_history, older_notes, _older_answer = transcript[1]
        self.assertIn(OPENING, older_history)
        self.assertIn("younger son", older_notes)

        _cain_q, cain_history, cain_notes, _cain_answer = transcript[2]
        self.assertNotIn("prodigal", cain_history.lower())
        self.assertNotIn("older brother", cain_history.lower())
        self.assertIn("Cain rose up", cain_notes)
        self.assertNotIn("younger son", cain_notes)

        _more_q, more_history, more_notes, _more_answer = transcript[3]
        self.assertIn(CAIN_Q, more_history)
        self.assertNotIn("prodigal", more_history.lower())
        self.assertNotIn(OPENING, more_history)
        self.assertIn("Cain rose up", more_notes)

        _pentecost_q, pentecost_history, pentecost_notes, _pentecost_answer = transcript[4]
        self.assertEqual(pentecost_history, "")
        self.assertIn("tongues", pentecost_notes)
        self.assertNotIn("Cain", pentecost_notes)
        self.assertNotIn("younger son", pentecost_notes)

        _gifts_q, gifts_history, gifts_notes, _gifts_answer = transcript[5]
        self.assertEqual(gifts_history, "")
        self.assertIn("Spiritual gifts", gifts_notes)
        self.assertNotIn("tongues", gifts_notes)

        _again_q, again_history, again_notes, _again_answer = transcript[6]
        self.assertIn(GIFTS_Q, again_history)
        self.assertNotIn("Pentecost", again_history)
        self.assertNotIn("Cain", again_history)
        self.assertIn("Spiritual gifts", again_notes)

        lines = ["Full chat exchange", ""]
        for index, (query, history, notes, answer) in enumerate(transcript, start=1):
            lines.append(f"Turn {index}")
            lines.append(f"User: {query}")
            lines.append("Prior replies sent to the model:")
            lines.append(history or "(none)")
            lines.append("Sermon notes attached:")
            lines.append(notes or "(none)")
            lines.append(f"Assistant: {answer}")
            lines.append("")
        self.transcript = "\n".join(lines)
        print(self.transcript)
