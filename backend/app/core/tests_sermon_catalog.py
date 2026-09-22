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
    pin_docs_to_strong_title_matches,
    query_focus_tokens,
    refine_major_source_keys,
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

    def test_abortion_promotes_teaching_file_without_title_words(self):
        query = "Can I have an abortion as a Christian?"
        focus = query_focus_tokens(query)
        self.assertIn("abortion", focus)
        self.assertNotIn("christian", focus)
        self.assertNotIn("have", focus)

        promise_windows = [
            (
                _doc(
                    "A believer must refuse abortion because that baby is a life God promised.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                0.74,
            ),
            (
                _doc(
                    "Webster defines abortion as the expulsion of the fetus, and abortionists call abortion a choice.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                0.70,
            ),
            (
                _doc(
                    "The embryo is a person, so believers should never treat abortion as disposable.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                0.69,
            ),
        ]
        titled = _doc(
            "Abortion shows up once in a list of social issues the church should notice.",
            source="society.pdf",
            file_hash="society-hash",
            title="Abortion and Society",
        )
        living = _doc(
            "Christians must walk by faith and refuse the wages of sin in the church.",
            source="hero.pdf",
            file_hash="hero-hash",
            title="Be a Hero",
        )
        keys = select_major_source_keys(
            [(living, 0.96), (titled, 0.93), *promise_windows],
            query,
            source_key=lambda doc: doc.metadata["file_hash"],
            is_bible=lambda doc: False,
            limit=3,
        )
        self.assertEqual(keys[0], "promise-hash")
        self.assertNotIn("hero-hash", keys)

        selected = select_diverse_docs(
            [(living, 0.96), (titled, 0.93), *promise_windows],
            k=4,
            bible_ratio=0.0,
            max_per_source=4,
            query=query,
            pin_query=query,
            is_bible=lambda doc: False,
            source_key=lambda doc: doc.metadata["file_hash"],
        )
        sources = [doc.metadata["file_hash"] for doc in selected]
        self.assertEqual(sources[0], "promise-hash")
        self.assertGreater(sources.count("promise-hash"), sources.count("society-hash"))
        self.assertNotIn("hero-hash", sources)
        pinned = pin_docs_to_strong_title_matches(
            selected,
            query,
            pin_query=query,
            candidate_hits=[(living, 0.96), (titled, 0.93), *promise_windows],
            is_bible=lambda doc: False,
            source_key=lambda doc: doc.metadata["file_hash"],
        )
        self.assertEqual(pinned[0].metadata["file_hash"], "promise-hash")

    def test_refine_uses_loaded_windows_when_title_shares_no_words(self):
        query = "Can I have an abortion as a Christian?"
        ann_promise = _doc(
            "A believer must refuse abortion because that baby is a life God promised.",
            source="promise.pdf",
            file_hash="promise-hash",
            title="Pregnant with a Promise",
        )
        titled = _doc(
            "Abortion shows up once in a list of social issues the church should notice.",
            source="society.pdf",
            file_hash="society-hash",
            title="Abortion and Society",
        )
        loaded = [
            (
                _doc(
                    "Parents must refuse abortion even when the pregnancy was a surprise promise.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                1.0,
            ),
            (
                _doc(
                    "The church should protect the fetus, and abortion is never the answer of faith.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                1.0,
            ),
            (
                _doc(
                    "Webster defines abortion as the expulsion of the fetus, and abortionists defend abortion.",
                    source="promise.pdf",
                    file_hash="promise-hash",
                    title="Pregnant with a Promise",
                ),
                1.0,
            ),
        ]
        keys = refine_major_source_keys(
            [(titled, 0.95), (ann_promise, 0.71)],
            query,
            source_key=lambda doc: doc.metadata["file_hash"],
            is_bible=lambda doc: False,
            file_windows=loaded,
            limit=2,
        )
        self.assertEqual(keys[0], "promise-hash")


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

    def test_outline_request_searches_the_topic_not_the_layout(self):
        from core.teaching_claims import retrieval_search_text

        self.assertEqual(
            retrieval_search_text("Give me a 3 point sermon on faith"),
            "faith",
        )
        self.assertEqual(
            retrieval_search_text("3 point sermon on faith"),
            "faith",
        )
        self.assertEqual(
            retrieval_search_text("Can Christians drink?"),
            "Can Christians drink?",
        )


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
