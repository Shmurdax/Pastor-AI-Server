import unittest
from types import SimpleNamespace

from core.teaching_claims import (
    claim_is_covered,
    claim_repair_steer,
    extract_teaching_claims,
    format_teaching_claims_block,
    uncovered_claims,
)


def _doc(text, **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class TeachingClaimTests(unittest.TestCase):
    def test_extracts_sermon_claims_not_bible(self):
        docs = [
            _doc(
                "Marriage is a covenant, not a contract, and God set the husband as head.",
                source="marriage.pdf",
                chunk_kind="sermon_quote",
                quote_text="Marriage is a covenant, not a contract.",
            ),
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                quote_text="The Lord is near to those who have a broken heart.",
            ),
        ]
        claims = extract_teaching_claims(docs, query="sermon series on marriage")
        self.assertTrue(any("covenant" in item.lower() for item in claims), claims)
        self.assertFalse(any("broken heart" in item.lower() for item in claims), claims)

    def test_prefers_topic_overlap(self):
        docs = [
            _doc(
                "Tithing opens the windows of heaven for the storehouse.",
                source="giving.pdf",
                chunk_kind="sermon_quote",
                quote_text="Tithing opens the windows of heaven for the storehouse.",
            ),
            _doc(
                "Marriage is a covenant, not a contract, ordained before roles of husband and wife.",
                source="marriage.pdf",
                chunk_kind="sermon_quote",
                quote_text="Marriage is a covenant, not a contract, ordained before roles of husband and wife.",
            ),
        ]
        claims = extract_teaching_claims(docs, query="expand week one of the marriage series", limit=1)
        self.assertEqual(len(claims), 1)
        self.assertIn("covenant", claims[0].lower())

    def test_generic_outline_does_not_cover_covenant_claim(self):
        claim = "Marriage is a covenant, not a contract, and the husband is the head."
        generic = (
            "Week 1\n"
            "- Commitment to God First\n"
            "- Communication\n"
            "- Conflict Resolution\n"
            "A strong marriage starts when both spouses put God first and talk openly."
        )
        self.assertFalse(claim_is_covered(claim, generic))
        self.assertEqual(uncovered_claims(generic, [claim]), [claim])

    def test_paraphrase_covers_claim(self):
        claim = "Marriage is a covenant, not a contract, and the husband is the head."
        paraphrase = (
            "The retrieved teaching presents marriage as a covenant rather than a contract, "
            "with the husband serving as head of the home."
        )
        self.assertTrue(claim_is_covered(claim, paraphrase))
        self.assertEqual(uncovered_claims(paraphrase, [claim]), [])

    def test_block_and_repair_list_points(self):
        claims = ["Marriage is a covenant, not a contract."]
        block = format_teaching_claims_block(claims)
        self.assertIn("<required_teaching_points>", block)
        self.assertIn("generic Christian pastoral tone", block)
        self.assertIn("covenant", block)
        self.assertIn("Do not replace them with generic Christian topics", block)
        steer = claim_repair_steer(claims)
        self.assertIn("without restarting", steer.lower())
        self.assertIn("covenant", steer)
        self.assertEqual(format_teaching_claims_block([]), "")


if __name__ == "__main__":
    unittest.main()
