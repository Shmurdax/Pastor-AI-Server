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

    def test_illustration_only_rewrite_does_not_cover_thesis(self):
        claim = (
            "The whistle should mean the train is coming because the same power "
            "that blew the whistle will pull the train."
        )
        generic = (
            "Just as the whistle signals the arrival of a train, our faith should "
            "signal our readiness to serve and work together for God."
        )
        kept = (
            "The shout only counts if the same power that blew the whistle can "
            "also pull the train up the hill."
        )
        self.assertFalse(claim_is_covered(claim, generic))
        self.assertTrue(claim_is_covered(claim, kept))

    def test_prefers_contrast_thesis(self):
        docs = [
            _doc(
                "Faith is a powerful force that transforms lives and builds communities.",
                source="generic.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "The shout is only indicative of the power. The whistle should mean "
                "the train is coming because the same power that blew the whistle "
                "will pull the train.",
                source="fire.pdf",
                chunk_kind="sermon_quote",
            ),
        ]
        claims = extract_teaching_claims(docs, query="pull up a sermon about faith", limit=1)
        self.assertEqual(len(claims), 1)
        self.assertIn("same power", claims[0].lower())

    def test_block_and_repair_list_points(self):
        claims = ["Marriage is a covenant, not a contract."]
        block = format_teaching_claims_block(claims)
        self.assertIn("<required_teaching_points>", block)
        self.assertIn("generic Christian pastoral tone", block)
        self.assertIn("covenant", block)
        self.assertIn("Do not replace them with generic Christian topics", block)
        self.assertIn("same thesis", block)
        steer = claim_repair_steer(claims)
        self.assertIn("do not restart", steer.lower())
        self.assertIn("let's continue", steer.lower())
        self.assertIn("covenant", steer)
        self.assertIn("same thesis", steer)
        self.assertEqual(format_teaching_claims_block([]), "")

    def test_skips_memoir_and_off_topic_repair_for_faith_query(self):
        docs = [
            _doc(
                "Under their loving care and spiritual direction, I accepted Christ "
                "and received the baptism of the Holy Spirit with the initial physical "
                "evidence of speaking in tongues when I was 13 years old.",
                source="giver.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "It's funny when you're working on a sermon that late how you can't "
                "seem to find anything in the Bible to preach.",
                source="giver.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "Faith is a gift of the Spirit, and loving the Lord means we pursue "
                "the Giver and the gifts together.",
                source="giver.pdf",
                chunk_kind="sermon_quote",
            ),
        ]
        query = "tell me about faith and loving the lord"
        claims = extract_teaching_claims(docs, query=query)
        self.assertTrue(any("gift" in item.lower() for item in claims), claims)
        self.assertFalse(any("when i was 13" in item.lower() for item in claims), claims)
        self.assertFalse(any("sermon that late" in item.lower() for item in claims), claims)

        generic = (
            "Faith is trusting the Lord's promises, and loving the Lord means "
            "seeking him in worship, service, and obedience."
        )
        from core.teaching_claims import repairable_claims

        missing = repairable_claims(generic, claims, query=query)
        self.assertFalse(any("13" in item for item in missing), missing)
        self.assertFalse(any("sermon that late" in item.lower() for item in missing), missing)


if __name__ == "__main__":
    unittest.main()
