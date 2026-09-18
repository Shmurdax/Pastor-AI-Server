import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.chat_retrieval import (
    apply_retrieval_threshold,
    bible_book_key,
    ensure_source_media_mix,
    expand_search_queries,
    extract_used_quotes,
    extract_used_verse_refs,
    filter_hits_by_topic,
    format_reference_notes,
    is_bible_source,
    is_video_chunk,
    keyword_search_query,
    looks_like_followup,
    merge_scored_hits,
    query_focus_tokens,
    search_queries_on_store,
    select_diverse_docs,
    sources_cited_in_answer,
    topic_overlap_score,
    uniqueness_instruction,
)


def _doc(text, *, source, file_hash=None, title=None, content_type=None, media_type=None, timestamp=None):
    metadata = {
        "source": source,
        "file_hash": file_hash or source,
        "title": title or source,
    }
    if content_type:
        metadata["content_type"] = content_type
    if media_type:
        metadata["media_type"] = media_type
    if timestamp:
        metadata["timestamp"] = timestamp
    return SimpleNamespace(
        page_content=text,
        metadata=metadata,
    )


class ChatRetrievalTests(unittest.TestCase):
    def test_followup_query_includes_prior_turn(self):
        queries = expand_search_queries(
            "Can you further clarify that guidance?",
            ["What should I say to someone who is gay?"],
        )
        joined = " | ".join(queries).lower()
        self.assertIn("gay", joined)
        self.assertTrue(any("clarify" in item.lower() for item in queries))
        self.assertGreaterEqual(len(queries), 2)

    def test_followup_query_uses_prior_ai_steps(self):
        queries = expand_search_queries(
            "Can you further clarify those steps?",
            ["What should I say to someone who is gay?"],
            prior_ai_texts=[
                "Pastor Don Nordin teaches compassion.\n\n"
                "**Affirm Their Worth**\n"
                "**Express Care**\n"
                "**Offer Truth**\n"
                "Genesis 1:27 shows every person bears God's image."
            ],
            limit=5,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("gay", joined)
        self.assertTrue(
            any("affirm" in item.lower() or "worth" in item.lower() for item in queries),
            queries,
        )

    def test_first_turn_embeds_topic_not_the_full_prompt(self):
        queries = expand_search_queries("What should I say to someone who is gay?")
        joined = " | ".join(queries).lower()
        self.assertTrue(queries[0].lower() == "gay" or queries[0].lower().startswith("gay"), queries)
        self.assertIn("gay", joined)
        self.assertTrue(any("gay" in item.lower() and "pastor don" in item.lower() for item in queries))
        self.assertFalse(any("what should i say" in item.lower() for item in queries), queries)

    def test_generate_a_sermon_embeds_social_issue_not_template(self):
        queries = expand_search_queries(
            "Generate a sermon based on homosexuality and abortion",
            limit=7,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("homosexuality", joined)
        self.assertIn("abortion", joined)
        self.assertTrue(
            queries[0].lower() in {"homosexuality abortion", "abortion homosexuality"}
            or ("homosexuality" in queries[0].lower() and "abortion" in queries[0].lower()),
            queries,
        )
        self.assertFalse(any("generate" in item.lower() for item in queries), queries)
        self.assertFalse(any(item.lower().startswith("generate a sermon") for item in queries), queries)
        focus = query_focus_tokens("Generate a sermon based on homosexuality and abortion")
        self.assertIn("homosexuality", focus)
        self.assertIn("abortion", focus)
        self.assertNotIn("generate", focus)
        self.assertNotIn("sermon", focus)

    def test_theology_prompt_embeds_predestination_and_salvation(self):
        queries = expand_search_queries(
            "Write me a sermon about predestination and salvation",
            limit=7,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("predestination", joined)
        self.assertIn("salvation", joined)
        self.assertTrue("predestination" in queries[0].lower() or "salvation" in queries[0].lower(), queries)
        self.assertFalse(any("write" in item.lower() for item in queries), queries)

    def test_cain_and_abel_queries_lead_with_names_not_give_me_a_sermon(self):
        queries = expand_search_queries(
            "Give me a sermon based on the story of Cain and Abel",
            limit=7,
        )
        joined = " | ".join(queries).lower()
        self.assertTrue(queries[0].lower().startswith("cain"), queries)
        self.assertIn("abel", queries[0].lower())
        self.assertIn("genesis 4", joined)
        focus = query_focus_tokens("Give me a sermon based on the story of Cain and Abel")
        self.assertIn("cain", focus)
        self.assertIn("abel", focus)
        self.assertNotIn("able", focus)
        self.assertNotIn("cane", focus)
        self.assertNotIn("sermon", focus)
        self.assertNotIn("story", focus)
        self.assertNotIn("based", focus)
        self.assertFalse(
            any(re.search(r"\b(?:able|cane)\b", item.lower()) for item in queries),
            queries,
        )

    def test_named_story_drops_unrelated_intro_video(self):
        cain_video = _doc(
            "Pastor Don teaches Kane and Able brought offerings in Genesis.",
            source="walk_through_word.mp4",
            title="Walk Through the Word",
            content_type="video_transcript",
            timestamp="12:10–14:02",
        )
        intro = _doc(
            "Welcome everyone give me a sermon based on living your best life today.",
            source="april_7.mp4",
            title="April 7",
            content_type="video_transcript",
            timestamp="00:00–02:31",
        )
        notes = _doc(
            "Cain and Abel show the heart of true worship and offering.",
            source="better_days.pdf",
            title="Better Days Ahead",
            content_type="document",
        )
        query = "Give me a sermon based on the story of Cain and Abel"
        kept = filter_hits_by_topic(
            [(intro, 0.93), (notes, 0.88), (cain_video, 0.81)],
            query,
            retrieval_k=24,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertIn("walk_through_word.mp4", sources)
        self.assertIn("better_days.pdf", sources)
        self.assertNotIn("april_7.mp4", sources)

        selected = select_diverse_docs(
            [(intro, 0.93), (notes, 0.88), (cain_video, 0.81)],
            k=6,
            bible_ratio=0.3,
            video_ratio=0.45,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            is_video=is_video_chunk,
            source_key=lambda doc: doc.metadata["source"],
            query=query,
        )
        selected_sources = [doc.metadata["source"] for doc in selected]
        self.assertIn("walk_through_word.mp4", selected_sources)
        self.assertNotIn("april_7.mp4", selected_sources)

    def test_able_in_ordinary_english_does_not_match_abel(self):
        query = "Give me a sermon based on the story of Cain and Abel"
        focus = query_focus_tokens(query)
        intro = _doc(
            "Welcome everyone we are able to worship the Lord together this morning.",
            source="april_7.mp4",
            title="April 7",
            content_type="video_transcript",
            timestamp="00:00–02:31",
        )
        whisper = _doc(
            "Pastor Don teaches Kane and Able brought offerings in Genesis.",
            source="cain_abel.mp4",
            title="Cain and Abel",
            content_type="video_transcript",
            timestamp="12:10–14:02",
        )
        self.assertEqual(topic_overlap_score(intro, focus), 0.0)
        self.assertGreater(topic_overlap_score(whisper, focus), 0.0)

        kept = filter_hits_by_topic(
            [(intro, 0.94), (whisper, 0.74)],
            query,
            retrieval_k=24,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertEqual(sources, ["cain_abel.mp4"])

        thresholded = apply_retrieval_threshold(kept, threshold=0.8, retrieval_k=24)
        self.assertEqual(
            [doc.metadata["source"] for doc, _score in thresholded],
            ["cain_abel.mp4"],
        )

    def test_named_story_does_not_fallback_to_unrelated_hits(self):
        intro = _doc(
            "Welcome we are able to start the service today with prayer.",
            source="april_7.mp4",
            title="April 7",
            content_type="video_transcript",
        )
        notes = _doc(
            "Christian boundaries for dating and friendship in the church.",
            source="boundaries.pdf",
            title="Christian Boundaries",
            content_type="document",
        )
        bible = _doc(
            "In the beginning God created the heaven and the earth.",
            source="nkjv-bible.pdf",
        )
        query = "Give me a sermon based on the story of Cain and Abel"
        kept = filter_hits_by_topic(
            [(intro, 0.94), (notes, 0.91), (bible, 0.70)],
            query,
            retrieval_k=24,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertEqual(sources, ["nkjv-bible.pdf"])
        empty = filter_hits_by_topic(
            [(intro, 0.94), (notes, 0.91)],
            query,
            retrieval_k=24,
        )
        self.assertEqual(empty, [])

    def test_named_story_sources_do_not_pad_to_five_unrelated(self):
        query = "Give me a sermon based on the story of Cain and Abel"
        docs = [
            _doc(
                "Pastor Don teaches Kane and Able brought offerings in Genesis.",
                source="walk_through_word.mp4",
                title="Walk Through the Word",
                content_type="video_transcript",
                timestamp="12:10–14:02",
            ),
            _doc(
                "Cain and Abel show the heart of true worship and offering.",
                source="better_days.pdf",
                title="Better Days Ahead",
                content_type="document",
            ),
            _doc(
                "Welcome we are able to worship together this morning.",
                source="april_7.mp4",
                title="April 7",
                content_type="video_transcript",
                timestamp="00:00–02:31",
            ),
            _doc(
                "Christian boundaries for dating and friendship.",
                source="boundaries.pdf",
                title="Christian Boundaries",
                content_type="document",
            ),
            _doc(
                "Contagious Christianity outreach notes for the city.",
                source="contagious.pdf",
                title="Contagious Christianity",
                content_type="document",
            ),
        ]

        def label(doc):
            meta = doc.metadata
            name = meta.get("title") or meta["source"]
            ts = meta.get("timestamp")
            return f"{name} [{ts}]" if ts else name

        mixed = ensure_source_media_mix(
            ["April 7 [00:00–02:31]", "Better Days Ahead", "Christian Boundaries"],
            docs,
            label,
            min_count=3,
            limit=5,
            query=query,
        )
        self.assertTrue(any("Walk Through the Word" in item for item in mixed), mixed)
        self.assertIn("Better Days Ahead", mixed)
        self.assertFalse(any("April 7" in item for item in mixed), mixed)
        self.assertFalse(any("Christian Boundaries" in item for item in mixed), mixed)
        self.assertFalse(any("Contagious" in item for item in mixed), mixed)
        self.assertLessEqual(len(mixed), 2)

    def test_looks_like_followup(self):
        self.assertTrue(looks_like_followup("Can you further clarify that guidance?"))
        self.assertTrue(looks_like_followup("What do you mean?"))
        self.assertFalse(looks_like_followup("Hello how are you today?"))
        self.assertFalse(looks_like_followup("Hi"))
        self.assertFalse(looks_like_followup(
            "If a teenager in the youth group comes out, what would this pastor say to the student?"
        ))

    def test_uniqueness_followup_stays_on_topic(self):
        text = uniqueness_instruction(
            ['We love and accept the sinner but refuse to accept a sinful lifestyle.'],
            ["Genesis 1:27"],
            is_followup=True,
            prior_user_query="What should I say to someone who is gay?",
        )
        self.assertIn("SAME chat", text)
        self.assertIn("gay", text.lower())
        self.assertIn("do not switch to an unrelated sermon theme", text.lower())
        self.assertIn("Genesis 1:27", text)

    def test_extracts_quotes_and_ezekiel_verse(self):
        answer = (
            'As Pastor Don Nordin teaches, "I am not sure how the term ‘Gay’ became part of the lexicon" '
            "and remember, “the soul that sins shall surely die” (Ezekiel 18:4 NKJV)."
        )
        quotes = extract_used_quotes([answer])
        verses = extract_used_verse_refs([answer])
        self.assertTrue(any("lexicon" in item.lower() for item in quotes))
        self.assertTrue(any(item.lower().startswith("ezekiel 18:4") for item in verses))

    def test_select_diverse_docs_spreads_sources(self):
        scored = [
            (_doc("gay identity teaching from sermon A " * 8, source="sermon-a.pdf"), 0.92),
            (_doc("more gay identity from sermon A " * 8, source="sermon-a.pdf"), 0.91),
            (_doc("still more sermon A overlap " * 8, source="sermon-a.pdf"), 0.90),
            (_doc("compassion and truth from sermon B " * 8, source="sermon-b.pdf"), 0.80),
            (_doc("parenting wisdom from sermon C " * 8, source="sermon-c.pdf"), 0.78),
            (_doc("Ezekiel 18:4 the soul who sins shall die", source="nkjv-bible.pdf"), 0.88),
            (_doc("John 3:16 for God so loved the world", source="nkjv-bible.pdf"), 0.70),
            (_doc("Romans 1:16 the gospel is the power of God", source="nkjv-bible.pdf"), 0.66),
        ]
        selected = select_diverse_docs(
            scored,
            k=6,
            bible_ratio=0.45,
            max_per_source=2,
            max_per_bible_book=1,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertLessEqual(sources.count("sermon-a.pdf"), 2)
        self.assertIn("sermon-b.pdf", sources)
        self.assertIn("sermon-c.pdf", sources)
        books = [bible_book_key(doc.page_content) for doc in selected if is_bible_source(doc.metadata["source"])]
        self.assertEqual(len(books), len(set(books)))

    def test_select_diverse_docs_mixes_notes_and_videos(self):
        scored = [
            (_doc("elders must be above reproach teaching " * 6, source="elders.pdf", content_type="document"), 0.95),
            (_doc("more elders notes about character " * 6, source="elders.pdf", content_type="document"), 0.94),
            (_doc("boundaries in ministry notes " * 6, source="boundaries.pdf", content_type="document"), 0.93),
            (
                _doc(
                    "video teaching on pastoral leadership " * 6,
                    source="may_23.mp4",
                    content_type="video_transcript",
                    media_type="video",
                    timestamp="10:45–12:43",
                ),
                0.80,
            ),
            (
                _doc(
                    "another video clip about shepherds " * 6,
                    source="june_30.mp4",
                    content_type="video_transcript",
                    media_type="video",
                    timestamp="01:00–02:00",
                ),
                0.78,
            ),
            (_doc("Titus 1:6 if a man is blameless", source="nkjv-bible.pdf"), 0.88),
            (_doc("Ephesians 5:23 husband is head of the wife", source="nkjv-bible.pdf"), 0.70),
        ]
        selected = select_diverse_docs(
            scored,
            k=6,
            bible_ratio=0.35,
            video_ratio=0.45,
            max_per_source=2,
            max_per_bible_book=1,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            is_video=is_video_chunk,
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertTrue(any(src.endswith(".pdf") and "bible" not in src for src in sources), sources)
        self.assertTrue(any(src.endswith(".mp4") for src in sources), sources)
        self.assertTrue(any(is_bible_source(src) for src in sources), sources)

    def test_ensure_source_media_mix_adds_missing_video(self):
        docs = [
            _doc("notes", source="elders.pdf", title="Elders Charge", content_type="document"),
            _doc(
                "clip",
                source="may_23.mp4",
                title="May 23",
                content_type="video_transcript",
                timestamp="10:45–12:43",
            ),
        ]

        def label(doc):
            meta = doc.metadata
            name = meta.get("title") or meta["source"]
            ts = meta.get("timestamp")
            return f"{name} [{ts}]" if ts else name

        mixed = ensure_source_media_mix(["Elders Charge"], docs, label, limit=5, min_count=2)
        self.assertIn("Elders Charge", mixed)
        self.assertTrue(any("May 23" in item for item in mixed), mixed)

    def test_ensure_source_media_mix_fills_three_to_five(self):
        docs = [
            _doc("women pastors elders complementarian teaching", source="elders.pdf", title="Elders Charge", content_type="document"),
            _doc("women in ministry egalitarian notes", source="boundaries.pdf", title="Christian Boundaries", content_type="document"),
            _doc("discipleship of leaders in the church", source="d101.pdf", title="Discipleship 101", content_type="document"),
            _doc(
                "women pastors elders preachers complementarian video",
                source="may_23.mp4",
                title="Women in Leadership",
                content_type="video_transcript",
                timestamp="10:45–12:43",
            ),
            _doc(
                "unrelated weather announcement from sunday",
                source="may_17.mp4",
                title="May 17",
                content_type="video_transcript",
                timestamp="09:44–10:37",
            ),
        ]

        def label(doc):
            meta = doc.metadata
            name = meta.get("title") or meta["source"]
            ts = meta.get("timestamp")
            return f"{name} [{ts}]" if ts else name

        query = "Women as pastors elders preachers complementarian egalitarian"
        mixed = ensure_source_media_mix(
            ["Elders Charge"],
            docs,
            label,
            min_count=3,
            limit=5,
            query=query,
        )
        self.assertGreaterEqual(len(mixed), 3)
        self.assertLessEqual(len(mixed), 5)
        self.assertIn("Elders Charge", mixed)
        self.assertTrue(any("Women in Leadership" in item for item in mixed), mixed)
        self.assertFalse(any(item.startswith("May 17") for item in mixed), mixed)

    def test_filter_hits_by_topic_drops_unrelated_when_enough_on_topic(self):
        from core.chat_retrieval import filter_hits_by_topic

        on_topic = _doc(
            "complementarian egalitarian women pastors elders preachers",
            source="elders.pdf",
            title="Elders Charge",
        )
        off_topic = _doc(
            "thirty things for a blessed life prosperity list",
            source="may_17.mp4",
            title="May 17",
            content_type="video_transcript",
        )
        hits = [(on_topic, 0.91) for _ in range(8)] + [(off_topic, 0.89)]
        kept = filter_hits_by_topic(
            hits,
            "Women as pastors elders preachers complementarian egalitarian",
            retrieval_k=6,
        )
        texts = " ".join(doc.page_content for doc, _score in kept)
        self.assertIn("complementarian", texts)
        self.assertNotIn("thirty things", texts)

    def test_novelty_skips_already_quoted_chunk_when_alternatives_exist(self):
        used_quote = "I am not sure how the term Gay became part of the lexicon"
        used_verse = "Ezekiel 18:4"
        scored = [
            (
                _doc(
                    f'Pastor Don said "{used_quote}" and cited {used_verse} the soul who sins.',
                    source="sermon-a.pdf",
                ),
                0.99,
            ),
            (_doc("A different pastoral line about compassion and holy living.", source="sermon-b.pdf"), 0.70),
            (_doc("John 8:11 go and sin no more teaching from the notes.", source="nkjv-bible.pdf"), 0.68),
            (_doc("Romans 12:9 let love be without hypocrisy.", source="nkjv-bible.pdf"), 0.60),
        ]
        selected = select_diverse_docs(
            scored,
            k=3,
            bible_ratio=0.4,
            max_per_source=2,
            used_quotes=[used_quote],
            used_verses=[used_verse],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        texts = " ".join(doc.page_content for doc in selected)
        self.assertNotIn(used_quote, texts)
        self.assertNotIn("Ezekiel 18:4", texts)

    def test_format_notes_labels_sources(self):
        docs = [
            _doc("First chunk", source="love.pdf", title="Walking in Love"),
            _doc("Second chunk", source="nkjv-bible.pdf", title="NKJV Bible"),
        ]
        notes = format_reference_notes(docs, lambda doc: doc.metadata["title"], max_chars=4000)
        self.assertIn("[Note 1 | Walking in Love]", notes)
        self.assertIn("[Note 2 | NKJV Bible]", notes)
        self.assertIn("First chunk", notes)

    def test_uniqueness_instruction_lists_prior_material(self):
        text = uniqueness_instruction(
            ['I am not sure how the term Gay became part of the lexicon'],
            ["Ezekiel 18:4"],
        )
        self.assertIn("<uniqueness>", text)
        self.assertIn("Ezekiel 18:4", text)
        self.assertIn("lexicon", text)
        self.assertIn("Do not restate the previous answer", text)

    def test_merge_scored_hits_keeps_best_duplicate(self):
        doc_a = _doc("same chunk text about mercy", source="a.pdf")
        doc_b = _doc("same chunk text about mercy", source="a.pdf")
        merged = merge_scored_hits([[(doc_a, 0.4)], [(doc_b, 0.9)]])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0][1], 0.9)

    def test_search_queries_on_store_runs_each_query(self):
        store = Mock()
        store.similarity_search_with_score.side_effect = [
            [(_doc("one", source="a.pdf"), 0.8)],
            [(_doc("two", source="b.pdf"), 0.7)],
        ]
        hits = search_queries_on_store(store, ["alpha", "beta"], k_per_query=8)
        self.assertEqual(store.similarity_search_with_score.call_count, 2)
        self.assertEqual(len(hits), 2)


SCREENSHOT_TURN1 = "Recount what Pastor Don believes about faith?"
SCREENSHOT_TURN2 = "Give me a 3 point sermon on that topic"
SCREENSHOT_TURN1_PARAPHRASE = (
    "**Faith as a Gift**\n\n"
    "Pastor Don teaches that faith is a tool given at birth. You already use it when you "
    "board an airplane, step into an elevator, or drive a car. Faith is independent of "
    "religious beliefs, and blessings come from God when we exercise it.\n\n"
    "In conclusion, cultivate the faith you already have."
)


class ScreenshotFaithTurnReproductionTests(unittest.TestCase):
    """Qdrant/vLLM-free reproduction of the two chat turns from the user screenshot."""

    def test_turn1_keeps_faith_keywords(self):
        focus = keyword_search_query(SCREENSHOT_TURN1)
        queries = expand_search_queries(SCREENSHOT_TURN1, limit=7)
        joined = " | ".join(queries).lower()
        # 7 tokens matches the <=8-word heuristic, but with no prior turn
        # expand_search_queries still treats this as a first question.
        self.assertEqual(len(SCREENSHOT_TURN1.split()), 7)
        self.assertTrue(looks_like_followup(SCREENSHOT_TURN1))
        self.assertIn("faith", focus.lower())
        self.assertIn("faith", joined)
        self.assertTrue(any("pastor don" in item.lower() for item in queries), queries)
        self.assertNotIn("elevator", joined)
        self.assertNotIn("airplane", joined)

    def test_turn2_strips_to_point_and_is_not_classified_followup(self):
        focus = keyword_search_query(SCREENSHOT_TURN2)
        tokens = query_focus_tokens(SCREENSHOT_TURN2)
        followup = looks_like_followup(SCREENSHOT_TURN2)
        views_is_followup = True and followup  # prior exists in the screenshot thread
        queries = expand_search_queries(
            SCREENSHOT_TURN2,
            [SCREENSHOT_TURN1],
            prior_ai_texts=[SCREENSHOT_TURN1_PARAPHRASE],
            limit=7,
        )
        joined = " | ".join(queries).lower()
        self.assertEqual(len(SCREENSHOT_TURN2.split()), 9)
        self.assertFalse(followup)
        self.assertFalse(views_is_followup)
        self.assertEqual(focus.lower(), "point")
        self.assertEqual(tokens, frozenset({"point"}))
        self.assertEqual(queries[0].lower(), "point")
        self.assertTrue(any(item.lower() == "pastor don nordin point" for item in queries), queries)
        self.assertTrue(any("faith" in item.lower() for item in queries), queries)
        self.assertIn("point", joined)

    def test_turn2_lexical_filter_keys_off_point_not_faith(self):
        faith_note = _doc(
            "Faith is a gift from God. Pastor Don teaches we walk by faith not sight.",
            source="faith.pdf",
            title="Walking in Faith",
        )
        point_hits = [
            (
                _doc(
                    f"The point of message {index} is three points for a better life today.",
                    source=f"better_life_{index}.pdf",
                    title=f"A Better Life {index}",
                ),
                0.80,
            )
            for index in range(8)
        ]
        kept = filter_hits_by_topic(
            [(faith_note, 0.91)] + point_hits,
            SCREENSHOT_TURN2,
            retrieval_k=6,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertTrue(any(item.startswith("better_life_") for item in sources), sources)
        self.assertNotIn("faith.pdf", sources)

    def test_uniqueness_and_length_steer_conflict_on_turn2(self):
        from core.chat_system_prompt import LENGTH_STEER, query_expects_long_answer

        is_followup = bool([SCREENSHOT_TURN1]) and looks_like_followup(SCREENSHOT_TURN2)
        uniqueness = uniqueness_instruction(
            extract_used_quotes([SCREENSHOT_TURN1_PARAPHRASE]),
            extract_used_verse_refs([SCREENSHOT_TURN1_PARAPHRASE]),
            is_followup=is_followup,
            prior_user_query=SCREENSHOT_TURN1,
        )
        self.assertFalse(is_followup)
        self.assertIn("Do not restate the previous answer", uniqueness)
        self.assertNotIn("SAME chat", uniqueness)
        self.assertTrue(query_expects_long_answer(SCREENSHOT_TURN2))
        human = f"{LENGTH_STEER}{SCREENSHOT_TURN2}"
        self.assertTrue(human.startswith(LENGTH_STEER))
        self.assertIn("Quote Pastor Don", LENGTH_STEER)
        self.assertIn("**bold headings**", LENGTH_STEER)
        self.assertIn("bullet points", LENGTH_STEER)

    def test_paraphrase_has_no_quotes_and_no_post_generation_check(self):
        from core.chat_system_prompt import answer_needs_expansion

        quotes = extract_used_quotes([SCREENSHOT_TURN1_PARAPHRASE])
        verses = extract_used_verse_refs([SCREENSHOT_TURN1_PARAPHRASE])
        self.assertEqual(quotes, [])
        self.assertEqual(verses, [])
        long_paraphrase = (SCREENSHOT_TURN1_PARAPHRASE + " ") * 20
        self.assertGreaterEqual(len(long_paraphrase), 1500)
        self.assertFalse(answer_needs_expansion(long_paraphrase, query=SCREENSHOT_TURN1))

    def test_sources_ui_can_show_five_labels_without_quoting_notes(self):
        docs = [
            _doc("faith given at birth teaching", source="faith.pdf", title="Walking in Faith"),
            _doc("airplane elevator driving examples of trust", source="trust.pdf", title="Everyday Trust"),
            _doc("blessings from God when we believe", source="blessing.pdf", title="Blessings of God"),
            _doc("Hebrews 11:1 now faith is the substance", source="nkjv-bible.pdf", title="NKJV Bible"),
            _doc(
                "video clip about using faith like boarding a plane",
                source="may_23.mp4",
                title="May 23",
                content_type="video_transcript",
                timestamp="08:50–09:30",
            ),
        ]

        def label(doc):
            meta = doc.metadata
            name = meta.get("title") or meta["source"]
            ts = meta.get("timestamp")
            return f"{name} [{ts}]" if ts else name

        cited = sources_cited_in_answer(docs, SCREENSHOT_TURN1_PARAPHRASE, label)
        self.assertEqual(cited, [])
        mixed = ensure_source_media_mix(
            [],
            docs,
            label,
            min_count=3,
            limit=5,
            query=SCREENSHOT_TURN1,
        )
        self.assertGreaterEqual(len(mixed), 3)
        self.assertLessEqual(len(mixed), 5)

    def test_format_notes_would_inject_labels_if_docs_retrieved(self):
        docs = [
            _doc(
                'Pastor Don said, "Faith is a tool given at birth." Board a plane, ride an elevator.',
                source="faith.pdf",
                title="Walking in Faith",
            ),
        ]
        notes = format_reference_notes(docs, lambda doc: doc.metadata["title"], max_chars=4000)
        self.assertIn("[Note 1 | Walking in Faith]", notes)
        self.assertIn("given at birth", notes)
        self.assertIn("elevator", notes)


if __name__ == "__main__":
    unittest.main()
