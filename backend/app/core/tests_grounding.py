import unittest
from types import SimpleNamespace

from core.grounding import (
    collect_allowed_nkjv,
    collect_allowed_sermon_quotes,
    format_grounding_block,
    grounded_fallback_answer,
    lookup_nkjv_verses,
    verify_answer_grounding,
)


def _doc(text, **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class GroundingTests(unittest.TestCase):
    def test_collects_sermon_quotes_not_bible(self):
        docs = [
            _doc(
                'Pastor Don said, "Comfort the child and stay in the kitchen with them."',
                source="grief.pdf",
                chunk_kind="sermon_quote",
                quote_text="Comfort the child and stay in the kitchen with them.",
            ),
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            ),
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        self.assertTrue(any("Comfort the child" in item for item in quotes), quotes)
        self.assertFalse(any("broken heart" in item for item in quotes), quotes)
        nkjv = collect_allowed_nkjv(docs)
        self.assertEqual(nkjv[0][0], "Psalm 34:18")
        self.assertIn("broken heart", nkjv[0][1])

    def test_verify_rejects_invented_quote_and_verse(self):
        sermon = [
            _doc(
                'We sit with the grieving and we pray.',
                source="notes.pdf",
                chunk_kind="sermon_quote",
                quote_text="We sit with the grieving and we pray.",
            )
        ]
        nkjv = [
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            )
        ]
        bad = (
            'Pastor Don Nordin teaches, "Your dog is in dog heaven waiting for you." '
            'Jeremiah 9:24 (NKJV) says, "I am the Lord who invented this kitchen script."'
        )
        report = verify_answer_grounding(bad, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertFalse(report.ok)
        self.assertTrue(report.invented_quotes or report.invented_scripture or report.missing_nkjv_refs)

        good = (
            'Pastor Don Nordin teaches, "We sit with the grieving and we pray." '
            'Psalm 34:18 (NKJV) says, "The Lord is near to those who have a broken heart."'
        )
        ok = verify_answer_grounding(good, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertTrue(ok.ok, ok)

    def test_fallback_uses_only_allowed_lines(self):
        text = grounded_fallback_answer(
            ["We sit with the grieving and we pray."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        self.assertIn("We sit with the grieving", text)
        self.assertIn("Psalm 34:18", text)
        self.assertNotIn("dog heaven", text.lower())

    def test_lookup_uses_retrieved_docs_without_client(self):
        docs = [
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            )
        ]
        found = lookup_nkjv_verses(
            None,
            "sermon_brain",
            [("psalm", 34, 18)],
            retrieved_docs=docs,
        )
        self.assertEqual(len(found), 1)

    def test_grounding_block_lists_allowed_sources(self):
        block = format_grounding_block(
            ["Comfort the child and stay in the kitchen with them."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        self.assertIn("<quote_ids>", block)
        self.assertIn("{{Q1}}", block)
        self.assertIn("Comfort the child", block)
        self.assertIn("Psalm 34:18", block)


if __name__ == "__main__":
    unittest.main()
