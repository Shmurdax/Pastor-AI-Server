import unittest
from types import SimpleNamespace

from core.grounding import (
    collect_allowed_nkjv,
    collect_allowed_sermon_quotes,
    grounded_fallback_answer,
    lookup_nkjv_verses,
    looks_like_heading_quote,
    strip_retrieval_meta,
    verify_answer_grounding,
    weave_into_answer,
)


def _doc(text, **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class GroundingTests(unittest.TestCase):
    def test_collects_sermon_quotes_not_bible(self):
        docs = [
            _doc(
                'Pastor Don said, "Comfort the child and stay in the kitchen with them."',
                source="grief.pdf",
                chunk_kind="sermon_quote",
                quote_text="Comfort the child and stay in the kitchen with them.",
            ),
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            ),
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        self.assertTrue(any("Comfort the child" in item for item in quotes), quotes)
        self.assertFalse(any("broken heart" in item for item in quotes), quotes)
        nkjv = collect_allowed_nkjv(docs)
        self.assertEqual(nkjv[0][0], "Psalm 34:18")
        self.assertIn("broken heart", nkjv[0][1])

    def test_verify_rejects_invented_quote_and_verse(self):
        sermon = [
            _doc(
                'We sit with the grieving and we pray.',
                source="notes.pdf",
                chunk_kind="sermon_quote",
                quote_text="We sit with the grieving and we pray.",
            )
        ]
        nkjv = [
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            )
        ]
        bad = (
            'Pastor Don Nordin teaches, "Your dog is in dog heaven waiting for you." '
            'Jeremiah 9:24 (NKJV) says, "I am the Lord who invented this kitchen script."'
        )
        report = verify_answer_grounding(bad, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertFalse(report.ok)
        self.assertTrue(report.invented_quotes or report.invented_scripture or report.missing_nkjv_refs)

        good = (
            'Pastor Don Nordin teaches, "We sit with the grieving and we pray." '
            'Psalm 34:18 (NKJV) says, "The Lord is near to those who have a broken heart."'
        )
        ok = verify_answer_grounding(good, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertTrue(ok.ok, ok)

    def test_fallback_uses_only_allowed_lines(self):
        text = grounded_fallback_answer(
            ["We sit with the grieving and we pray."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        self.assertIn("We sit with the grieving", text)
        self.assertIn("Psalm 34:18", text)
        self.assertIn("Pastor Don Nordin teaches", text)
        self.assertNotIn("dog heaven", text.lower())
        self.assertNotIn("From the retrieved notes", text)
        self.assertNotIn("I can only teach from these retrieved lines", text)
        self.assertNotIn("teach from the retrieved sermons", text)

    def test_strip_retrieval_meta_drops_notes_dump(self):
        dumped = (
            "Faith is trust in God, not a feeling.\n\n"
            "From the retrieved notes:\n\n"
            "Pastor Don and Susan Nordin teach from the retrieved sermons:\n\n"
            '"We sit with the grieving and we pray."\n\n'
            "I can only teach from these retrieved lines. Ask another question "
            "if you want a different passage or sermon."
        )
        cleaned = strip_retrieval_meta(dumped)
        self.assertIn("Faith is trust in God", cleaned)
        self.assertNotIn("From the retrieved notes", cleaned)
        self.assertNotIn("I can only teach from these retrieved lines", cleaned)

    def test_weave_into_answer_folds_quotes_into_opening(self):
        answer = (
            "**Faith Over Fear**\n\n"
            "Faith is trust in God rather than a feeling.\n\n"
            "Stand when the pressure comes."
        )
        snippet = grounded_fallback_answer(
            ["We sit with the grieving and we pray."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        woven = weave_into_answer(answer, snippet)
        self.assertTrue(woven.startswith("**Faith Over Fear**"), woven)
        self.assertIn("Faith is trust in God", woven)
        self.assertIn("We sit with the grieving", woven)
        self.assertIn("Psalm 34:18", woven)
        self.assertLess(woven.find("We sit with the grieving"), woven.find("Stand when the pressure"))
        self.assertNotIn("From the retrieved notes", woven)

    def test_heading_quotes_are_not_woven(self):
        self.assertTrue(looks_like_heading_quote("# God Was with Him"))
        self.assertTrue(looks_like_heading_quote("# Jesus as the Word"))
        self.assertFalse(
            looks_like_heading_quote("We sit with the grieving and we pray.")
        )
        text = grounded_fallback_answer(
            ["# God Was with Him", "We sit with the grieving and we pray."],
            [],
        )
        self.assertNotIn("# God Was with Him", text)
        self.assertIn("We sit with the grieving", text)
        dumped = (
            'Certainly! Here\'s a short teaching on the armor of God based on the provided scripture and notes:.\n\n'
            'Pastor Don Nordin teaches, "# God Was with Him"'
        )
        cleaned = strip_retrieval_meta(dumped)
        self.assertNotIn("Certainly", cleaned)
        self.assertNotIn("provided scripture and notes", cleaned)
        self.assertNotIn("# God Was with Him", cleaned)

    def test_strip_slide_direction_notes(self):
        from core.grounding import strip_retrieval_meta

        text = (
            'Pastor Don Nordin teaches, "God is devoted to you." '
            "(LEAVE ON SCREEN UNTIL END OF SERVICE) Keep praying."
        )
        cleaned = strip_retrieval_meta(text)
        self.assertNotIn("LEAVE ON SCREEN", cleaned)
        self.assertIn("God is devoted to you", cleaned)
        self.assertIn("Keep praying", cleaned)

    def test_strip_ungrounded_spans_removes_invented_quote(self):
        from core.grounding import GroundingReport, strip_ungrounded_spans

        answer = (
            'Pastor Don would say, "Your dog is in dog heaven waiting for you." '
            "Then he points us back to prayer."
        )
        report = GroundingReport(
            ok=False,
            invented_quotes=["Your dog is in dog heaven waiting for you."],
            invented_scripture=[],
            missing_nkjv_refs=[],
        )
        cleaned = strip_ungrounded_spans(answer, report)
        self.assertNotIn("dog heaven", cleaned)
        self.assertIn("points us back to prayer", cleaned)

    def test_lookup_uses_retrieved_docs_without_client(self):
        docs = [
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
                chapter=34,
                verse_start=18,
                verse_end=18,
                verse_ref="Psalm 34:18",
                quote_text="The Lord is near to those who have a broken heart.",
            )
        ]
        found = lookup_nkjv_verses(
            None,
            "sermon_brain",
            [("psalm", 34, 18)],
            retrieved_docs=docs,
        )
        self.assertEqual(len(found), 1)

    def test_grounding_repair_steer_lists_allowed_lines(self):
        from core.grounding import GroundingReport, grounding_repair_steer

        report = GroundingReport(
            ok=False,
            invented_quotes=["Your dog is in dog heaven waiting for you."],
            invented_scripture=[],
            missing_nkjv_refs=["Jeremiah 9:24"],
        )
        steer = grounding_repair_steer(
            report,
            ["We sit with the grieving and we pray."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        self.assertIn("RAG check", steer)
        self.assertIn("dog heaven", steer)
        self.assertIn("We sit with the grieving", steer)
        self.assertIn("Psalm 34:18", steer)
        self.assertIn("Do not say Certainly", steer)

    def test_scripture_blobs_are_not_sermon_quotes(self):
        from core.grounding import collect_allowed_sermon_quotes, looks_like_scripture_blob

        self.assertTrue(
            looks_like_scripture_blob(
                "Proverbs 20:5-8 (NKJV): Counsel in the heart of man is like deep water."
            )
        )
        docs = [
            _doc(
                "Proverbs 20:5-8 (NKJV): Counsel in the heart of man is like deep water. "
                "A king who sits on the throne of judgment scatters all evil with his eyes.",
                source="notes.pdf",
                chunk_kind="sermon_quote",
            ),
            _doc(
                'Pastor Don said, "Faith is acting on what God already promised."',
                source="faith.pdf",
                chunk_kind="sermon_quote",
                quote_text="Faith is acting on what God already promised.",
            ),
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        self.assertTrue(any("already promised" in item for item in quotes), quotes)
        self.assertFalse(any("Proverbs" in item for item in quotes), quotes)

    def test_god_speech_is_not_a_pastor_quote(self):
        docs = [
            _doc(
                "God has a plan for your life. Before you were born, I sanctified you "
                "and appointed you as My spokesman to the world.",
                source="purpose.pdf",
                chunk_kind="sermon_quote",
                quote_text="Before you were born, I sanctified you and appointed you as My spokesman to the world.",
            ),
            _doc(
                'Pastor Don said, "There can be only one logical explanation for the precision of these relationships."',
                source="design.pdf",
                chunk_kind="sermon_quote",
                quote_text="There can be only one logical explanation for the precision of these relationships.",
            ),
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        self.assertTrue(any("logical explanation" in item for item in quotes), quotes)
        self.assertFalse(any("sanctified you" in item.lower() for item in quotes), quotes)
        self.assertFalse(any("spokesman" in item.lower() for item in quotes), quotes)

    def test_verify_flags_scripture_wrapped_as_pastor_don(self):
        sermon = [
            _doc(
                "God has an eternal plan for your life.",
                source="notes.pdf",
                chunk_kind="sermon_quote",
                quote_text="God has an eternal plan for your life.",
            )
        ]
        nkjv = [
            _doc(
                "Before I formed you in the womb I knew you; Before you were born I sanctified you; "
                "I ordained you a prophet to the nations.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="jeremiah",
                chapter=1,
                verse_start=5,
                verse_end=5,
                verse_ref="Jeremiah 1:5",
                quote_text=(
                    "Before I formed you in the womb I knew you; Before you were born I sanctified you; "
                    "I ordained you a prophet to the nations."
                ),
            )
        ]
        bad = (
            'Additionally, he emphasizes, "Before you were born, I sanctified you and '
            'appointed you as My spokesman to the world."'
        )
        report = verify_answer_grounding(bad, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertFalse(report.ok)
        self.assertTrue(report.misattributed_quotes, report)

        from core.grounding import repair_speaker_attributions

        fixed = repair_speaker_attributions(bad, nkjv_docs=nkjv)
        self.assertNotIn("he emphasizes", fixed.lower())
        self.assertNotIn("pastor don", fixed.lower())
        self.assertIn("Lord", fixed)
        self.assertIn("sanctified you", fixed)
        ok = verify_answer_grounding(fixed, sermon_docs=sermon, nkjv_docs=nkjv)
        self.assertTrue(ok.ok, ok)
        self.assertFalse(ok.misattributed_quotes)

    def test_verify_flags_unclosed_scripture_wrapped_as_pastor(self):
        nkjv = [
            _doc(
                "Before I formed you in the womb I knew you; Before you were born I sanctified you; "
                "I ordained you a prophet to the nations.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="jeremiah",
                chapter=1,
                verse_start=5,
                verse_end=5,
                verse_ref="Jeremiah 1:5",
            )
        ]
        bad = (
            'Pastor Don Nordin teaches, "Before you were born, I sanctified you '
            "and appointed you as My spokesman to the world.\n"
        )
        report = verify_answer_grounding(bad, sermon_docs=[], nkjv_docs=nkjv)
        self.assertTrue(report.misattributed_quotes, report)
        from core.grounding import repair_speaker_attributions

        fixed = repair_speaker_attributions(bad, nkjv_docs=nkjv)
        self.assertNotIn("Pastor Don", fixed)
        self.assertIn("Jeremiah 1:5", fixed)

    def test_fallback_skips_god_speech(self):
        text = grounded_fallback_answer(
            [
                "Before you were born, I sanctified you and appointed you as My spokesman to the world.",
                "God has an eternal plan for your life.",
            ],
            [("Jeremiah 1:5", "Before I formed you in the womb I knew you.")],
        )
        self.assertNotIn("sanctified you", text)
        self.assertIn("eternal plan", text)
        self.assertIn("Jeremiah 1:5", text)

    def test_selects_query_overlap_quotes(self):
        from core.grounding import select_query_grounded_nkjv, select_query_grounded_quotes

        quotes = select_query_grounded_quotes(
            [
                "Comfort the child and stay in the kitchen with them.",
                "Faith is acting on what God already promised when you pray.",
            ],
            "How does Pastor Don connect faith to prayer?",
        )
        self.assertEqual(quotes, ["Faith is acting on what God already promised when you pray."])
        nkjv = select_query_grounded_nkjv(
            [
                ("Proverbs 20:5", "Counsel in the heart of man is like deep water."),
                ("Hebrews 11:1", "Faith is the substance of things hoped for."),
            ],
            "How does Pastor Don connect faith to prayer?",
        )
        self.assertEqual(nkjv[0][0], "Hebrews 11:1")
        from core.grounding import split_docs_for_grounding

        docs = [
            _doc("sermon line", source="notes.pdf", chunk_kind="sermon_quote"),
            _doc(
                "The Lord is near to those who have a broken heart.",
                source="nkjv-bible.pdf",
                chunk_kind="bible_verse",
                book="psalm",
            ),
        ]
        sermon, bible = split_docs_for_grounding(docs)
        self.assertEqual(len(sermon), 1)
        self.assertEqual(len(bible), 1)


if __name__ == "__main__":
    unittest.main()
