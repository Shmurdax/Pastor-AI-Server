import unittest
from types import SimpleNamespace

from core.notes_coverage import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    coverage_subject_tokens,
    focus_retrieved_notes,
    select_reference_notes,
    sermon_lines_for_answer,
)


def _doc(text, *, source="notes.pdf"):
    return SimpleNamespace(page_content=text, metadata={"source": source, "title": source})


class NotesCoverageTests(unittest.TestCase):
    def test_josephus_question_keeps_nearest_jesus_notes_as_partial(self):
        query = "Give me historical evidence outside of the Bible that Jesus is real"
        tomb = _doc(
            "The tomb was empty. Jesus is risen. Joseph of Arimathea buried the body.",
            source="cemetery.pdf",
        )
        dna = _doc(
            "Nowhere does the Bible try to prove the existence of God. In the beginning was the Word.",
            source="dna.pdf",
        )
        docs, coverage = select_reference_notes(
            query,
            [(tomb, 0.82), (dna, 0.71)],
            limit=24,
            min_score=0.12,
            partial_limit=8,
        )
        self.assertEqual(coverage, COVERAGE_PARTIAL)
        self.assertEqual(docs, [tomb, dna])
        self.assertTrue({"historical", "evidence"} <= coverage_subject_tokens(query))
        self.assertNotIn("outside", coverage_subject_tokens(query))
        self.assertNotIn("real", coverage_subject_tokens(query))

    def test_low_scores_go_silent_with_no_docs(self):
        filler = _doc("Announcements and next week's potluck.", source="bulletin.pdf")
        docs, coverage = select_reference_notes(
            "historical evidence outside of the Bible that Jesus is real",
            [(filler, 0.04)],
            min_score=0.12,
        )
        self.assertEqual(coverage, COVERAGE_NONE)
        self.assertEqual(docs, [])

    def test_faith_notes_are_full_coverage(self):
        query = "Sermon notes on faith"
        faith = _doc(
            "Faith without works is dead. Hold fast the confidence of your faith.",
            source="todo.pdf",
        )
        docs, coverage = select_reference_notes(query, [(faith, 0.91)])
        self.assertEqual(coverage, COVERAGE_FULL)
        self.assertEqual(docs, [faith])

    def test_tacitus_window_that_names_the_subject_is_full(self):
        query = "Give me historical evidence outside of the Bible that Jesus is real"
        tacitus = _doc(
            "The historian Tacitus wrote historical evidence that Nero murdered Christians.",
            source="table.pdf",
        )
        docs, coverage = select_reference_notes(query, [(tacitus, 0.88)])
        self.assertEqual(coverage, COVERAGE_FULL)
        self.assertEqual(docs, [tacitus])

    def test_partial_trims_to_the_adjacent_limit(self):
        query = "historical evidence outside of the Bible"
        hits = [
            (_doc(f"Jesus rose from the dead window {index}.", source=f"s{index}.pdf"), 0.8 - index * 0.01)
            for index in range(12)
        ]
        docs, coverage = select_reference_notes(
            query,
            hits,
            limit=24,
            partial_limit=8,
        )
        self.assertEqual(coverage, COVERAGE_PARTIAL)
        self.assertEqual(len(docs), 8)

    def test_missing_scores_fail_open_instead_of_going_silent(self):
        faith = _doc("Faith comes by hearing the word of God.", source="faith.pdf")
        docs, coverage = select_reference_notes("sermon notes on faith", [(faith, 0.0)])
        self.assertEqual(coverage, COVERAGE_FULL)
        self.assertEqual(docs, [faith])

    def test_empty_hits_are_none(self):
        docs, coverage = select_reference_notes("historical evidence", [])
        self.assertEqual(coverage, COVERAGE_NONE)
        self.assertEqual(docs, [])


class FocusRetrievedNotesTests(unittest.TestCase):
    def test_goliath_keeps_the_sermon_that_teaches_it(self):
        stuff = _doc(
            "David was anointed by Samuel. He once fought Goliath. "
            "Then he fled to Ziklag and wanted his stuff back.",
            source="stuff.pdf",
        )
        giants = _doc(
            "Goliath is the giant of the untamed tongue. David faced Goliath "
            "for forty days. The tongue is a giant like Goliath. "
            "Keys to victory over Goliath start with the words we speak.",
            source="giants.pdf",
        )
        generation = _doc(
            "David killed Goliath, then sinned with Bathsheba. "
            "Family and friends, trusted advisors, mighty men, and the arsenal "
            "supported the next generation.",
            source="generation.pdf",
        )
        kept = focus_retrieved_notes(
            "Tell the story of David and Goliath the way the sermon notes teach it.",
            [stuff, generation, giants],
        )
        self.assertEqual(kept, [giants])

    def test_marriage_prefers_the_marriage_sermon_over_church_covenant(self):
        church = _doc(
            "Covenant means we are in covenant with one another in the body of Christ. "
            "A culture of covenant brings people to Jesus. Covenant relationships serve.",
            source="covenant.pdf",
        )
        home = _doc(
            "Both the husband and the wife have needs that should be fulfilled inside "
            "their marriage. Withholding is sinning against God, the marriage covenant, "
            "and their mate. When one marries they forfeit control of their body.",
            source="home.pdf",
        )
        kept = focus_retrieved_notes(
            "Create sermon notes on marriage as a blood covenant. "
            "What does Pastor Don teach a husband and wife to do?",
            [church, home],
        )
        self.assertEqual(kept, [home])

    def test_drink_prefers_alcohol_notes_over_communion(self):
        table = _doc(
            "Come to the Lord's table and drink from the cup. Eat the bread and remember.",
            source="communion.pdf",
        )
        sippin = _doc(
            "Total abstinence from alcoholic beverages is the only acceptable way. "
            "Alcoholism is a sin, not a sickness. A Christian should not drink alcohol.",
            source="sippin.pdf",
        )
        kept = focus_retrieved_notes(
            "According to the sermon notes, can a Christian drink alcohol?",
            [table, sippin],
        )
        self.assertEqual(kept, [sippin])

    def test_same_instruction_shape_is_not_required_for_focus(self):
        faith = _doc(
            "Faith must refuse the if factor of doubt and receive what God promised.",
            source="faith.pdf",
        )
        groups = _doc(
            "Small groups discuss the Sunday sermon after church.",
            source="groups.pdf",
        )
        story = focus_retrieved_notes("Tell the story of faith from the sermon notes.", [groups, faith])
        question = focus_retrieved_notes("What do the notes teach about faith?", [groups, faith])
        self.assertEqual(story, [faith])
        self.assertEqual(question, [faith])

    def test_sermon_lines_keep_the_goliath_point_in_order(self):
        giants = _doc(
            "David faced giants. David is our template. David trusted God when he was afraid. "
            "The name Goliath means to reveal or advertise in a disgraceful sense. "
            "What weapon did Goliath use against the men of Israel? Words! "
            "Goliath is the giant of the untamed tongue. "
            "The only way we can tame the tongue is through the power of God. "
            "David later fled to Ziklag and wanted his stuff back.",
            source="giants.pdf",
        )
        lines = sermon_lines_for_answer(
            "Tell the story of David and Goliath the way the sermon notes teach it.",
            [giants],
        )
        self.assertIn("untamed tongue", lines)
        self.assertIn("power of God", lines)
        self.assertLess(lines.find("name Goliath"), lines.find("untamed tongue"))
        self.assertLess(lines.find("untamed tongue"), lines.find("power of God"))
