import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.embeddings_utils import QueryPrefixedEmbeddings
from core.sermon_catalog import (
    CatalogEntry,
    catalog_title_queries,
    catalog_tokens,
    lookup_chunks_by_file_hashes,
    match_catalog_entries,
    score_catalog_title,
)


def _entry(title, file_hash, **kwargs):
    return CatalogEntry(title=title, file_hash=file_hash, **kwargs)


class SermonCatalogTests(unittest.TestCase):
    def test_faith_prefers_faith_titled_sermons_not_community(self):
        entries = [
            _entry("Community", "community-hash"),
            _entry("Contagious Christianity", "contagious-hash"),
            _entry("Faith That Moves Mountains", "faith-hash"),
            _entry("Works, Hope, Faith & Patience", "works-hash"),
            _entry("3 D Resurrection", "resurrection-hash"),
            _entry("New King James Version", "nkjv-hash", source_name="nkjv-bible.pdf"),
        ]
        hits = match_catalog_entries(entries, "Give me a 3 point sermon on faith", limit=3)
        titles = [item.title for item in hits]
        self.assertIn("Faith That Moves Mountains", titles)
        self.assertIn("Works, Hope, Faith & Patience", titles)
        self.assertNotIn("Community", titles)
        self.assertNotIn("3 D Resurrection", titles)
        self.assertTrue(hits[0].title.startswith("Faith"), hits)
        self.assertGreater(
            score_catalog_title(entries[2], catalog_tokens("faith")),
            score_catalog_title(entries[3], catalog_tokens("faith")),
        )

    def test_gratitude_matches_thanksgiving_title(self):
        entries = [
            _entry("Community", "community-hash"),
            _entry("A Lifestyle of Thanksgiving", "thanks-hash"),
            _entry("Harvest", "harvest-hash"),
        ]
        hits = match_catalog_entries(entries, "gratitude", limit=3)
        self.assertEqual([item.title for item in hits], ["A Lifestyle of Thanksgiving"])

    def test_prayer_matches_plural_title(self):
        entries = [
            _entry("Community", "community-hash"),
            _entry("Prayers That Prevail for the Lost", "prayer-hash"),
            _entry("Happy People", "happy-hash"),
        ]
        hits = match_catalog_entries(
            entries, "What does Pastor Don teach about prayer?", limit=3
        )
        self.assertEqual([item.title for item in hits], ["Prayers That Prevail for the Lost"])

    def test_gay_people_does_not_match_happy_people(self):
        entries = [
            _entry("Happy People", "happy-hash"),
            _entry("Christian Boundaries", "bound-hash"),
            _entry("Community", "community-hash"),
        ]
        hits = match_catalog_entries(entries, "Can gay people be Christians?", limit=3)
        titles = [item.title for item in hits]
        self.assertNotIn("Happy People", titles)
        self.assertNotIn("Christian Boundaries", titles)

    def test_marriage_does_not_match_church_covenant_titles(self):
        entries = [
            _entry("Covenant Bringers", "bring-hash"),
            _entry("Covenant Servanthood", "serve-hash"),
            _entry("Going Beyond Covenant 3 Mq Edit", "beyond-hash"),
            _entry("Marriage That Lasts", "marriage-hash"),
        ]
        hits = match_catalog_entries(
            entries, "Give me a 3 point sermon on marriage", limit=3
        )
        self.assertEqual([item.title for item in hits], ["Marriage That Lasts"])

    def test_drink_query_matches_sippin_saints(self):
        entries = [
            _entry("Community", "community-hash"),
            _entry("Sippin’ Saints", "sippin-hash"),
            _entry("Crying for Wine", "wine-hash"),
            _entry("Happy People", "happy-hash"),
        ]
        hits = match_catalog_entries(entries, "Can Christians drink?", limit=3)
        titles = [item.title for item in hits]
        self.assertIn("Sippin’ Saints", titles)
        self.assertIn("Crying for Wine", titles)
        self.assertNotIn("Happy People", titles)

    def test_catalog_title_queries_include_pastor_don(self):
        hits = match_catalog_entries(
            [_entry("Faith That Moves Mountains", "faith-hash")],
            "faith",
        )
        queries = catalog_title_queries(hits)
        joined = " ".join(queries).lower()
        self.assertIn("faith that moves mountains", joined)
        self.assertIn("pastor don nordin", joined)

    def test_lookup_chunks_filters_by_file_hash(self):
        point = SimpleNamespace(
            payload={
                "text": "Faith must refuse the if factor of doubt.",
                "file_hash": "faith-hash",
                "title": "Faith That Moves Mountains",
                "chunk_kind": "sermon_quote",
                "metadata": {
                    "file_hash": "faith-hash",
                    "title": "Faith That Moves Mountains",
                },
            }
        )
        client = Mock()
        client.scroll.return_value = ([point], None)

        class _Filter:
            def __init__(self, must=None):
                self.must = must

        class _FieldCondition:
            def __init__(self, key=None, match=None):
                self.key = key
                self.match = match

        class _MatchValue:
            def __init__(self, value=None):
                self.value = value

        fake_models = SimpleNamespace(
            Filter=_Filter,
            FieldCondition=_FieldCondition,
            MatchValue=_MatchValue,
        )
        fake_http = SimpleNamespace(models=fake_models)
        fake_client_mod = SimpleNamespace(http=fake_http)
        with patch.dict(
            "sys.modules",
            {
                "qdrant_client": fake_client_mod,
                "qdrant_client.http": fake_http,
                "qdrant_client.http.models": fake_models,
            },
        ):
            docs = lookup_chunks_by_file_hashes(client, "sermon_brain", ["faith-hash"])
        self.assertEqual(len(docs), 1)
        self.assertIn("if factor", docs[0].page_content.lower())
        client.scroll.assert_called()

    def test_lookup_chunks_ranks_topical_theses_over_intros(self):
        intro = SimpleNamespace(
            payload={
                "text": "BOUNDARIES. Do not remove the ancient landmark. God only gave us ten rules.",
                "file_hash": "bound-hash",
                "title": "Christian Boundaries",
                "chunk_kind": "sermon_quote",
                "metadata": {"file_hash": "bound-hash", "title": "Christian Boundaries"},
            }
        )
        thesis = SimpleNamespace(
            payload={
                "text": (
                    "We must love the homosexual and stand firmly against the lifestyle. "
                    "Homosexuality is not an acceptable lifestyle by natural law or the law of God."
                ),
                "file_hash": "bound-hash",
                "title": "Christian Boundaries",
                "chunk_kind": "sermon_quote",
                "metadata": {"file_hash": "bound-hash", "title": "Christian Boundaries"},
            }
        )
        client = Mock()
        client.scroll.return_value = ([intro, thesis], None)

        class _Filter:
            def __init__(self, must=None):
                self.must = must

        class _FieldCondition:
            def __init__(self, key=None, match=None):
                self.key = key
                self.match = match

        class _MatchValue:
            def __init__(self, value=None):
                self.value = value

        fake_models = SimpleNamespace(
            Filter=_Filter,
            FieldCondition=_FieldCondition,
            MatchValue=_MatchValue,
        )
        fake_http = SimpleNamespace(models=fake_models)
        fake_client_mod = SimpleNamespace(http=fake_http)
        with patch.dict(
            "sys.modules",
            {
                "qdrant_client": fake_client_mod,
                "qdrant_client.http": fake_http,
                "qdrant_client.http.models": fake_models,
            },
        ):
            docs = lookup_chunks_by_file_hashes(
                client,
                "sermon_brain",
                ["bound-hash"],
                query="Can gay people be Christians?",
                limit_per_file=1,
            )
        self.assertEqual(len(docs), 1)
        self.assertIn("love the homosexual", docs[0].page_content.lower())


class QueryPrefixEmbeddingTests(unittest.TestCase):
    def test_prefixes_queries_not_documents(self):
        class Inner:
            def __init__(self):
                self.queries = []
                self.docs = []

            def embed_query(self, text):
                self.queries.append(text)
                return [0.1, 0.2]

            def embed_documents(self, texts):
                self.docs.extend(texts)
                return [[0.1, 0.2] for _ in texts]

        inner = Inner()
        wrapped = QueryPrefixedEmbeddings(
            inner, "Represent this sentence for searching relevant passages: "
        )
        wrapped.embed_query("faith")
        wrapped.embed_documents(["Faith must refuse the if factor."])
        self.assertTrue(
            inner.queries[0].startswith("Represent this sentence for searching relevant passages:"),
            inner.queries,
        )
        self.assertIn("faith", inner.queries[0])
        self.assertEqual(inner.docs, ["Faith must refuse the if factor."])
        try:
            from langchain_core.embeddings import Embeddings
        except Exception:
            self.skipTest("langchain_core is not installed")
        self.assertIsInstance(wrapped, Embeddings)
