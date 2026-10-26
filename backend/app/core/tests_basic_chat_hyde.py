import io
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from api.models import Profile
from core.basic_chat import (
    HYDE_CANDIDATES,
    _clip_words,
    _merge_ranked,
    _message_text,
    _promote_lexical,
    _prompt,
    _query_terms,
    _search_qdrant,
    generate_hyde_document,
    hyde_enabled,
    retrieve_passages,
)
from core.models import ChatMessage

User = get_user_model()

HYDE_TEXT = (
    "UNIQUE_HYDE_TRINITY_MARKER The Father the Son and the Holy Spirit "
    "are one God. This is the Trinity and the Godhead."
)


def _hit(title: str, text: str, score: float = 0.5, *, payload=None):
    body = payload if payload is not None else {"title": title, "text": text}
    return SimpleNamespace(score=score, payload=body)


class HyDERetrievalTests(SimpleTestCase):
    def _embeddings(self):
        calls = []

        class Embeddings:
            def embed_query(self, text):
                calls.append(text)
                return [len(calls)]

        return Embeddings(), calls

    def _search(self, query_hits, hyde_hits):
        def search(client, collection, vector, top_k):
            if vector == [1]:
                return list(query_hits)[:top_k]
            if vector == [2]:
                return list(hyde_hits)[:top_k]
            raise AssertionError(f"unexpected vector {vector}")

        return search

    def _retrieve(self, *, query_hits, hyde_hits=None, hyde_text=HYDE_TEXT, env=None):
        embeddings, calls = self._embeddings()
        hyde_hits = [] if hyde_hits is None else hyde_hits
        env = {"CHAT_HYDE": "1", **(env or {})}
        with patch.dict(os.environ, env), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch(
            "core.basic_chat._search_qdrant",
            side_effect=self._search(query_hits, hyde_hits),
        ), patch(
            "core.basic_chat.generate_hyde_document", return_value=hyde_text
        ) as hyde:
            result = retrieve_passages("What is the Trinity?", include_debug=True)
        return result, calls, hyde

    def test_hyde_titles_are_merged_ahead_of_the_question(self):
        query_hits = [
            _hit("Advent", "We wait for the coming of Christ.", 0.91),
            _hit("Christmas", "The child is born in Bethlehem.", 0.88),
        ]
        hyde_hits = [
            _hit("Nextsteps 101", "The Trinity is Father Son and Spirit.", 0.42),
            _hit("Why Receive the Holy Spirit", "The Godhead is one God.", 0.40),
        ]
        result, calls, _ = self._retrieve(query_hits=query_hits, hyde_hits=hyde_hits)

        self.assertEqual(calls[0], "What is the Trinity?")
        self.assertEqual(calls[1], HYDE_TEXT)
        self.assertEqual(
            result["hyde_titles"],
            ["Nextsteps 101", "Why Receive the Holy Spirit"],
        )
        self.assertEqual(result["query_titles"], ["Advent", "Christmas"])
        self.assertEqual(
            [item["title"] for item in result["passages"]],
            [
                "Nextsteps 101",
                "Advent",
                "Why Receive the Holy Spirit",
                "Christmas",
            ],
        )
        prompt = _prompt("What is the Trinity?", result["passages"])
        rendered = prompt[0]["content"] + prompt[1]["content"]
        self.assertNotIn("UNIQUE_HYDE_TRINITY_MARKER", rendered)
        self.assertIn("The Trinity is Father Son and Spirit.", rendered)

    def test_hyde_failure_keeps_the_question_hits(self):
        embeddings, calls = self._embeddings()
        query_hits = [_hit("Advent", "We wait for the coming of Christ.")]

        def explode(query):
            raise RuntimeError("vLLM down")

        with patch.dict(os.environ, {"CHAT_HYDE": "1"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch(
            "core.basic_chat._search_qdrant",
            side_effect=self._search(query_hits, []),
        ), patch("core.basic_chat.generate_hyde_document", side_effect=explode):
            result = retrieve_passages("What is the Trinity?", include_debug=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["hyde_text"], "")
        self.assertEqual(result["hyde_titles"], [])
        self.assertEqual([item["title"] for item in result["passages"]], ["Advent"])

    def test_empty_hyde_text_skips_the_second_search(self):
        query_hits = [_hit("Advent", "We wait for the coming of Christ.")]
        result, calls, _ = self._retrieve(query_hits=query_hits, hyde_hits=[], hyde_text="")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["hyde_text"], "")
        self.assertEqual(result["hyde_titles"], [])
        self.assertEqual([item["title"] for item in result["passages"]], ["Advent"])

    def test_hyde_search_failure_keeps_the_question_hits(self):
        embeddings, calls = self._embeddings()
        query_hits = [_hit("Advent", "We wait for the coming of Christ.")]

        def search(client, collection, vector, top_k):
            if vector == [1]:
                return list(query_hits)
            raise RuntimeError("qdrant down")

        with patch.dict(os.environ, {"CHAT_HYDE": "1"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch("core.basic_chat._search_qdrant", side_effect=search), patch(
            "core.basic_chat.generate_hyde_document", return_value=HYDE_TEXT
        ):
            result = retrieve_passages("What is the Trinity?", include_debug=True)

        self.assertEqual(calls, ["What is the Trinity?", HYDE_TEXT])
        self.assertEqual(result["hyde_text"], HYDE_TEXT)
        self.assertEqual(result["hyde_titles"], [])
        self.assertEqual([item["title"] for item in result["passages"]], ["Advent"])

    def test_hyde_can_be_turned_off(self):
        embeddings, calls = self._embeddings()
        query_hits = [_hit("Advent", "We wait for the coming of Christ.")]

        def explode(query):
            raise AssertionError("HyDE should not run")

        with patch.dict(os.environ, {"CHAT_HYDE": "0"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch(
            "core.basic_chat._search_qdrant",
            side_effect=self._search(query_hits, []),
        ), patch("core.basic_chat.generate_hyde_document", side_effect=explode):
            result = retrieve_passages("What is faith?", include_debug=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["passages"][0]["title"], "Advent")

    def test_hyde_env_aliases_turn_it_off(self):
        for value in ("false", "no", "off", "FALSE"):
            with patch.dict(os.environ, {"CHAT_HYDE": value}):
                self.assertFalse(hyde_enabled(), msg=value)

    def test_duplicate_chunks_are_dropped_across_searches(self):
        shared = "The Holy Spirit is the third person of the Holy Trinity."
        query_hits = [
            _hit("Why Receive the Holy Spirit", shared, 0.55),
            _hit("Advent", "We wait for the coming of Christ.", 0.50),
        ]
        hyde_hits = [
            _hit("Why Receive the Holy Spirit", shared, 0.70),
            _hit("Nextsteps 101", "The Trinity is Father Son and Spirit.", 0.60),
        ]
        result, _, _ = self._retrieve(query_hits=query_hits, hyde_hits=hyde_hits)
        titles = [item["title"] for item in result["passages"]]
        self.assertEqual(titles.count("Why Receive the Holy Spirit"), 1)
        # HyDE slot first, then the next HyDE hit fills the odd slot after the
        # duplicate query hit is skipped.
        self.assertEqual(
            titles,
            [
                "Why Receive the Holy Spirit",
                "Nextsteps 101",
                "Advent",
            ],
        )

    def test_merge_caps_at_top_k_and_prefers_hyde_slots(self):
        hyde_hits = [
            {"title": f"HyDE {i}", "text": f"hyde text {i}", "score": 0.5}
            for i in range(1, 5)
        ]
        query_hits = [
            {"title": f"Query {i}", "text": f"query text {i}", "score": 0.9}
            for i in range(1, 5)
        ]
        merged = _merge_ranked(hyde_hits, query_hits, top_k=4)
        self.assertEqual(
            [item["title"] for item in merged],
            ["HyDE 1", "Query 1", "HyDE 2", "Query 2"],
        )

    def test_candidate_depth_is_requested_before_merge(self):
        seen_limits = []

        def search(client, collection, vector, top_k):
            seen_limits.append(top_k)
            return [_hit("Advent", f"text for {vector}", 0.5)]

        embeddings, _ = self._embeddings()
        with patch.dict(os.environ, {"CHAT_HYDE": "1"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch("core.basic_chat._search_qdrant", side_effect=search), patch(
            "core.basic_chat.generate_hyde_document", return_value=HYDE_TEXT
        ):
            retrieve_passages("What is the Trinity?", top_k=6)

        self.assertEqual(seen_limits, [HYDE_CANDIDATES, HYDE_CANDIDATES])

    def test_question_term_promotes_the_sermon_that_uses_it(self):
        promoted = _promote_lexical(
            [
                {
                    "title": "The Fear Not's of Christmas",
                    "text": "Do not be afraid. The child is born.",
                    "score": 0.66,
                },
                {
                    "title": "Why Receive the Holy Spirit",
                    "text": "The Holy Spirit is the third person of the Holy Trinity.",
                    "score": 0.56,
                },
            ],
            {"trinity"},
        )
        self.assertEqual(promoted[0]["title"], "Why Receive the Holy Spirit")

    def test_query_terms_skip_short_and_stop_words(self):
        self.assertEqual(_query_terms("What is the Trinity about there?"), {"trinity"})
        self.assertEqual(_query_terms("How should believers repent?"), {"believers", "repent"})

    def test_search_keeps_sermon_quotes_only(self):
        seen = {}

        class Client:
            def query_points(self, **kwargs):
                seen.update(kwargs)
                return SimpleNamespace(points=[])

        _search_qdrant(Client(), "sermon_brain", [0.1], 4)
        sermon_filter = seen["query_filter"]
        self.assertEqual(sermon_filter.must[0].key, "chunk_kind")
        self.assertEqual(sermon_filter.must[0].match.value, "sermon_quote")
        self.assertEqual(seen["limit"], 4)

    def test_legacy_search_api_also_filters_sermons(self):
        seen = {}

        class Client:
            def search(self, **kwargs):
                seen.update(kwargs)
                return []

        _search_qdrant(Client(), "sermon_brain", [0.1], 3)
        self.assertEqual(seen["query_filter"].must[0].match.value, "sermon_quote")
        self.assertEqual(seen["limit"], 3)

    def test_payload_title_and_text_fallbacks(self):
        result, _, _ = self._retrieve(
            query_hits=[
                _hit(
                    "",
                    "",
                    payload={"source": "From Source Key", "page_content": "page body"},
                )
            ],
            hyde_hits=[
                _hit(
                    "",
                    "",
                    payload={
                        "metadata": {"title": "From Metadata", "content": "meta body"},
                    },
                )
            ],
        )
        self.assertEqual(
            [item["title"] for item in result["passages"]],
            ["From Metadata", "From Source Key"],
        )
        self.assertEqual(result["passages"][0]["text"], "meta body")
        self.assertEqual(result["passages"][1]["text"], "page body")

    def test_answer_system_prompt_asks_for_pastoral_teaching(self):
        prompt = _prompt(
            "What is faith?",
            [{"title": "Faith That Moves", "text": "Faith is trust in God."}],
        )
        system = prompt[0]["content"]
        self.assertIn("Pastor Don's AI teaching assistant", system)
        self.assertIn("2–4 short paragraphs", system)
        self.assertIn("Do not invent sermon titles", system)
        self.assertIn("Do not fill gaps with outside theology", system)
        self.assertNotIn("say that briefly", system.lower())

    def test_prompt_truncates_oversized_excerpts(self):
        huge = ("Nextsteps doctrine " * 400).strip()
        prompt = _prompt("What is the Trinity?", [{"title": "Nextsteps 101", "text": huge}])
        excerpt = prompt[1]["content"]
        self.assertIn("…", excerpt)
        self.assertLess(len(excerpt), len(huge))
        self.assertLessEqual(excerpt.find("…"), 1300)

    def test_prompt_keeps_a_late_question_term(self):
        filler = "waiting for christmas " * 80
        text = f"{filler}The Holy Spirit is the third person of the Holy Trinity. {filler}"
        prompt = _prompt(
            "What is the Trinity?",
            [{"title": "Why Receive the Holy Spirit", "text": text}],
        )
        excerpt = prompt[1]["content"]
        self.assertIn("third person of the Holy Trinity", excerpt)
        self.assertLess(len(excerpt), len(text))

    def test_clip_words_and_message_shapes(self):
        long = " ".join(f"word{i}" for i in range(200))
        clipped = _clip_words(long, limit=10)
        self.assertEqual(len(clipped.split()), 10)
        self.assertEqual(
            _message_text({"choices": [{"message": {"content": "  Hello Trinity.  "}}]}),
            "Hello Trinity.",
        )
        self.assertEqual(
            _message_text(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"text": "Father "},
                                    {"text": "Son Spirit"},
                                ]
                            }
                        }
                    ]
                }
            ),
            "Father Son Spirit",
        )

    def test_generate_hyde_document_posts_non_streaming_request(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"choices": [{"message": {"content": "One God in three Persons."}}]}
                ).encode()

        def fake_post(body, *, timeout=None):
            captured["body"] = body
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("core.basic_chat._post_llm", side_effect=fake_post):
            text = generate_hyde_document("What is the Trinity?")

        self.assertEqual(text, "One God in three Persons.")
        self.assertFalse(captured["body"]["stream"])
        self.assertEqual(captured["body"]["max_tokens"], 180)
        self.assertIn("sermon-note paragraph", captured["body"]["messages"][0]["content"])
        self.assertEqual(captured["body"]["messages"][1]["content"], "What is the Trinity?")


class HyDEChatAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="hyde@example.com",
            email="hyde@example.com",
            password="pass12345",
        )
        profile = self.user.profile
        profile.subscription_status = Profile.SubscriptionStatus.ACTIVE
        profile.email_verified = True
        profile.save(update_fields=["subscription_status", "email_verified"])
        Token.objects.create(user=self.user)
        token = Token.objects.get(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_json_chat_never_puts_hyde_text_in_the_answer_prompt(self):
        hyde_marker = "UNIQUE_HYDE_API_MARKER never show this"

        def fake_retrieve(query, **kwargs):
            return [
                {
                    "title": "Why Receive the Holy Spirit",
                    "text": "The Holy Spirit is the third person of the Holy Trinity.",
                }
            ]

        def fake_stream(query, passages):
            prompt = _prompt(query, passages)
            rendered = prompt[0]["content"] + prompt[1]["content"]
            self.assertNotIn(hyde_marker, rendered)
            self.assertIn("third person of the Holy Trinity", rendered)
            yield "The Spirit is the third person of the Trinity."

        with patch("core.basic_chat_views.retrieve_passages", fake_retrieve), patch(
            "core.basic_chat_views.stream_llm_tokens", fake_stream
        ), patch("core.basic_chat.generate_hyde_document", return_value=hyde_marker):
            res = self.client.post(
                "/api/chat/",
                {"query": "What is the Trinity?", "session_id": "hyde-json"},
                format="json",
            )

        self.assertEqual(res.status_code, 200)
        self.assertIn("Trinity", res.data["answer"])
        self.assertEqual(res.data["sources"], ["Why Receive the Holy Spirit"])
        saved = ChatMessage.objects.get(session_id="hyde-json")
        self.assertNotIn(hyde_marker, saved.ai_response)

    def test_sse_chat_reports_retrieving_before_hyde_backed_answer(self):
        with patch(
            "core.basic_chat_views.retrieve_passages",
            return_value=[
                {
                    "title": "Nextsteps 101",
                    "text": "We believe in one God: Father, Son, and Holy Spirit.",
                }
            ],
        ), patch(
            "core.basic_chat_views.stream_llm_tokens",
            return_value=iter(["One God in three persons."]),
        ):
            res = self.client.post(
                "/api/chat/",
                {
                    "query": "Explain the Trinity from the notes.",
                    "session_id": "hyde-sse",
                    "stream": True,
                },
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
            body = b"".join(res.streaming_content).decode()

        self.assertEqual(res.status_code, 200)
        self.assertLess(body.find('"phase": "retrieving"'), body.find('"type": "delta"'))
        self.assertIn("One God in three persons.", body)
        self.assertIn("Nextsteps 101", body)
