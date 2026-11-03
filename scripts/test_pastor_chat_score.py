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


class CaseFileTests(unittest.TestCase):
    def test_case_file_is_one_conversation(self):
        turns = load_cases(CASES)
        self.assertGreaterEqual(len(turns), 12)
        ids = [turn["id"] for turn in turns]
        self.assertEqual(len(ids), len(set(ids)))
        anaphoric = [turn for turn in turns if turn["anaphoric"]]
        self.assertEqual(len(anaphoric), 2)
        drafts = [turn for turn in turns if turn["kind"] == "draft"]
        self.assertGreater(len(drafts), len(turns) // 2)
        self.assertIn("James 2", anaphoric[0]["must_mention"])


if __name__ == "__main__":
    unittest.main()
