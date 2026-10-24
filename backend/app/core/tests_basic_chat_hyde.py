import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.basic_chat import _promote_lexical, _prompt, _search_qdrant, retrieve_passages

HYDE_TEXT = (
    "UNIQUE_HYDE_TRINITY_MARKER The Father the Son and the Holy Spirit "
    "are one God. This is the Trinity and the Godhead."
)


def _hit(title: str, text: str, score: float = 0.5):
    return SimpleNamespace(
        score=score,
        payload={"title": title, "text": text},
    )


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
                return list(query_hits)
            if vector == [2]:
                return list(hyde_hits)
            raise AssertionError(f"unexpected vector {vector}")

        return search

    def test_hyde_titles_are_merged_ahead_of_the_question(self):
        embeddings, calls = self._embeddings()
        query_hits = [
            _hit("Advent", "We wait for the coming of Christ.", 0.91),
            _hit("Christmas", "The child is born in Bethlehem.", 0.88),
        ]
        hyde_hits = [
            _hit("Nextsteps 101", "The Trinity is Father Son and Spirit.", 0.42),
            _hit("Why Receive the Holy Spirit", "The Godhead is one God.", 0.40),
        ]
        with patch.dict(os.environ, {"CHAT_HYDE": "1"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=embeddings
        ), patch(
            "core.basic_chat._search_qdrant",
            side_effect=self._search(query_hits, hyde_hits),
        ), patch(
            "core.basic_chat.generate_hyde_document", return_value=HYDE_TEXT
        ):
            result = retrieve_passages("What is the Trinity?", include_debug=True)

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
        prompt = _prompt("What is the Trinity?", [{"title": "Why Receive the Holy Spirit", "text": text}])
        excerpt = prompt[1]["content"]
        self.assertIn("third person of the Holy Trinity", excerpt)
        self.assertLess(len(excerpt), len(text))
