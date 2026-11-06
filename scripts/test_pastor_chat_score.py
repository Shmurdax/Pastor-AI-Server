#!/usr/bin/env python3
"""Unit checks for the pastor-chat scorer. No Django and no live model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from pastor_chat_score import (  # noqa: E402
    ACCURACY_FAIL_BELOW,
    grade_turn,
    load_cases,
    render_scorecard,
    score_reply,
)


CASES = Path(__file__).resolve().parent / "pastor_chat_cases.yaml"
PASSAGES = [
    {
        "title": "Why Receive the Holy Spirit",
        "text": (
            "Water baptism follows repentance. James 2 says faith without works "
            "is dead. John 3:16 is the promise of God's love."
        ),
    }
]


class ScoreReplyTests(unittest.TestCase):
    def test_supported_sentence_and_scripture_score_full(self):
        scored = score_reply(
            "Water baptism follows repentance. James teaches faith. John 3:16.",
            PASSAGES,
        )
        self.assertEqual(scored["accuracy"], 100)
        self.assertEqual(scored["missing_scripture"], [])
        self.assertEqual(scored["unsupported_sentences"], [])

    def test_invented_scripture_lowers_the_score(self):
        scored = score_reply(
            "Water baptism follows repentance. Revelation 22:21 closes the book.",
            PASSAGES,
        )
        self.assertIn("Revelation 22:21", scored["missing_scripture"])
        self.assertLess(scored["accuracy"], 100)
        self.assertGreater(scored["accuracy"], 0)

    def test_unsupported_sentence_is_listed(self):
        scored = score_reply(
            "The congregation should buy a fishing boat for the retreat.",
            PASSAGES,
        )
        self.assertEqual(scored["accuracy"], 0)
        self.assertEqual(len(scored["unsupported_sentences"]), 1)

    def test_empty_retrieval_rewards_a_gap_admission(self):
        scored = score_reply(
            "The notes do not cover this question.",
            [],
        )
        self.assertEqual(scored["accuracy"], 100)

    def test_empty_retrieval_rejects_a_specific_claim(self):
        scored = score_reply(
            "Baptism in the ocean saves every believer who attends.",
            [],
        )
        self.assertEqual(scored["accuracy"], 0)

    def test_heading_label_is_not_required_to_appear_in_the_excerpt(self):
        scored = score_reply(
            "Title: Water baptism follows repentance.",
            PASSAGES,
        )
        self.assertEqual(scored["unsupported_sentences"], [])
        self.assertEqual(scored["accuracy"], 100)


class GradeTurnTests(unittest.TestCase):
    def test_draft_missing_heading_fails_even_when_words_overlap(self):
        turn = {
            "kind": "draft",
            "expect_pipeline": "study_sermon_draft",
            "must_mention": ["baptism"],
            "must_not_mention": [],
        }
        graded = grade_turn(
            turn,
            "Water baptism follows repentance. John 3:16.",
            "study_sermon_draft",
            PASSAGES,
        )
        self.assertFalse(graded["pass"])
        self.assertTrue(any(reason.startswith("missing heading") for reason in graded["reasons"]))

    def test_accuracy_bar_fails_a_grounded_shape_with_outside_claims(self):
        turn = {
            "kind": "pastoral",
            "expect_pipeline": "pastoral_chat",
            "must_mention": ["baptism"],
            "must_not_mention": [],
        }
        answer = (
            "Water baptism follows repentance. "
            "The congregation should buy a fishing boat for the retreat. "
            "Revelation 22:21 closes the book."
        )
        graded = grade_turn(turn, answer, "pastoral_chat", PASSAGES)
        self.assertLess(graded["accuracy"], ACCURACY_FAIL_BELOW)
        self.assertFalse(graded["pass"])


class ScorecardTests(unittest.TestCase):
    def test_scorecard_includes_full_passing_and_failing_turns(self):
        passing_answer = "Grace is the full unearned gift in this passing answer."
        failing_answer = "The congregation should buy a fishing boat. Revelation 22:21."
        report = {
            "passed": 1,
            "total": 2,
            "session_id": "ai-testing-abc",
            "restored_active_session": "prior-chat",
            "turns": [
                {
                    "id": "grace_question",
                    "anaphoric": False,
                    "pass": True,
                    "accuracy": 100,
                    "pipeline": "pastoral_chat",
                    "query": "What does grace mean?",
                    "reasons": [],
                    "sources": ["Grace Notes"],
                    "passage_titles": ["Grace Notes"],
                    "unsupported_sentences": [],
                    "missing_scripture": [],
                    "answer": passing_answer,
                },
                {
                    "id": "baptism_sermon",
                    "anaphoric": True,
                    "pass": False,
                    "accuracy": 25,
                    "pipeline": "pastoral_chat",
                    "query": "Add a discussion question to that study",
                    "reasons": ["missing James 2"],
                    "sources": [],
                    "passage_titles": ["James Study"],
                    "unsupported_sentences": ["The congregation should buy a fishing boat."],
                    "missing_scripture": ["Revelation 22:21"],
                    "answer": failing_answer,
                },
            ],
        }
        text = render_scorecard(report)
        self.assertIn("grace_question", text)
        self.assertIn("baptism_sermon", text)
        self.assertIn("Accuracy: 100", text)
        self.assertIn("Accuracy: 25", text)
        self.assertIn(passing_answer, text)
        self.assertIn(failing_answer, text)
        self.assertIn("missing James 2", text)
        self.assertIn("The congregation should buy a fishing boat.", text)
        self.assertIn("Passed 1 of 2.", text)


class CaseFileTests(unittest.TestCase):
    def test_case_file_is_one_conversation(self):
        turns = load_cases(CASES)
        self.assertGreaterEqual(len(turns), 16)
        ids = [turn["id"] for turn in turns]
        self.assertEqual(len(ids), len(set(ids)))
        anaphoric = [turn for turn in turns if turn["anaphoric"]]
        self.assertGreaterEqual(len(anaphoric), 8)
        drafts = [turn for turn in turns if turn["kind"] == "draft"]
        self.assertGreater(len(drafts), len(turns) // 2)
        self.assertIn("James 2", anaphoric[0]["must_mention"])


if __name__ == "__main__":
    unittest.main()
