import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.chat_retrieval import (
    bible_book_key,
    expand_search_queries,
    extract_used_quotes,
    extract_used_verse_refs,
    format_reference_notes,
    is_bible_source,
    looks_like_followup,
    merge_scored_hits,
    search_queries_on_store,
    select_diverse_docs,
    uniqueness_instruction,
)


def _doc(text, *, source, file_hash=None, title=None):
    return SimpleNamespace(
        page_content=text,
        metadata={
            "source": source,
            "file_hash": file_hash or source,
            "title": title or source,
        },
    )


class ChatRetrievalTests(unittest.TestCase):
    def test_followup_query_includes_prior_turn(self):
        queries = expand_search_queries(
            "Can you further clarify that guidance?",
            ["What should I say to someone who is gay?"],
        )
        joined = " | ".join(queries).lower()
        self.assertIn("gay", joined)
        self.assertTrue(any("clarify" in item.lower() for item in queries))
        self.assertGreaterEqual(len(queries), 2)

    def test_followup_query_uses_prior_ai_steps(self):
        queries = expand_search_queries(
            "Can you further clarify those steps?",
            ["What should I say to someone who is gay?"],
            prior_ai_texts=[
                "Pastor Don Nordin teaches compassion.\n\n"
                "**Affirm Their Worth**\n"
                "**Express Care**\n"
                "**Offer Truth**\n"
                "Genesis 1:27 shows every person bears God's image."
            ],
            limit=5,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("gay", joined)
        self.assertTrue(
            any("affirm" in item.lower() or "worth" in item.lower() for item in queries),
            queries,
        )

    def test_first_turn_adds_keyword_and_sermon_query(self):
        queries = expand_search_queries("What should I say to someone who is gay?")
        self.assertEqual(queries[0], "What should I say to someone who is gay?")
        self.assertTrue(any("gay" in item.lower() and "pastor don" in item.lower() for item in queries))

    def test_looks_like_followup(self):
        self.assertTrue(looks_like_followup("Can you further clarify that guidance?"))
        self.assertTrue(looks_like_followup("What do you mean?"))
        self.assertFalse(looks_like_followup(
            "If a teenager in the youth group comes out, what would this pastor say to the student?"
        ))

    def test_uniqueness_followup_stays_on_topic(self):
        text = uniqueness_instruction(
            ['We love and accept the sinner but refuse to accept a sinful lifestyle.'],
            ["Genesis 1:27"],
            is_followup=True,
            prior_user_query="What should I say to someone who is gay?",
        )
        self.assertIn("SAME chat", text)
        self.assertIn("gay", text.lower())
        self.assertIn("do not switch to an unrelated sermon theme", text.lower())
        self.assertIn("Genesis 1:27", text)

    def test_extracts_quotes_and_ezekiel_verse(self):
        answer = (
            'As Pastor Don Nordin teaches, "I am not sure how the term ‘Gay’ became part of the lexicon" '
            "and remember, “the soul that sins shall surely die” (Ezekiel 18:4 NKJV)."
        )
        quotes = extract_used_quotes([answer])
        verses = extract_used_verse_refs([answer])
        self.assertTrue(any("lexicon" in item.lower() for item in quotes))
        self.assertTrue(any(item.lower().startswith("ezekiel 18:4") for item in verses))

    def test_select_diverse_docs_spreads_sources(self):
        scored = [
            (_doc("gay identity teaching from sermon A " * 8, source="sermon-a.pdf"), 0.92),
            (_doc("more gay identity from sermon A " * 8, source="sermon-a.pdf"), 0.91),
            (_doc("still more sermon A overlap " * 8, source="sermon-a.pdf"), 0.90),
            (_doc("compassion and truth from sermon B " * 8, source="sermon-b.pdf"), 0.80),
            (_doc("parenting wisdom from sermon C " * 8, source="sermon-c.pdf"), 0.78),
            (_doc("Ezekiel 18:4 the soul who sins shall die", source="nkjv-bible.pdf"), 0.88),
            (_doc("John 3:16 for God so loved the world", source="nkjv-bible.pdf"), 0.70),
            (_doc("Romans 1:16 the gospel is the power of God", source="nkjv-bible.pdf"), 0.66),
        ]
        selected = select_diverse_docs(
            scored,
            k=6,
            bible_ratio=0.45,
            max_per_source=2,
            max_per_bible_book=1,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertLessEqual(sources.count("sermon-a.pdf"), 2)
        self.assertIn("sermon-b.pdf", sources)
        self.assertIn("sermon-c.pdf", sources)
        books = [bible_book_key(doc.page_content) for doc in selected if is_bible_source(doc.metadata["source"])]
        self.assertEqual(len(books), len(set(books)))

    def test_novelty_skips_already_quoted_chunk_when_alternatives_exist(self):
        used_quote = "I am not sure how the term Gay became part of the lexicon"
        used_verse = "Ezekiel 18:4"
        scored = [
            (
                _doc(
                    f'Pastor Don said "{used_quote}" and cited {used_verse} the soul who sins.',
                    source="sermon-a.pdf",
                ),
                0.99,
            ),
            (_doc("A different pastoral line about compassion and holy living.", source="sermon-b.pdf"), 0.70),
            (_doc("John 8:11 go and sin no more teaching from the notes.", source="nkjv-bible.pdf"), 0.68),
            (_doc("Romans 12:9 let love be without hypocrisy.", source="nkjv-bible.pdf"), 0.60),
        ]
        selected = select_diverse_docs(
            scored,
            k=3,
            bible_ratio=0.4,
            max_per_source=2,
            used_quotes=[used_quote],
            used_verses=[used_verse],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        texts = " ".join(doc.page_content for doc in selected)
        self.assertNotIn(used_quote, texts)
        self.assertNotIn("Ezekiel 18:4", texts)

    def test_format_notes_labels_sources(self):
        docs = [
            _doc("First chunk", source="love.pdf", title="Walking in Love"),
            _doc("Second chunk", source="nkjv-bible.pdf", title="NKJV Bible"),
        ]
        notes = format_reference_notes(docs, lambda doc: doc.metadata["title"], max_chars=4000)
        self.assertIn("[Note 1 | Walking in Love]", notes)
        self.assertIn("[Note 2 | NKJV Bible]", notes)
        self.assertIn("First chunk", notes)

    def test_uniqueness_instruction_lists_prior_material(self):
        text = uniqueness_instruction(
            ['I am not sure how the term Gay became part of the lexicon'],
            ["Ezekiel 18:4"],
        )
        self.assertIn("<uniqueness>", text)
        self.assertIn("Ezekiel 18:4", text)
        self.assertIn("lexicon", text)
        self.assertIn("Do not restate the previous answer", text)

    def test_merge_scored_hits_keeps_best_duplicate(self):
        doc_a = _doc("same chunk text about mercy", source="a.pdf")
        doc_b = _doc("same chunk text about mercy", source="a.pdf")
        merged = merge_scored_hits([[(doc_a, 0.4)], [(doc_b, 0.9)]])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0][1], 0.9)

    def test_search_queries_on_store_runs_each_query(self):
        store = Mock()
        store.similarity_search_with_score.side_effect = [
            [(_doc("one", source="a.pdf"), 0.8)],
            [(_doc("two", source="b.pdf"), 0.7)],
        ]
        hits = search_queries_on_store(store, ["alpha", "beta"], k_per_query=8)
        self.assertEqual(store.similarity_search_with_score.call_count, 2)
        self.assertEqual(len(hits), 2)


if __name__ == "__main__":
    unittest.main()
