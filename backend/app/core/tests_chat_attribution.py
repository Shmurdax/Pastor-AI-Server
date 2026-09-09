import unittest

from .chat_attribution import (
    attribution_lock_instruction,
    distinctive_query_terms,
    docs_for_response_sources,
    expand_retrieval_queries,
    related_topic_phrases,
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
        self.assertIn("related preaching", lock.lower())
        self.assertIn("word-for-word", lock.lower())
        self.assertIn("Trinity", lock)
        self.assertNotIn("According to Pastor Don Nordin, this term was crucial", lock)

    def test_no_lock_when_notes_contain_the_term(self):
        self.assertEqual(attribution_lock_instruction(self.QUERY, self.MATCHING), "")

    def test_prefers_chunks_that_name_the_term(self):
        docs = [_Doc(self.UNRELATED), _Doc(self.MATCHING)]
        matched = docs_for_response_sources(docs, self.QUERY)
        self.assertEqual(len(matched), 1)
        self.assertIn("homoousios", matched[0].page_content)

    def test_keeps_related_sources_when_the_exact_term_is_missing(self):
        docs = [_Doc(self.UNRELATED)]
        self.assertEqual(docs_for_response_sources(docs, self.QUERY), docs)

    def test_expands_retrieval_toward_trinity_and_deity(self):
        phrases = related_topic_phrases(self.QUERY)
        self.assertIn("Trinity", phrases)
        self.assertTrue(any("deity" in p.lower() or "fully god" in p.lower() for p in phrases))
        queries = expand_retrieval_queries(self.QUERY)
        self.assertGreaterEqual(len(queries), 2)
        self.assertIn("Trinity", queries[1])

    def test_ordinary_church_question_does_not_lock(self):
        query = "According to Pastor Don's sermons, what is the main purpose of the church?"
        notes = "Pastor Don Nordin teaches, \"The main purpose of the church is to make disciples.\""
        self.assertEqual(distinctive_query_terms(query), [])
        self.assertEqual(attribution_lock_instruction(query, notes), "")
