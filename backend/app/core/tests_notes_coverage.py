import unittest
from types import SimpleNamespace

from core.notes_coverage import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    coverage_subject_tokens,
    select_reference_notes,
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
