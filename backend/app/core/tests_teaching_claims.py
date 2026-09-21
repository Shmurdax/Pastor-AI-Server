import unittest
from types import SimpleNamespace

from core.teaching_claims import (
    claim_is_covered,
    claim_matches_query,
    claim_repair_steer,
    extract_teaching_claims,
    format_teaching_claims_block,
    keep_note_paraphrase_sentences,
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
        self.assertIn("only ideas you may teach", block)
        self.assertIn("not a license to invent a new outline", block)
        self.assertIn("covenant", block)
        self.assertIn("Do not replace them with generic Christian topics", block)
        self.assertIn("same thesis", block)
        self.assertIn("LGBTQ inclusion frame", block)
        self.assertIn("Romans 14 liberty", block)
        steer = claim_repair_steer(claims)
        self.assertIn("do not restart", steer.lower())
        self.assertIn("let's continue", steer.lower())
        self.assertIn("covenant", steer)
        self.assertIn("same thesis", steer)
        self.assertEqual(format_teaching_claims_block([]), "")

    def test_generation_user_prompt_locks_drink_and_gay_theses(self):
        from core.teaching_claims import format_generation_user_prompt

        drink = format_generation_user_prompt(
            "Can Christians drink?",
            [
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian.",
                "Alcoholism is a sin; it is not a sickness or a disease!",
            ],
        )
        self.assertIn("Can Christians drink?", drink)
        self.assertIn("only acceptable way", drink)
        self.assertIn("Alcoholism is a sin", drink)
        self.assertIn("Romans 14 liberty", drink)
        self.assertIn("Do not say drinking is a personal decision", drink)

        gay = format_generation_user_prompt(
            "Can gay people be Christians?",
            [
                "We must love the homosexual but we are to stand firmly against the lifestyle.",
            ],
        )
        self.assertIn("stand firmly", gay)
        self.assertIn("LGBTQ inclusion", gay)
        self.assertIn("Mark 12", gay)

        empty = format_generation_user_prompt("Can Christians drink?", [])
        self.assertIn("did not yield teaching points", empty)
        self.assertIn("Do not answer from general Christian knowledge", empty)

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

    def test_gay_query_extracts_christian_boundaries_application_theses(self):
        notes = (
            "lifestyle open themselves up to twenty three additional sinful practices.: "
            "“…unrighteousness, sexual immorality, wickedness, covetousness, maliciousness; "
            "full of envy, murder, strife, deceit, evil-mindedness; they are whisperers, "
            "30backbiters, haters of God, violent, proud, boasters, inventors of evil things, "
            "disobedient to parents, 31undiscerning, untrustworthy, unloving, unforgiving, "
            "unmerciful.” This explains why the modern day homosexual agenda is filled with "
            "venom toward anyone who dares to speak out against such a lifestyle. It seems "
            "that very few people who practice a homosexual lifestyle are capable of allowing "
            "the sin to be spoken of without internalizing it and making it personal. Just "
            "because I choose to speak out against alcoholism does not mean I do not respect "
            "or care for the alcoholic. Preaching this sermon does not mean I hate homosexuals, "
            "I am merely saying this is not an acceptable lifestyle according to natural law "
            "and the law of God. • In verse thirty two, Paul lets us know, those who practice "
            "such a lifestyle are deserving of death… He also tells us, those who approve such "
            "a lifestyle are worthy of the same penalty. What does he mean by “those who approve "
            "them”? Those who accept this kind of a lifestyle as normal; those who encourage "
            "others to follow such a pattern; those who push legislation to legalize it; those "
            "who vote for those who vote to legalize it; those who watch it in the privacy of "
            "their own bedroom; those who watch it at the theatre or bring it into their home! "
            "Before anyone cocks a gun to carry out the punishment of God upon those who "
            "practice a homosexual lifestyle, let me remind us, life is precious in the sight "
            "of God and God alone has the authority to give or take life; judgment is not ours, "
            "it is Gods; we must love the homosexual but we are to stand firmly against the "
            "lifestyle which they have chosen to embrace. Before any of us get rocks out to "
            "stone the homosexuals, let me remind us, the same Bible which pronounces judgment "
            "upon the sin of the homosexual, pronounces judgment upon the sin of the fornicator; "
            "the adulterer; the"
        )
        docs = [
            _doc(
                notes,
                source="christian-boundaries.pdf",
                title="Christian Boundaries",
                chunk_kind="sermon_quote",
            )
        ]
        claims = extract_teaching_claims(docs, query="Can gay people be Christians?")
        blob = " ".join(claims).lower()
        self.assertTrue(claims, claims)
        self.assertIn("not an acceptable lifestyle", blob)
        self.assertIn("natural law", blob)
        self.assertIn("love the homosexual", blob)
        self.assertIn("stand firmly", blob)
        self.assertTrue("approve" in blob or "lifestyle as normal" in blob, claims)
        self.assertTrue(
            any("lifestyle as normal" in item.lower() for item in claims)
            or any("those who approve" in item.lower() for item in claims),
            claims,
        )
        self.assertIn("stone", blob)
        self.assertIn("fornicator", blob)
        self.assertNotIn("unrighteousness", blob)
        self.assertNotIn("evil-mindedness", blob)
        self.assertTrue(
            any("love the homosexual" in item.lower() and "stand firmly" in item.lower() for item in claims),
            claims,
        )

    def test_skips_deck_junk_kjv_and_stat_slides(self):
        docs = [
            _doc(
                "LEAVE ON THE SCREEN until the next point is taught.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "3.5% of all wine in America is consumed by civic leaders every year.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "Wine is a mocker, strong drink is a brawler, and whoever is led astray by it is not wise.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "Total abstinence from alcoholic beverages is the only acceptable way of "
                "life for the Christian.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "Total abstinence from alcoholic beverages is the only acceptable "
                    "way of life for the Christian."
                ),
            ),
        ]
        claims = extract_teaching_claims(docs, query="Can Christians drink?")
        blob = " ".join(claims).lower()
        self.assertIn("abstinence", blob)
        self.assertNotIn("leave on the screen", blob)
        self.assertNotIn("3.5%", blob)
        self.assertNotIn("civic leaders", blob)
        self.assertNotIn("wine is a mocker", blob)

    def test_loose_overlap_does_not_cover_abstinence_thesis(self):
        claim = (
            "Total abstinence from alcoholic beverages is the only acceptable way "
            "of life for the Christian."
        )
        loose = "Abstinence from alcohol aligns closely with a wise Christian lifestyle."
        self.assertFalse(claim_is_covered(claim, loose))
        kept = (
            "The boundary a Christian should set is total abstinence from alcoholic beverages."
        )
        self.assertTrue(claim_is_covered(claim, kept))

    def test_strips_inclusive_and_hedging_sentences_not_in_notes(self):
        from core.teaching_claims import (
            keep_note_paraphrase_sentences,
            notes_only_from_claims,
            paraphrase_too_thin,
        )

        gay_docs = [
            _doc(
                "We love and accept the sinner but refuse to accept a sinful lifestyle. "
                "We love the sinner but we will not bless the sin.",
                source="boundaries.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "We love and accept the sinner but refuse to accept a sinful lifestyle."
                ),
            )
        ]
        gay_claims = [
            "We love and accept the sinner but refuse to accept a sinful lifestyle.",
            "We love the sinner but we will not bless the sin.",
        ]
        gay_answer = (
            "LGBTQ+ people can find acceptance and salvation in the church including sexual orientation. "
            "Christians should love the sinner and refuse a sinful lifestyle."
        )
        gay_kept = keep_note_paraphrase_sentences(
            gay_answer, sermon_docs=gay_docs, claims=gay_claims
        )
        self.assertNotIn("LGBTQ", gay_kept)
        self.assertNotIn("sexual orientation", gay_kept.lower())
        self.assertIn("sinful lifestyle", gay_kept.lower())

        drink_docs = [
            _doc(
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian. Alcoholism is a sin; it is not a sickness "
                "or a disease!",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "Total abstinence from alcoholic beverages is the only acceptable "
                    "way of life for the Christian."
                ),
            )
        ]
        drink_claims = [
            "Total abstinence from alcoholic beverages is the only acceptable way of "
            "life for the Christian."
        ]
        drink_answer = (
            "Christians should consider the risks and drink in moderation if they choose. "
            "The boundary a Christian should set is total abstinence from alcoholic beverages."
        )
        drink_kept = keep_note_paraphrase_sentences(
            drink_answer, sermon_docs=drink_docs, claims=drink_claims
        )
        self.assertNotIn("moderation", drink_kept.lower())
        self.assertNotIn("consider the risks", drink_kept.lower())
        self.assertIn("abstinence", drink_kept.lower())
        self.assertFalse(paraphrase_too_thin(drink_kept, drink_claims))

        invented = (
            'Pastor Don Nordin teaches, "Wine is a mocker, strong drink is a brawler, '
            'and whoever is led astray by it is not wise." '
            "Some churches welcome every identity equally."
        )
        stripped = keep_note_paraphrase_sentences(
            invented, sermon_docs=drink_docs, nkjv_docs=[], claims=drink_claims
        )
        self.assertNotIn("Wine is a mocker", stripped)
        self.assertNotIn("every identity", stripped.lower())
        self.assertTrue(paraphrase_too_thin(stripped, drink_claims))
        fallback = notes_only_from_claims(drink_claims)
        self.assertIn("abstinence", fallback.lower())
        self.assertNotIn("Wine is a mocker", fallback)

    def test_stat_slides_are_not_allowed_ideas(self):
        from core.teaching_claims import allowed_idea_texts, thesis_sentences_from_docs

        docs = [
            _doc(
                "3.5% of all wine in America is consumed by civic leaders every year. "
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        theses = thesis_sentences_from_docs(docs)
        blob = " ".join(theses).lower()
        self.assertIn("abstinence", blob)
        self.assertNotIn("3.5%", blob)
        self.assertNotIn("civic leaders", blob)
        allowed = " ".join(allowed_idea_texts(docs, theses)).lower()
        self.assertNotIn("3.5%", allowed)

    def test_seminar_extras_are_replaced_with_note_theses(self):
        from core.teaching_claims import ground_to_note_paraphrase

        docs = [
            _doc(
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian. Alcoholism is a sin; it is not a sickness "
                "or a disease!",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "Total abstinence from alcoholic beverages is the only acceptable "
                    "way of life for the Christian."
                ),
            )
        ]
        claims = [
            "Total abstinence from alcoholic beverages is the only acceptable way of "
            "life for the Christian."
        ]
        seminar = (
            "Based on the teachings referenced, Christians are encouraged to practice "
            "total abstinence from alcohol. "
            "Theological Foundations: The Bible provides guidance through numerous verses "
            "that warn against the dangers of alcohol. "
            "Historical Context: Ancient wine in biblical times was non-alcoholic or "
            "significantly diluted. "
            "Practical Considerations: Given fatalities from drunk driving, increased "
            "risk of violence, adhering to a policy of total abstinence aligns with "
            "protecting oneself. "
            "Community Impact: Practicing total abstinence helps create a community "
            "environment fostering a supportive atmosphere for all members."
        )
        grounded = ground_to_note_paraphrase(
            seminar, sermon_docs=docs, claims=claims
        )
        lowered = grounded.lower()
        self.assertNotIn("theological foundations", lowered)
        self.assertNotIn("historical context", lowered)
        self.assertNotIn("supportive atmosphere", lowered)
        self.assertNotIn("diluted", lowered)
        self.assertIn("abstinence", lowered)
        self.assertNotIn("practical considerations", lowered)
        self.assertNotIn("fatalities", lowered)
        self.assertNotIn("drunk driving", lowered)

    def test_repeating_thesis_words_does_not_keep_new_outline(self):
        from core.teaching_claims import sentence_idea_is_in_notes

        claim = (
            "Total abstinence from alcoholic beverages is the only acceptable way "
            "of life for the Christian."
        )
        hay = claim.lower()
        self.assertTrue(
            sentence_idea_is_in_notes(
                "The boundary a Christian should set is total abstinence from alcoholic beverages.",
                hay,
                [claim],
            )
        )
        self.assertFalse(
            sentence_idea_is_in_notes(
                "Adhering to a policy of total abstinence from alcoholic beverages "
                "helps create a supportive atmosphere for all members.",
                hay,
                [claim],
            )
        )

    def test_query_fallback_skips_off_topic_theses(self):
        from core.teaching_claims import resolve_teaching_claims

        docs = [
            _doc(
                "Happy people should walk in the Fruit of the Spirit and keep a merry heart.",
                source="happiness.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            ),
        ]
        drink = resolve_teaching_claims(docs, query="Can Christians drink alcohol?")
        blob = " ".join(drink).lower()
        self.assertIn("abstinence", blob)
        self.assertNotIn("merry heart", blob)
        self.assertNotIn("fruit of the spirit", blob)

    def test_continuation_extra_without_notes_is_dropped(self):
        docs = [
            _doc(
                "We love and accept the sinner but refuse to accept a sinful lifestyle.",
                source="boundaries.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        claims = [
            "We love and accept the sinner but refuse to accept a sinful lifestyle."
        ]
        extra = (
            "Community Impact: this also fosters a supportive atmosphere for all members "
            "including every identity in the church."
        )
        kept = keep_note_paraphrase_sentences(
            extra, sermon_docs=docs, claims=claims
        )
        self.assertEqual(kept, "")

    def test_joined_note_completion_stays_and_seminar_does_not(self):
        from core.teaching_claims import keep_note_paraphrase_sentences

        docs = [
            _doc(
                "Total abstinence from alcoholic beverages is the only acceptable way "
                "of life for the Christian.",
                source="sippin.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        claims = [
            "Total abstinence from alcoholic beverages is the only acceptable way of "
            "life for the Christian."
        ]
        joined = (
            "Total abstinence from alcoholic beverages is the only acceptable way "
            "of life for the Christian."
        )
        kept = keep_note_paraphrase_sentences(
            joined, sermon_docs=docs, claims=claims, query="Can Christians drink?"
        )
        self.assertIn("abstinence", kept.lower())
        self.assertIn("alcoholic beverages", kept.lower())
        seminar_join = (
            "The boundary a Christian should set is total abstinence from alcoholic "
            "beverages. Community Impact: this also fosters a supportive atmosphere "
            "for all members including every identity in the church."
        )
        kept_seminar = keep_note_paraphrase_sentences(
            seminar_join, sermon_docs=docs, claims=claims, query="Can Christians drink?"
        )
        self.assertIn("abstinence", kept_seminar.lower())
        self.assertNotIn("supportive atmosphere", kept_seminar.lower())
        self.assertNotIn("every identity", kept_seminar.lower())


if __name__ == "__main__":
    unittest.main()
