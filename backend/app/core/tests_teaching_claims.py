import unittest
from types import SimpleNamespace

from core.teaching_claims import (
    claim_is_covered,
    claim_matches_query,
    claim_repair_steer,
    extract_teaching_claims,
    format_teaching_claims_block,
    query_topic_tokens,
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

    def test_church_query_does_not_require_generic_church_sentences(self):
        query = "Why does Pastor Don say this church is a big deal?"
        tokens = query_topic_tokens(query)
        self.assertIn("deal", tokens)
        self.assertFalse(
            claim_matches_query(
                "The church should be a place of forgiveness, mercy, and harvest.",
                tokens,
            )
        )
        self.assertTrue(
            claim_matches_query(
                "This church is a big deal because gifts grow here for world evangelism.",
                tokens,
            )
        )
        docs = [
            _doc(
                "The church should be a place of forgiveness, mercy, restoration, and harvest.",
                source="community.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "This church is a big deal because natural and spiritual gifts grow here "
                "for world evangelism, not because it is a generic house of mercy.",
                source="this-church.pdf",
                chunk_kind="sermon_quote",
            ),
        ]
        claims = extract_teaching_claims(docs, query=query)
        blob = " ".join(claims).lower()
        self.assertIn("big deal", blob)
        self.assertNotIn("forgiveness", blob)

    def test_drink_query_claims_keep_alcohol_not_communion(self):
        query = "Can Christians drink?"
        tokens = query_topic_tokens(query)
        self.assertIn("alcohol", tokens)
        self.assertFalse(
            claim_matches_query(
                "A person should examine himself first, and only then drink from the cup.",
                tokens,
                query=query,
            )
        )
        self.assertTrue(
            claim_matches_query(
                "Alcoholism is a sin; it is not a sickness or a disease!",
                tokens,
                query=query,
            )
        )
        docs = [
            _doc(
                "A person should examine himself first, and only then eat the bread "
                "and drink from the cup at communion.",
                source="lords-table.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "A person should examine himself first, and only then eat the bread "
                    "and drink from the cup at communion."
                ),
            ),
            _doc(
                "Alcoholism is a sin; it is not a sickness or a disease! "
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian.",
                source="the-christian-and-alcohol.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "Alcoholism is a sin; it is not a sickness or a disease! "
                    "Total abstinence from alcoholic beverages is the only acceptable "
                    "way of life for the Christian."
                ),
            ),
        ]
        claims = extract_teaching_claims(docs, query=query)
        blob = " ".join(claims).lower()
        self.assertIn("alcoholism", blob)
        self.assertIn("abstinence", blob)
        self.assertNotIn("communion", blob)
        self.assertNotIn("cup", blob)

    def test_gay_query_claims_keep_sexuality_not_happiness(self):
        query = "Can gay people be Christians?"
        tokens = query_topic_tokens(query)
        self.assertIn("gay", tokens)
        self.assertIn("homosexuality", tokens)
        self.assertFalse(
            claim_matches_query(
                "HAPPY PEOPLE are those folks who know, and have confidence in their standing with GOD.",
                tokens,
                query=query,
            )
        )
        self.assertFalse(
            claim_matches_query(
                "The fruit of the Spirit is love, joy, peace, longsuffering, kindness, goodness, faithfulness.",
                tokens,
                query=query,
            )
        )
        self.assertTrue(
            claim_matches_query(
                "We love and accept the sinner but refuse to accept a sinful lifestyle.",
                tokens,
                query=query,
            )
        )
        self.assertTrue(
            claim_matches_query(
                "We love the sinner but we will not bless the sin.",
                tokens,
                query=query,
            )
        )
        docs = [
            _doc(
                "HAPPY PEOPLE are those folks who know, and have confidence in their standing with GOD. "
                "The fruit of the Spirit is love, joy, peace.",
                source="happiness.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "HAPPY PEOPLE are those folks who know, and have confidence in their standing with GOD."
                ),
            ),
            _doc(
                "We love and accept the sinner but refuse to accept a sinful lifestyle. "
                "We love the sinner but we will not bless the sin.",
                source="homosexuality.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "We love and accept the sinner but refuse to accept a sinful lifestyle. | "
                    "We love the sinner but we will not bless the sin."
                ),
            ),
        ]
        claims = extract_teaching_claims(docs, query=query)
        blob = " ".join(claims).lower()
        self.assertIn("sinful lifestyle", blob)
        self.assertIn("bless the sin", blob)
        self.assertNotIn("happy people", blob)
        self.assertNotIn("fruit of the spirit", blob)


if __name__ == "__main__":
    unittest.main()
