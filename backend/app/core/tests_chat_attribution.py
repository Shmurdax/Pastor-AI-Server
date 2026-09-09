import unittest

from .chat_attribution import (
    attribution_lock_instruction,
    distinctive_query_terms,
    docs_matching_asked_terms,
    unmentioned_claim_terms,
)


class _Doc:
    def __init__(self, text):
        self.page_content = text


class ChatAttributionTests(unittest.TestCase):
    QUERY = "What did the pastor think of the Council of Nicaea’s use of homoousios?"
    UNRELATED = (
        "Pastor Don Nordin teaches, \"Guard sound doctrine and feed the flock.\" "
        "Paul told Timothy to use a little wine for his stomach. "
        "Stay with the Word and do not chase every new idea."
    )
    MATCHING = (
        "At Nicaea the church confessed that the Son is homoousios with the Father, "
        "of one substance, fully God."
    )

    def test_extracts_nicaea_and_homoousios(self):
        terms = [t.casefold() for t in distinctive_query_terms(self.QUERY)]
        self.assertTrue(any("homoousios" in t for t in terms))
        self.assertTrue(any("nicaea" in t for t in terms))

    def test_unrelated_timothy_notes_do_not_cover_homoousios(self):
        missing = [t.casefold() for t in unmentioned_claim_terms(self.QUERY, self.UNRELATED)]
        self.assertIn("homoousios", missing)
        self.assertTrue(any("nicaea" in t for t in missing))

    def test_lock_forbids_according_to_pastor_don_on_missing_terms(self):
        lock = attribution_lock_instruction(self.QUERY, self.UNRELATED)
        self.assertIn("homoousios", lock)
        self.assertIn("According to Pastor Don", lock)
        self.assertIn("Do not say Pastor Don", lock)
        self.assertNotIn("According to Pastor Don Nordin, this term was crucial", lock)

    def test_no_lock_when_notes_contain_the_term(self):
        self.assertEqual(attribution_lock_instruction(self.QUERY, self.MATCHING), "")

    def test_hides_sermon_sources_that_never_mention_the_term(self):
        docs = [_Doc(self.UNRELATED), _Doc(self.MATCHING)]
        matched = docs_matching_asked_terms(docs, self.QUERY)
        self.assertEqual(len(matched), 1)
        self.assertIn("homoousios", matched[0].page_content)

    def test_empty_sources_when_nothing_mentions_the_term(self):
        docs = [_Doc(self.UNRELATED)]
        self.assertEqual(docs_matching_asked_terms(docs, self.QUERY), [])

    def test_ordinary_church_question_does_not_lock(self):
        query = "According to Pastor Don's sermons, what is the main purpose of the church?"
        notes = "Pastor Don Nordin teaches, \"The main purpose of the church is to make disciples.\""
        self.assertEqual(distinctive_query_terms(query), [])
        self.assertEqual(attribution_lock_instruction(query, notes), "")
