import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.chat_retrieval import format_reference_notes
from core.notes_coverage import COVERAGE_FULL, COVERAGE_NONE, COVERAGE_PARTIAL
from core.scripture_support import (
    LANE_NKJV_FALLBACK,
    LANE_SERMON,
    attach_supporting_scripture,
    format_nkjv_scripture_block,
    is_bible_chunk,
    search_supporting_nkjv_verses,
    sermon_window_verse_refs,
)


def _doc(text, **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class ScriptureSupportTests(unittest.TestCase):
    def test_sermon_window_refs_come_from_chunk_text_not_catalog_index(self):
        sermon = _doc(
            "Faith is the substance of things hoped for. Hebrews 11:1 holds when the if factor comes.",
            source="faith-lift.pdf",
            title="Faith Lift",
            scripture_refs=[f"John 3:{n}" for n in range(1, 101)],
        )
        refs = sermon_window_verse_refs([sermon])
        self.assertEqual(refs, [("hebrews", 11, 1)])

    def test_chunk_verse_ref_counts_and_bible_chunks_do_not(self):
        sermon = _doc(
            "Stand when the pressure comes.",
            source="faith.pdf",
            verse_ref="Romans 10:17",
        )
        bible = _doc(
            "Now faith is the substance of things hoped for.",
            source="nkjv-bible.pdf",
            chunk_kind="bible_verse",
            verse_ref="Hebrews 11:1",
            book="hebrews",
            chapter=11,
            verse_start=1,
        )
        refs = sermon_window_verse_refs([sermon, bible])
        self.assertEqual(refs, [("romans", 10, 17)])
        self.assertTrue(is_bible_chunk(bible))
        self.assertFalse(is_bible_chunk(sermon))

    def test_greetings_and_empty_coverage_skip_scripture(self):
        sermon = _doc("Hebrews 11:1 is the definition of faith.", source="faith.pdf")
        lookup = Mock(return_value=[_doc("Now faith is.", source="nkjv.pdf", chunk_kind="bible_verse")])
        search = Mock(return_value=[_doc("Other verse.", source="nkjv.pdf", chunk_kind="bible_verse")])
        docs, lane = attach_supporting_scripture(
            "Hello how are you today?",
            [sermon],
            COVERAGE_FULL,
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual(docs, [])
        self.assertEqual(lane, "")
        lookup.assert_not_called()
        search.assert_not_called()

        docs, lane = attach_supporting_scripture(
            "What is faith?",
            [sermon],
            COVERAGE_NONE,
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual((docs, lane), ([], ""))
        lookup.assert_not_called()

    def test_named_sermon_refs_win_and_skip_fallback(self):
        sermon = _doc(
            "Pastor Don teaches from Hebrews 11:1 that faith refuses the if factor.",
            source="faith-lift.pdf",
        )
        nkjv = _doc(
            "Now faith is the substance of things hoped for.",
            source="nkjv-bible.pdf",
            chunk_kind="bible_verse",
            verse_ref="Hebrews 11:1",
            quote_text="Now faith is the substance of things hoped for.",
        )
        lookup = Mock(return_value=[nkjv])
        search = Mock(return_value=[_doc("unrelated", source="nkjv.pdf", chunk_kind="bible_verse")])
        docs, lane = attach_supporting_scripture(
            "Give me a sermon on faith",
            [sermon],
            COVERAGE_FULL,
            client=object(),
            collection_name="sermon_brain",
            embeddings=object(),
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual(lane, LANE_SERMON)
        self.assertEqual(docs, [nkjv])
        lookup.assert_called_once()
        args, kwargs = lookup.call_args
        self.assertEqual(args[2], [("hebrews", 11, 1)])
        self.assertIsNone(kwargs.get("retrieved_docs"))
        search.assert_not_called()

    def test_partial_coverage_without_refs_does_not_fallback(self):
        neighbor = _doc(
            "The tomb was empty. Jesus is risen. Joseph of Arimathea buried the body.",
            source="cemetery.pdf",
        )
        lookup = Mock()
        search = Mock(return_value=[_doc("Josephus is not here.", source="nkjv.pdf", chunk_kind="bible_verse")])
        docs, lane = attach_supporting_scripture(
            "Give me historical evidence outside of the Bible that Jesus is real",
            [neighbor],
            COVERAGE_PARTIAL,
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual((docs, lane), ([], ""))
        lookup.assert_not_called()
        search.assert_not_called()

    def test_full_coverage_without_refs_uses_nkjv_embedding_fallback(self):
        sermon = _doc(
            "Gratitude is a lifestyle of thanks before the breakthrough arrives.",
            source="gratitude.pdf",
        )
        nkjv = _doc(
            "In everything give thanks.",
            source="nkjv-bible.pdf",
            chunk_kind="bible_verse",
            verse_ref="1 Thessalonians 5:18",
            quote_text="In everything give thanks.",
        )
        lookup = Mock()
        search = Mock(return_value=[nkjv])
        docs, lane = attach_supporting_scripture(
            "sermon notes on gratitude",
            [sermon],
            COVERAGE_FULL,
            client=object(),
            collection_name="sermon_brain",
            embeddings=object(),
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual(lane, LANE_NKJV_FALLBACK)
        self.assertEqual(docs, [nkjv])
        lookup.assert_not_called()
        search.assert_called_once()

    def test_named_refs_with_empty_lookup_do_not_fallback(self):
        sermon = _doc("Hebrews 11:1 is the line Pastor Don keeps returning to.", source="faith.pdf")
        lookup = Mock(return_value=[])
        search = Mock(return_value=[_doc("other", source="nkjv.pdf", chunk_kind="bible_verse")])
        docs, lane = attach_supporting_scripture(
            "What is faith?",
            [sermon],
            COVERAGE_FULL,
            lookup=lookup,
            search_nkjv=search,
        )
        self.assertEqual((docs, lane), ([], ""))
        search.assert_not_called()

    def test_format_block_labels_nkjv_and_notes_keep_scripture_after_preface(self):
        nkjv = _doc(
            "# Hebrews 11\n\n1 Now faith is the substance of things hoped for.",
            source="nkjv-bible.pdf",
            chunk_kind="bible_verse",
            verse_ref="Hebrews 11:1",
            quote_text="Now faith is the substance of things hoped for.",
        )
        block = format_nkjv_scripture_block([nkjv])
        self.assertTrue(block.startswith("[NKJV SCRIPTURE]"))
        self.assertIn("Hebrews 11:1 (NKJV):", block)
        self.assertIn("Now faith is the substance", block)

        sermon = _doc("Faith refuses the if factor.", source="faith.pdf", title="Faith Lift")
        notes = format_reference_notes(
            [sermon],
            lambda doc: doc.metadata["title"],
            max_chars=4000,
            preserve_order=True,
            scripture_docs=[nkjv],
        )
        self.assertTrue(notes.startswith("These excerpts are Pastor Don Nordin's and Susan Nordin's"))
        self.assertLess(notes.index("[NKJV SCRIPTURE]"), notes.index("[Note 1 | Faith Lift]"))
        self.assertIn("Hebrews 11:1", notes)

    def test_empty_sermon_docs_still_have_no_notes_even_with_scripture(self):
        nkjv = _doc(
            "Now faith is.",
            source="nkjv.pdf",
            chunk_kind="bible_verse",
            verse_ref="Hebrews 11:1",
        )
        notes = format_reference_notes(
            [],
            lambda doc: "Unused",
            max_chars=4000,
            scripture_docs=[nkjv],
        )
        self.assertEqual(notes, "")

    def test_embedding_search_filters_bible_verse_and_drops_low_scores(self):
        class _Emb:
            def embed_query(self, text):
                self.seen = text
                return [0.1, 0.2]

        class _Client:
            def query_points(self, **kwargs):
                self.kwargs = kwargs
                strong = SimpleNamespace(
                    score=0.81,
                    payload={
                        "text": "In everything give thanks.",
                        "chunk_kind": "bible_verse",
                        "verse_ref": "1 Thessalonians 5:18",
                        "source": "nkjv-bible.pdf",
                        "metadata": {"chunk_kind": "bible_verse", "source": "nkjv-bible.pdf"},
                    },
                )
                weak = SimpleNamespace(
                    score=0.05,
                    payload={
                        "text": "And the evening and the morning were the first day.",
                        "chunk_kind": "bible_verse",
                        "verse_ref": "Genesis 1:5",
                        "source": "nkjv-bible.pdf",
                        "metadata": {"chunk_kind": "bible_verse"},
                    },
                )
                sermon = SimpleNamespace(
                    score=0.99,
                    payload={
                        "text": "A sermon window that leaked into bible search.",
                        "chunk_kind": "sermon_quote",
                        "source": "faith.pdf",
                        "metadata": {"chunk_kind": "sermon_quote", "source": "faith.pdf"},
                    },
                )
                return SimpleNamespace(points=[strong, weak, sermon])

        client = _Client()
        emb = _Emb()
        found = search_supporting_nkjv_verses(
            "sermon notes on gratitude",
            client,
            "sermon_brain",
            emb,
            rerank_hits=lambda query, hits, **kwargs: hits,
        )
        self.assertEqual(len(found), 1)
        self.assertIn("give thanks", found[0].page_content)
        self.assertEqual(client.kwargs["query_filter"].must[0].key, "chunk_kind")
        self.assertEqual(client.kwargs["query_filter"].must[0].match.value, "bible_verse")
        self.assertEqual(emb.seen, "sermon notes on gratitude")


if __name__ == "__main__":
    unittest.main()
