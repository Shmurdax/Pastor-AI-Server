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
from core.teaching_claims import distinctive_query_tokens, extract_teaching_claims, query_topic_tokens
from core.chat_retrieval import (
    exclusive_title_lock_for_query,
    expand_search_queries,
    select_diverse_docs,
    select_major_source_keys,
    is_bible_source,
)


def _entry(title, file_hash, **kwargs):
    return CatalogEntry(title=title, file_hash=file_hash, **kwargs)


def _doc(text, *, source, file_hash=None, title=None):
    return SimpleNamespace(
        page_content=text,
        metadata={
            "source": source,
            "file_hash": file_hash or source,
            "title": title or source,
        },
    )


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


class DualLaneRetrievalTests(unittest.TestCase):
    def test_simple_faith_is_not_exclusive_title_lock(self):
        self.assertFalse(exclusive_title_lock_for_query("faith"))
        self.assertFalse(exclusive_title_lock_for_query("Give me a 3 point sermon on faith"))
        self.assertFalse(exclusive_title_lock_for_query("What does Pastor Don teach about faith?"))
        self.assertTrue(exclusive_title_lock_for_query("What are the prayer barriers Pastor Don teaches about?"))
        self.assertTrue(exclusive_title_lock_for_query("Can Christians drink?"))

    def test_expand_search_injects_catalog_titles(self):
        queries = expand_search_queries(
            "faith",
            catalog_titles=["Faith That Moves Mountains"],
            limit=8,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("faith that moves mountains", joined)
        self.assertTrue(queries[0].lower() == "faith" or "faith" in queries[0].lower(), queries)

    def test_faith_keeps_major_sermon_and_related_thesis(self):
        faith = _doc(
            "Faith must refuse the if factor of doubt and see the unseen promise.",
            source="faith.pdf",
            file_hash="faith-hash",
            title="Faith That Moves Mountains",
        )
        community = _doc(
            "Faith and hope show up in community life together as we love one another.",
            source="community.pdf",
            file_hash="com-hash",
            title="Community",
        )
        related = _doc(
            "Patience must prove hope when the answer is delayed and faith is tested.",
            source="giver.pdf",
            file_hash="giver-hash",
            title="The Giver and His Gifts",
        )
        query = "Give me a 3 point sermon on faith"
        selected = select_diverse_docs(
            [(community, 0.94), (faith, 0.71), (related, 0.80)],
            k=6,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["file_hash"],
            query=query,
            pin_query=query,
            catalog_source_keys=["faith-hash"],
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertIn("faith.pdf", sources)
        self.assertIn("giver.pdf", sources)
        self.assertNotIn("community.pdf", sources)

    def test_major_sources_prefer_thesis_windows_over_community(self):
        faith = _doc(
            "Faith must refuse the if factor of doubt and see the unseen promise.",
            source="hope.pdf",
            file_hash="hope-hash",
            title="Prisoners of Hope",
        )
        community = _doc(
            "Faith and hope show up in community life together as we love one another.",
            source="community.pdf",
            file_hash="com-hash",
            title="Community",
        )
        keys = select_major_source_keys(
            [(community, 0.94), (faith, 0.71)],
            "Give me a 3 point sermon on faith",
            source_key=lambda doc: doc.metadata["file_hash"],
            is_bible=lambda doc: False,
            limit=2,
        )
        self.assertEqual(keys[0], "hope-hash")
        self.assertNotIn("com-hash", keys)


class FaithClaimDistinctiveTests(unittest.TestCase):
    def test_three_point_faith_keeps_faith_not_sermon_discussion(self):
        tokens = query_topic_tokens("Give me a 3 point sermon on faith")
        distinctive = distinctive_query_tokens(tokens)
        self.assertIn("faith", distinctive)
        self.assertNotIn("sermon", distinctive)
        self.assertNotIn("point", distinctive)

        docs = [
            SimpleNamespace(
                page_content=(
                    "Small groups offer a space where members can discuss the Sunday sermon, "
                    "share spiritual battles, or simply pray together."
                ),
                metadata={"source": "groups.pdf", "chunk_kind": "sermon_quote"},
            ),
            SimpleNamespace(
                page_content=(
                    "Faith must refuse the if factor of doubt and receive what God promised."
                ),
                metadata={"source": "faith.pdf", "chunk_kind": "sermon_quote"},
            ),
        ]
        claims = extract_teaching_claims(docs, query="Give me a 3 point sermon on faith")
        blob = " ".join(claims).lower()
        self.assertIn("if factor", blob)
        self.assertNotIn("sunday sermon", blob)


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
