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
        self.assertTrue(looks_like_heading_quote("Who Built the Moon."))
        self.assertTrue(
            looks_like_heading_quote(
                "An instrument used for moving the bolt of a lock thus locking or unlocking something."
            )
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

    def test_strip_glued_book_typo(self):
        from core.grounding import strip_retrieval_meta

        cleaned = strip_retrieval_meta(
            "TJeremiah 1:5 (NKJV) records the Lord saying, \"Before you were born.\""
        )
        self.assertNotIn("TJeremiah", cleaned)
        self.assertIn("Jeremiah 1:5", cleaned)

    def test_strip_source_bullets_and_empty_leadins(self):
        from core.grounding import strip_retrieval_meta

        dumped = (
            'Pastor Don teaches specific prayer.\n'
            'He explains, "\n'
            "land.As I wait on you.\n"
            "• Pastor Don\n"
            "In Romans 10:17 (NKJV), it states, This means faith comes by hearing."
        )
        cleaned = strip_retrieval_meta(dumped)
        self.assertNotIn("He explains", cleaned)
        self.assertNotIn("• Pastor Don", cleaned)
        self.assertIn("land. As I wait", cleaned)
        self.assertIn("Romans 10:17", cleaned)
        self.assertRegex(cleaned, r"Romans 10:17 \(NKJV\) teaches that faith comes")
        self.assertNotIn("it states,", cleaned.lower())
        self.assertNotIn("states, This", cleaned)

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

    def test_lookup_scroll_filter_includes_verse_start(self):
        import inspect

        source = inspect.getsource(lookup_nkjv_verses)
        self.assertIn('key="verse_start"', source)
        self.assertIn("NKJV chapter lookup failed", source)

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

    def test_empty_nkjv_leadins_are_rewritten_and_filled(self):
        from core.grounding import repair_empty_nkjv_citations, strip_retrieval_meta

        worship = (
            "Psalm 22:3 (NKJV) states, This verse highlights that God is enthroned "
            "in the praises of His people. Proverbs 3:5-6 (NKJV) reminds us, "
            "This passage encourages us to rely on God."
        )
        cleaned = strip_retrieval_meta(worship)
        self.assertNotIn("states,", cleaned.lower())
        self.assertNotIn("reminds us,", cleaned.lower())
        self.assertIn('Psalm 22:3 (NKJV) says, "But You are holy', cleaned)
        self.assertIn("Proverbs 3:5-6 (NKJV) teaches that", cleaned)
        filled = repair_empty_nkjv_citations(
            worship,
            [
                (
                    "Psalm 22:3",
                    "But You are holy, Enthroned in the praises of Israel.",
                )
            ],
        )
        self.assertIn('Psalm 22:3 (NKJV) says, "But You are holy', filled)
        self.assertNotIn("states, This verse", filled)

    def test_mixed_worship_notes_keep_pastor_sentences(self):
        from core.grounding import collect_allowed_sermon_quotes

        docs = [
            _doc(
                "Oddly enough, when things are going well, we often have a tendency to "
                "worship our own successes rather than worshiping God. Psalm 22:3 (NKJV) "
                "But You are holy, Enthroned in the praises of Israel. A time of crisis "
                "should drive us to worship God more fervently instead of turning away.",
                source="worship.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        joined = " ".join(quotes)
        self.assertTrue(
            "successes" in joined or "crisis" in joined,
            quotes,
        )
        self.assertFalse(any("Enthroned" in item for item in quotes), quotes)

    def test_newline_chunks_keep_pastor_lines_beside_verses(self):
        from core.grounding import collect_allowed_sermon_quotes

        docs = [
            _doc(
                "Marriage is a developmental process not an event and requires commitment\n"
                "As far as the east is from the west so far has He removed our transgressions\n"
                "We must make sure our spouses feel valued as a very special person today",
                source="home.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        joined = " ".join(quotes)
        self.assertIn("developmental process", joined)
        self.assertIn("special person", joined)
        self.assertFalse(any("east is from the west" in item for item in quotes), quotes)

    def test_fallback_picks_on_topic_quote_when_score_is_low(self):
        from core.grounding import select_query_grounded_quotes

        quotes = select_query_grounded_quotes(
            [
                "Comfort the child and stay in the kitchen with them.",
                "Worship is a jamming device against the enemy when we lift God up.",
            ],
            "Create sermon notes on worship.",
        )
        self.assertEqual(
            quotes,
            ["Worship is a jamming device against the enemy when we lift God up."],
        )

    def test_zero_overlap_quotes_are_not_forced(self):
        from core.grounding import pastor_quotes_match_query, select_query_grounded_quotes

        quotes = select_query_grounded_quotes(
            [
                "There are only two things you can be sure of, death and taxes.",
                "Comfort the child and stay in the kitchen with them.",
            ],
            "Create sermon notes on marriage.",
        )
        self.assertEqual(quotes, [])
        self.assertEqual(
            select_query_grounded_quotes(
                [
                    "There are only two things you can be sure of, death and taxes.",
                    "Comfort the child and stay in the kitchen with them.",
                ],
                "Create sermon notes on marriage.",
                allow_topic_pool_fallback=True,
            ),
            [],
        )
        self.assertFalse(
            pastor_quotes_match_query(
                'Pastor Don Nordin teaches, "There are only two things you can be sure of, death and taxes."',
                "Create sermon notes on marriage.",
            )
        )
        self.assertTrue(
            pastor_quotes_match_query(
                'Pastor Don Nordin teaches, "Marriage is a developmental process that requires commitment."',
                "Create sermon notes on marriage.",
            )
        )

    def test_quoted_nkjv_is_not_rewritten(self):
        from core.grounding import repair_empty_nkjv_citations

        text = (
            '1 Corinthians 7:37-40 (NKJV) says, "Nevertheless he who stands steadfast '
            'in his heart, having no necessity, but has power over his own will."'
        )
        cleaned = repair_empty_nkjv_citations(
            text,
            [
                (
                    "1 Corinthians 7:37",
                    "Nevertheless he who stands steadfast in his heart.",
                )
            ],
        )
        self.assertEqual(cleaned.count("Nevertheless"), 1)
        self.assertIn('says, "Nevertheless', cleaned)
        self.assertNotIn("teaches that ,", cleaned)

    def test_empty_teaches_that_leadin_is_filled(self):
        from core.grounding import repair_empty_nkjv_citations, strip_retrieval_meta

        text = (
            "Psalm 100:4 (NKJV) teaches that to enter His gates with thanksgiving:\n"
            "Isaiah 43:2 (NKJV) teaches that that even in the midst of trouble, God is with us:"
        )
        filled = repair_empty_nkjv_citations(
            text,
            [
                ("Psalm 100:4", "Enter into His gates with thanksgiving, And into His courts with praise."),
                ("Isaiah 43:2", "When you pass through the waters, I will be with you."),
            ],
        )
        self.assertIn('Psalm 100:4 (NKJV) says, "Enter into His gates', filled)
        self.assertIn('Isaiah 43:2 (NKJV) says, "When you pass through', filled)
        self.assertNotIn("teaches that to enter", filled)
        cleaned = strip_retrieval_meta(
            "Creating sermon notes on worship involves emphasizing worship. "
            "Here are some key points based on the teachings provided:. "
            'Pastor Don teaches, "Worship in crisis."'
        )
        self.assertNotIn("teachings provided", cleaned.lower())
        self.assertIn("Worship in crisis", cleaned)

    def test_certainly_here_are_opener_is_stripped(self):
        from core.grounding import strip_retrieval_meta

        cleaned = strip_retrieval_meta(
            "Certainly! Here are some key points from the sermon notes on marriage:. "
            'Pastor Don Nordin teaches, "Marriage is a developmental process."'
        )
        self.assertNotIn("Certainly", cleaned)
        self.assertIn("Marriage is a developmental process", cleaned)

    def test_provided_reference_material_opener_is_stripped(self):
        from core.grounding import strip_retrieval_meta

        cleaned = strip_retrieval_meta(
            "To create sermon notes on marriage based on the provided reference material, "
            "we can focus on the key points regarding personhood. Here’s a summary:. "
            '1 Corinthians 7:37-40 (NKJV) says, "Nevertheless he who stands steadfast in his heart."'
        )
        self.assertNotIn("provided reference material", cleaned.lower())
        self.assertNotIn("here’s a summary", cleaned.lower())
        self.assertIn("1 Corinthians 7:37-40", cleaned)

    def test_certainly_provided_sermon_notes_opener_is_stripped(self):
        from core.grounding import strip_retrieval_meta

        cleaned = strip_retrieval_meta(
            "Certainly! Based on the provided sermon notes, here is a summary of the key points regarding prayer:. "
            'Pastor Don Nordin teaches, "Praying for the lost requires persistence."'
        )
        self.assertNotIn("certainly", cleaned.lower())
        self.assertNotIn("provided sermon notes", cleaned.lower())
        self.assertNotIn("here is a summary", cleaned.lower())
        self.assertIn("Praying for the lost requires persistence", cleaned)

    def test_peter_humility_verse_is_not_collected_as_pastor_quote(self):
        from core.grounding import select_query_grounded_quotes
        from core.speaker_attribution import (
            is_pastor_own_voice,
            looks_like_scripture_wording,
            pastor_attributed_quotes,
            rewrite_misattributed_quotes,
        )

        verse = (
            "Yes, all of you be submissive to one another, and be clothed with humility, "
            "for God resists the proud, But gives grace to the humble."
        )
        teaching = (
            "To receive spiritual miracles and cooperation, we must humble ourselves before others."
        )
        docs = [
            _doc(
                f"{teaching}\n{verse}\n"
                "Humility involves recognizing our dependence on God and taking the high road of humility.",
                source="miracles.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        self.assertFalse(is_pastor_own_voice(verse))
        self.assertTrue(looks_like_scripture_wording(verse))
        self.assertTrue(is_pastor_own_voice(teaching))
        quotes = collect_allowed_sermon_quotes(
            docs, query="Create sermon notes on humility."
        )
        self.assertTrue(any("spiritual miracles" in item.lower() for item in quotes), quotes)
        self.assertFalse(any("be clothed with humility" in item.lower() for item in quotes), quotes)
        picked = select_query_grounded_quotes(
            quotes,
            "Create sermon notes on humility.",
            allow_topic_pool_fallback=True,
        )
        self.assertTrue(
            any(
                "spiritual miracles" in item.lower() or "high road of humility" in item.lower()
                for item in picked
            ),
            picked,
        )
        snippet = grounded_fallback_answer(picked, [])
        remaining = pastor_attributed_quotes(rewrite_misattributed_quotes(snippet))
        self.assertTrue(remaining, snippet)
        self.assertFalse(
            any("be clothed with humility" in span.lower() for span, _lead in remaining),
            remaining,
        )
        self.assertTrue(
            any("spiritual miracles" in span.lower() or "high road" in span.lower() for span, _lead in remaining),
            remaining,
        )

    def test_passage_of_marriage_book_authority_is_stripped(self):
        from core.grounding import strip_retrieval_meta

        cleaned = strip_retrieval_meta(
            'According to the book "Passages of Marriage" by Dr. Frank and Mary Alice Minirth, '
            "there are five distinct units in marriage. "
            'Pastor Don Nordin teaches, "Marriage is a developmental process."'
        )
        self.assertNotIn("Passages of Marriage", cleaned)
        self.assertNotIn("Minirth", cleaned)
        self.assertIn("Marriage is a developmental process", cleaned)

    def test_in_luke_we_see_is_filled_with_nkjv_wording(self):
        from core.grounding import repair_empty_nkjv_citations

        filled = repair_empty_nkjv_citations(
            "In Luke 19:45-48 (NKJV), we see Jesus entering the temple and driving out those who were buying.",
            [
                (
                    "Luke 19:45",
                    "Then He went into the temple and began to drive out those who bought and sold in it.",
                )
            ],
        )
        self.assertIn('Luke 19:45-48 (NKJV) says, "Then He went into the temple', filled)
        self.assertNotIn("we see Jesus", filled)

    def test_nkjv_is_a_reminder_leadin_is_filled(self):
        from core.grounding import repair_empty_nkjv_citations

        filled = repair_empty_nkjv_citations(
            "Paul’s call in Romans 12:1-2 (NKJV) is a powerful reminder of our duty to offer ourselves.",
            [
                (
                    "Romans 12:1",
                    "I beseech you therefore, brethren, by the mercies of God, that you present your bodies a living sacrifice.",
                )
            ],
        )
        self.assertIn('Romans 12:1-2 (NKJV) says, "I beseech you therefore', filled)
        self.assertNotIn("is a powerful reminder", filled)

    def test_empty_leviticus_teaches_that_is_filled_from_pairs(self):
        from core.grounding import repair_empty_nkjv_citations, strip_retrieval_meta

        filled = repair_empty_nkjv_citations(
            "Leviticus 27:30-34 (NKJV) teaches that These commands are not suggestions "
            "but mandates given by God through Moses on Mount Sinai.",
            [
                (
                    "Leviticus 27:30",
                    "And all the tithe of the land, whether of the seed of the land or of the fruit of the tree, is the Lord's.",
                )
            ],
        )
        self.assertIn('says, "And all the tithe of the land', filled)
        self.assertNotIn("teaches that These commands", filled)
        cleaned = strip_retrieval_meta(
            'Pastor Don Nordin teaches, "God is the owner of all creation." '
            "(LEAVE ON THE SCREEN UNTIL NEXT SLIDE) Stewardship is about ownership;\""
        )
        self.assertNotIn("LEAVE ON THE SCREEN", cleaned)

    def test_colon_this_verse_leadin_and_nlt_are_rewritten(self):
        from core.grounding import repair_empty_nkjv_citations, verse_refs_for_lookup

        filled = repair_empty_nkjv_citations(
            "Proverbs 22:6 (NKJV): This verse highlights the significance of early training. "
            'Leviticus 27:30-34 (NLT): "A tenth of the produce of the land belongs to the LORD."',
            [
                ("Proverbs 22:6", "Train up a child in the way he should go."),
                (
                    "Leviticus 27:30",
                    "And all the tithe of the land, whether of the seed of the land or of the fruit of the tree, is the Lord's.",
                ),
            ],
        )
        self.assertIn('Proverbs 22:6 (NKJV) says, "Train up a child', filled)
        self.assertIn("Leviticus 27:30-34 (NKJV)", filled)
        self.assertNotIn("NLT", filled)
        self.assertNotIn("This verse highlights", filled)
        outlined = repair_empty_nkjv_citations(
            "Leviticus 27:30-34 (NLT) outlines the requirement to give a tenth of all produce to the Lord. "
            "This passage underscores the significance of tithing as a commandment.",
            [
                (
                    "Leviticus 27:30",
                    "And all the tithe of the land, whether of the seed of the land or of the fruit of the tree, is the Lord's.",
                )
            ],
        )
        self.assertNotIn("NLT", outlined)
        self.assertIn("Leviticus 27:30-34 (NKJV) says,", outlined)
        self.assertIn("tithe of the land", outlined)
        self.assertIn("This passage underscores", outlined)
        refs = verse_refs_for_lookup("Create sermon notes on worship.", [])
        joined = " ".join(f"{book} {chapter}:{verse}" for book, chapter, verse in refs)
        self.assertTrue("22" in joined or "12" in joined or "4" in joined, refs)

    def test_quoted_teaches_that_on_same_line_is_kept(self):
        from core.grounding import repair_empty_nkjv_citations

        text = (
            "James 1:6-8 (NKJV) teaches that of persistent and unwavering prayer: "
            "“But let him ask in faith, with no doubting.”"
        )
        filled = repair_empty_nkjv_citations(
            text,
            [
                (
                    "James 1:6",
                    "But let him ask in faith, with no doubting, for he who doubts is like a wave of the sea.",
                )
            ],
        )
        self.assertEqual(filled, text)
        self.assertIn("teaches that of persistent", filled)

    def test_i_you_slide_labels_are_not_collected_or_woven(self):
        from core.grounding import select_query_grounded_quotes
        from core.speaker_attribution import is_pastor_own_voice, rewrite_misattributed_quotes

        docs = [
            _doc(
                "I messages rather than you.\n"
                "You make me feel.\n"
                "Marriage is a developmental process, not an event. "
                "Couples must treat marriage as a living relationship that takes daily care.",
                source="home.pdf",
                chunk_kind="sermon_quote",
            )
        ]
        quotes = collect_allowed_sermon_quotes(docs)
        self.assertTrue(any("developmental process" in item for item in quotes), quotes)
        self.assertFalse(any("You make me feel" in item for item in quotes), quotes)
        self.assertFalse(any("messages rather than" in item.lower() and len(item) < 60 for item in quotes), quotes)
        self.assertFalse(is_pastor_own_voice("You make me feel"))
        self.assertFalse(is_pastor_own_voice('I” messages rather than “you'))
        self.assertTrue(
            is_pastor_own_voice(
                "Use I messages rather than you messages when you speak to your spouse."
            )
        )
        picked = select_query_grounded_quotes(
            quotes + ["You make me feel", 'I messages rather than you'],
            "Create sermon notes on marriage.",
            allow_topic_pool_fallback=True,
        )
        self.assertTrue(any("developmental" in item for item in picked), picked)
        self.assertFalse(any("You make me feel" in item for item in picked), picked)
        snippet = grounded_fallback_answer(picked, [])
        self.assertNotIn("You make me feel", snippet)
        live = (
            'Pastor Don Nordin teaches, "I” messages rather than “you" Pastor Don and Susan '
            'Nordin also teach, "You make me feel" 1 Corinthians 7:37 (NKJV) says, '
            '"Nevertheless he who stands steadfast in his heart."'
        )
        cleaned = rewrite_misattributed_quotes(weave_into_answer(live, snippet))
        self.assertNotIn("You make me feel", cleaned)
        self.assertIn("developmental process", cleaned)

    def test_collect_ranks_marriage_quotes_ahead_of_slide_fillers(self):
        from core.grounding import select_query_grounded_quotes

        docs = [
            _doc(
                f"How could you possibly feel that way about tone {index}?",
                source="home.pdf",
                chunk_kind="sermon_quote",
            )
            for index in range(12)
        ]
        docs.append(
            _doc(
                "It is important for each of us to make a deliberate commitment "
                "to this relationship called marriage. According to the book, "
                '"Passages of Marriage" by Dr. Hemfelt.',
                source="home.pdf",
                chunk_kind="sermon_quote",
                quote_text=(
                    "It is important for each of us to make a deliberate commitment "
                    "to this relationship called marriage. | According to the book, "
                    '"Passages of Marriage" by Dr.'
                ),
            )
        )
        quotes = collect_allowed_sermon_quotes(
            docs, query="Create sermon notes on marriage."
        )
        self.assertTrue(any("deliberate commitment" in item for item in quotes), quotes)
        self.assertFalse(any("passages of marriage" in item.lower() for item in quotes), quotes)
        self.assertFalse(any("according to the book" in item.lower() for item in quotes), quotes)
        picked = select_query_grounded_quotes(
            quotes, "Create sermon notes on marriage.", allow_topic_pool_fallback=True
        )
        self.assertTrue(any("deliberate commitment" in item for item in picked), picked)
        snippet = grounded_fallback_answer(picked, [])
        self.assertIn("deliberate commitment", snippet)
        self.assertNotIn("Passages of Marriage", snippet)

    def test_ensure_topical_nkjv_replaces_celibacy_verse_for_marriage(self):
        from core.grounding import ensure_topical_nkjv, nkjv_matches_query

        query = "Create sermon notes on marriage."
        off_topic = (
            '1 Corinthians 7:37-40 (NKJV) says, "Nevertheless he who stands steadfast '
            'in his heart, having no necessity, but has power over his own will, and has '
            'so determined in his heart that he will keep his virgin, does well."'
        )
        self.assertFalse(nkjv_matches_query(off_topic, query))
        pairs = [
            (
                "Genesis 2:24",
                "Therefore a man shall leave his father and mother and be joined to his wife, and they shall become one flesh.",
            ),
            (
                "1 Corinthians 7:37",
                "Nevertheless he who stands steadfast in his heart.",
            ),
        ]
        cleaned = ensure_topical_nkjv(off_topic, query, pairs)
        self.assertIn("Genesis 2:24", cleaned)
        self.assertIn("joined to his wife", cleaned)
        self.assertNotIn("keep his virgin", cleaned)
        self.assertTrue(nkjv_matches_query(cleaned, query))

    def test_bare_leviticus_cite_is_not_quoted_nkjv_and_gets_filled(self):
        from core.grounding import ensure_topical_nkjv, nkjv_matches_query

        query = "Create sermon notes on giving and stewardship."
        bare = (
            "Stewardship is about ownership. In Leviticus 27:30-34, we see clear "
            "directives regarding tithes and offerings. These commands underscore tithing."
        )
        self.assertFalse(nkjv_matches_query(bare, query))
        pairs = [
            (
                "Leviticus 27:30",
                "And all the tithe of the land, whether of the seed of the land or of the fruit of the tree, is the Lord's.",
            ),
            (
                "Malachi 3:10",
                "Bring all the tithes into the storehouse, that there may be food in My house.",
            ),
        ]
        filled = ensure_topical_nkjv(bare, query, pairs)
        self.assertIn("(NKJV) says,", filled)
        self.assertTrue(nkjv_matches_query(filled, query))
        self.assertTrue(
            "tithe of the land" in filled or "tithes into the storehouse" in filled
            or "earth is the LORD" in filled or "earth is the Lord's" in filled,
            filled,
        )
        from_fallback = ensure_topical_nkjv(bare, query, [])
        self.assertIn("(NKJV) says,", from_fallback)
        self.assertTrue(nkjv_matches_query(from_fallback, query))

    def test_unquoted_leviticus_outline_replaced_even_with_off_topic_pairs(self):
        from core.chat_retrieval import has_quoted_nkjv
        from core.grounding import ensure_topical_nkjv, nkjv_matches_query

        query = "Create sermon notes on giving and stewardship."
        text = (
            "### Sermon Notes: Giving and Stewardship\n\n"
            "**Stewardship Defined**\n"
            "Stewardship is the sum total of man's attitude toward the Creator. "
            'Pastor Don Nordin teaches, "The subject of tithing is really not about money alone, '
            'it is about a lifestyle of stewardship!" '
            "Leviticus 27:30-34 outlines the requirements for giving, emphasizing the importance "
            "of honoring God with our finances."
        )
        filled = ensure_topical_nkjv(
            text,
            query,
            [("1 Corinthians 7:1", "It is good for a man not to touch a woman.")],
        )
        self.assertTrue(has_quoted_nkjv(filled), filled)
        self.assertTrue(nkjv_matches_query(filled, query), filled)
        self.assertIn("tithe of the land", filled)
        self.assertNotIn("not to touch a woman", filled)
        self.assertNotIn("outlines the requirements for giving", filled)

    def test_giving_range_starting_at_ban_verse_is_replaced_with_tithe_verse(self):
        from core.chat_retrieval import has_quoted_nkjv
        from core.grounding import ensure_topical_nkjv, nkjv_matches_query

        query = "Create sermon notes on giving and stewardship."
        text = (
            'Pastor Don Nordin teaches, "Stewardship is the sum total of man’s attitude '
            'and reaction toward the Divine Creator and His creation." '
            'Leviticus 27:29-32 (NKJV) says, "No person under the ban, who may become doomed '
            "to destruction among men, shall be redeemed, but shall surely be put to death. "
            "And all the tithe of the land, whether of the seed of the land or of the fruit "
            'of the tree, is the LORD\'s."'
        )
        filled = ensure_topical_nkjv(text, query, [])
        self.assertTrue(has_quoted_nkjv(filled), filled)
        self.assertTrue(nkjv_matches_query(filled, query), filled)
        self.assertIn("Leviticus 27:30", filled)
        self.assertIn("tithe of the land", filled)
        self.assertNotIn("under the ban", filled)
        self.assertNotIn("put to death", filled)

    def test_prayer_teaches_that_without_quote_is_filled_from_topic_wording(self):
        from core.chat_retrieval import has_quoted_nkjv
        from core.grounding import nkjv_matches_query, repair_empty_nkjv_citations

        query = "Create sermon notes on prayer."
        text = (
            'Pastor Don Nordin teaches, "Praying For and reaching the lost requires persistence." '
            "Matthew 6:5-8 (NKJV) teaches that And when you pray, you shall not be like the hypocrites. "
            "For they love to pray standing in the synagogues they have their reward."
        )
        repaired = repair_empty_nkjv_citations(text, [])
        self.assertTrue(has_quoted_nkjv(repaired), repaired)
        self.assertTrue(nkjv_matches_query(repaired, query), repaired)
        self.assertIn("when you pray, go into your room", repaired)

    def test_prodigal_story_question_gets_quoted_nkjv_fallback(self):
        from core.chat_retrieval import has_quoted_nkjv
        from core.grounding import ensure_topical_nkjv, nkjv_matches_query

        query = "What does Pastor Don say about the prodigal son?"
        text = (
            'Pastor Don Nordin teaches, "The father ran to the son before the son could finish his speech." '
            "The story shows mercy that restores a wandering child."
        )
        filled = ensure_topical_nkjv(text, query, [])
        self.assertTrue(has_quoted_nkjv(filled), filled)
        self.assertTrue(nkjv_matches_query(filled, query), filled)
        self.assertIn("Luke 15:20", filled)
        self.assertIn("great way off", filled)

    def test_nkjv_says_without_opening_quote_is_repaired(self):
        from core.chat_retrieval import has_quoted_nkjv
        from core.grounding import ensure_topical_nkjv, repair_empty_nkjv_citations

        query = "Create sermon notes on prayer."
        text = (
            'Pastor Don Nordin teaches, "Praying for the lost requires persistence." '
            "Matthew 6:5-8 (NKJV) says, And when you pray, you shall not be like the hypocrites. "
            "For they love to pray standing in the synagogues. they have their reward.\""
        )
        self.assertFalse(has_quoted_nkjv(text))
        repaired = repair_empty_nkjv_citations(
            text,
            [
                (
                    "Matthew 6:6",
                    "But you, when you pray, go into your room, and when you have shut your door, pray to your Father who is in the secret place.",
                )
            ],
        )
        topical = ensure_topical_nkjv(text, query, [])
        self.assertTrue(has_quoted_nkjv(repaired) or has_quoted_nkjv(topical), repaired + "\n---\n" + topical)


if __name__ == "__main__":
    unittest.main()
