import random
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.chat_retrieval import (
    INTENT_APPLY,
    INTENT_CLARIFY,
    INTENT_NEW_ANGLE,
    INTENT_NEW_TOPIC,
    apply_retrieval_threshold,
    bible_book_key,
    classify_followup_intent,
    ensure_source_media_mix,
    expand_search_queries,
    extract_used_headings,
    extract_used_quotes,
    extract_used_verse_refs,
    filter_hits_by_topic,
    format_reference_notes,
    is_bible_source,
    is_strong_title_match,
    is_video_chunk,
    keyword_search_query,
    looks_like_followup,
    looks_like_format_followup,
    looks_like_library_pull,
    pin_docs_to_strong_title_matches,
    restrict_docs_to_primary_source,
    retain_title_matches,
    merge_scored_hits,
    query_focus_tokens,
    looks_like_bible_query,
    search_queries_on_store,
    select_chat_source_chips,
    select_diverse_docs,
    source_chip_relevance_score,
    title_overlap_score,
    topic_anchor_query,
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
        self.assertTrue(queries[0].lower().startswith("gay"), queries)
        self.assertTrue(any("clarify" in item.lower() for item in queries))
        self.assertGreaterEqual(len(queries), 2)

    def test_followup_query_leads_with_prior_topic(self):
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
        self.assertTrue(queries[0].lower().startswith("gay"), queries)

    def test_expand_week_one_leads_with_marriage(self):
        prior = (
            "I'd like to develop a sermon series on marriage. I need 3 weeks "
            "worth of content. What should be main topics each week?"
        )
        current = "Can you expand on week one and back up each point with scripture?"
        queries = expand_search_queries(
            current,
            [prior],
            prior_ai_texts=[
                "**Week 1: Understanding Biblical Marriage**\n"
                "- Definition: a covenant between a man and a woman.\n"
                "- Purpose: reflect God's love.\n"
                "- Roles: complementary responsibilities.\n"
            ],
        )
        self.assertTrue(queries)
        self.assertIn("marriage", queries[0].lower())
        joined = " | ".join(queries).lower()
        self.assertIn("marriage", joined)
        self.assertTrue(
            any(
                token in joined
                for token in ("definition", "purpose", "roles", "covenant")
            ),
            queries,
        )
        anchor = topic_anchor_query(current, [prior])
        self.assertIn("marriage", anchor.lower())
        self.assertIn("week one", anchor.lower())

    def test_topic_anchor_keeps_opening_question_after_later_turns(self):
        anchor = topic_anchor_query(
            "What topic did we start this chat with?",
            [
                "How should a believer walk in humility like Jesus washing the disciples feet?",
                "Give me a 3 point sermon on that topic.",
                "Recap the original humility teaching in four sentences.",
            ],
        )
        lowered = anchor.lower()
        self.assertIn("washing", lowered)
        self.assertIn("humility", lowered)
        self.assertIn("what topic did we start", lowered)

    def test_followup_quote_ask_still_anchors_to_prior_topic(self):
        queries = expand_search_queries(
            "Can you give me quotes from Pastor Don for week one?",
            ["I'd like to develop a sermon series on marriage."],
        )
        joined = " | ".join(queries).lower()
        self.assertIn("marriage", joined)
        self.assertTrue(any("pastor don" in item.lower() and "marriage" in item.lower() for item in queries), queries)

    def test_first_turn_embeds_topic_not_the_full_prompt(self):
        queries = expand_search_queries("What should I say to someone who is gay?")
        joined = " | ".join(queries).lower()
        self.assertTrue(queries[0].lower() == "gay" or queries[0].lower().startswith("gay"), queries)
        self.assertIn("gay", joined)
        self.assertTrue(any("gay" in item.lower() and "pastor don" in item.lower() for item in queries))
        self.assertFalse(any("what should i say" in item.lower() for item in queries), queries)

    def test_new_topic_embeds_current_question_not_prior_purpose(self):
        queries = expand_search_queries(
            "What does Pastor Don teach about faith?",
            ["What is my purpose in God's plan?"],
        )
        self.assertTrue(queries)
        self.assertIn("faith", queries[0].lower())
        self.assertNotIn("purpose", queries[0].lower())
        from core.chat_retrieval import current_carries_new_topic, topic_anchor_query

        self.assertTrue(
            current_carries_new_topic(
                "What does Pastor Don teach about faith?",
                "What is my purpose in God's plan?",
            )
        )
        anchor = topic_anchor_query(
            "What does Pastor Don teach about faith?",
            ["What is my purpose in God's plan?", "Quote Pastor Don about that purpose."],
        )
        self.assertIn("faith", anchor.lower())
        self.assertNotIn("purpose", anchor.lower())

    def test_grieving_followup_embeds_grief_not_prior_prayer_only(self):
        current = (
            "How should I pray when I am grieving, based on Pastor Don's teaching "
            "and what we already discussed?"
        )
        queries = expand_search_queries(
            current,
            ["Quote Pastor Don about prayer."],
        )
        joined = " | ".join(queries).lower()
        self.assertTrue(queries)
        self.assertTrue(
            "griev" in queries[0].lower() or "grief" in queries[0].lower(),
            queries,
        )
        self.assertIn("comfort", joined)
        grief = _doc(
            "Sit with the grieving and weep with those who weep, then comfort them in prayer.",
            source="grief.pdf",
            title="Comfort the Grieving",
        )
        repentance = _doc(
            "If My people who are called by My name will humble themselves and pray "
            "and turn from their wicked ways I will forgive their sin.",
            source="prayer.pdf",
            title="If My People Pray",
        )
        kept = filter_hits_by_topic(
            [(repentance, 0.95), (grief, 0.80)],
            current,
            retrieval_k=6,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertEqual(sources, ["grief.pdf"])

    def test_library_pull_embeds_topic_not_pull_up_a_sermon(self):
        self.assertTrue(looks_like_library_pull("Pull up a sermon in the sermon library about faith"))
        self.assertFalse(looks_like_library_pull("What does Pastor Don teach about faith?"))
        queries = expand_search_queries(
            "Pull up a sermon in the sermon library about faith",
            limit=7,
        )
        joined = " | ".join(queries).lower()
        self.assertIn("faith", joined)
        self.assertTrue(queries[0].lower() == "faith" or queries[0].lower().startswith("faith"), queries)
        self.assertFalse(any("pull" in item.lower() for item in queries), queries)
        self.assertFalse(any("library" in item.lower() for item in queries), queries)

    def test_library_pull_keeps_one_sermon_source(self):
        docs = [
            _doc("Heart intro about summer and vacation.", source="heart.pdf"),
            _doc(
                "Faith and fire: the whistle should mean the train is coming because "
                "the same power that blew the whistle will pull the train.",
                source="fire.pdf",
            ),
            _doc("Nehemiah surveyed the difficulties.", source="preparing.pdf"),
            _doc("NKJV Psalm 121:1", source="nkjv-bible.pdf"),
        ]
        kept = restrict_docs_to_primary_source(
            docs,
            topic="faith",
            is_bible=lambda doc: "bible" in doc.metadata["source"],
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = {doc.metadata["source"] for doc in kept}
        self.assertEqual(sources, {"fire.pdf", "nkjv-bible.pdf"})

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
            intent=INTENT_CLARIFY,
            prior_user_query="What should I say to someone who is gay?",
            used_headings=["Affirm Their Worth"],
            banned_titles=["He Is God"],
        )
        self.assertIn("SAME chat", text)
        self.assertIn("gay", text.lower())
        self.assertIn("do not reprint the previous heading", text.lower())
        self.assertIn("Affirm Their Worth", text)
        self.assertIn("He Is God", text)
        self.assertIn("Genesis 1:27", text)

    def test_uniqueness_new_angle_bans_prior_outline(self):
        text = uniqueness_instruction(
            [],
            [],
            is_followup=True,
            intent=INTENT_NEW_ANGLE,
            prior_user_query="My kid saw a dog get hit by a car near the kitchen.",
            used_headings=["He Is God"],
            banned_titles=["He Is God"],
        )
        self.assertIn("Answer THIS new question", text)
        self.assertIn("Do not reuse the previous heading", text)
        self.assertIn("He Is God", text)
        self.assertIn("kitchen", text.lower())

    def test_classify_followup_intent_new_angle_and_topic_break(self):
        prior = ["My kid saw a dog get hit by a car near the kitchen. What should I say?"]
        prior_ai = [
            "**He Is God**\n\n"
            "- Acknowledge the Pain: sit with them.\n"
            "- Stay Present: do not rush the moment.\n"
        ]
        self.assertEqual(
            classify_followup_intent(
                "How do I reassure my kid even if I am overwhelmed?",
                prior,
                prior_ai,
            ),
            INTENT_NEW_ANGLE,
        )
        self.assertEqual(
            classify_followup_intent("What is communion?", prior, prior_ai),
            INTENT_NEW_TOPIC,
        )
        self.assertEqual(
            classify_followup_intent("What should I say tonight in the kitchen?", prior, prior_ai),
            INTENT_APPLY,
        )
        self.assertEqual(
            classify_followup_intent("Can you further clarify that guidance?", prior, prior_ai),
            INTENT_CLARIFY,
        )
        self.assertEqual(
            classify_followup_intent("How do I reassure my kid even if I am overwhelmed?", []),
            INTENT_NEW_TOPIC,
        )

    def test_screenshot_three_point_sermon_recasts_faith_not_communion(self):
        prior = ["Recount what Pastor Don believes about faith?"]
        recast = "Give me a 3 point sermon on that topic"
        communion = "Give me a 3 point sermon on communion"
        self.assertTrue(looks_like_format_followup(recast))
        self.assertTrue(looks_like_followup(recast))
        self.assertFalse(looks_like_format_followup(communion))
        self.assertEqual(
            classify_followup_intent(recast, prior, ["Pastor Don teaches that faith trusts God."]),
            INTENT_NEW_ANGLE,
        )
        self.assertEqual(
            classify_followup_intent(communion, prior, ["Pastor Don teaches that faith trusts God."]),
            INTENT_NEW_TOPIC,
        )
        self.assertFalse(keyword_search_query(recast))
        self.assertNotIn("point", keyword_search_query(recast).lower())
        self.assertIn("communion", keyword_search_query(communion).lower())
        self.assertNotIn("point", keyword_search_query(communion).lower())
        queries = expand_search_queries(recast, prior_user_queries=prior)
        joined = " | ".join(queries).lower()
        self.assertIn("faith", joined)
        self.assertTrue(queries[0].lower().find("faith") >= 0, queries)
        self.assertFalse(any("point" in item.lower().split() for item in queries), queries)

    def test_extract_used_headings_from_markdown(self):
        headings = extract_used_headings(
            [
                "**He Is God**\n\n"
                "Pastor Don teaches compassion.\n\n"
                "- Acknowledge the Pain: sit with them.\n"
                "- Stay Present: stay in the room.\n"
            ]
        )
        lowered = [item.lower() for item in headings]
        self.assertTrue(any("he is god" in item for item in lowered), headings)
        self.assertTrue(any("acknowledge the pain" in item for item in lowered), headings)

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

    def test_parenting_notes_are_not_hosea_prayer_sermon(self):
        from core.chat_retrieval import (
            filter_hits_by_topic,
            required_topic_core_tokens,
            required_topic_synonyms,
        )

        query = "Create sermon notes on parenting and raising children."
        required = required_topic_synonyms(query)
        self.assertTrue(any("parent" in item for item in required), required)
        self.assertNotIn("children", required)
        cores = required_topic_core_tokens(query)
        self.assertIn("parenting", cores)
        self.assertNotIn("parent", cores)
        self.assertNotIn("children", cores)
        parenting = _doc(
            "Parents must raise children with consistent discipline and model the faith at home.",
            source="parenting.pdf",
            title="Home Improvement Parenting",
        )
        hosea_prayer = _doc(
            "Go and marry a prostitute, so some of her children will be born to you from other men. "
            "Hosea prayed persistently for Gomer and visualized her salvation.",
            source="prayers-lost.pdf",
            title="Prayers That Prevail for the Lost",
        )
        kept = filter_hits_by_topic(
            [(hosea_prayer, 0.94), (parenting, 0.81)],
            query,
            retrieval_k=6,
        )
        sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertEqual(sources, ["parenting.pdf"])

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
        self.assertIn("[Note 1 | SERMON (Pastor Don / Susan) | Walking in Love]", notes)
        self.assertIn("[Note 2 | SCRIPTURE (NKJV) | NKJV Bible]", notes)
        self.assertIn("First chunk", notes)

    def test_format_notes_tags_god_speech_inside_sermon(self):
        docs = [
            _doc(
                "God has a plan for your life. Before you were born, I sanctified you "
                "and appointed you as My spokesman to the world. Stay faithful.",
                source="purpose.pdf",
                title="Purpose",
            )
        ]
        notes = format_reference_notes(docs, lambda doc: doc.metadata["title"], max_chars=4000)
        self.assertIn("SERMON (Pastor Don / Susan)", notes)
        self.assertIn("not Pastor Don", notes)
        self.assertIn("Before you were born, I sanctified you", notes)

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

    def test_title_overlap_prefers_named_sermon_over_generic_community(self):
        canonical = _doc(
            "Faith works with hope and patience until the promise comes.",
            source="Works_Hope_Faith_Patience.pdf",
            title="Works Hope Faith & Patience",
        )
        community = _doc(
            "Faith hope and patience show up in community life together "
            "as we love one another and stay contagious in our witness.",
            source="community.pdf",
            title="Community",
        )
        contagious = _doc(
            "Faith and hope keep Christianity contagious when we wait with patience.",
            source="contagious.pdf",
            title="Contagious Christianity",
        )
        query = "What does Pastor Don teach about faith hope and patience?"
        focus = query_focus_tokens(query)
        self.assertGreaterEqual(title_overlap_score(canonical, focus), 0.5)
        self.assertLess(title_overlap_score(community, focus), 0.34)
        self.assertLess(title_overlap_score(contagious, focus), 0.34)

        selected = select_diverse_docs(
            [(community, 0.94), (contagious, 0.93), (canonical, 0.71)],
            k=6,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
            query=query,
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertIn("Works_Hope_Faith_Patience.pdf", sources)

        labels = ensure_source_media_mix(
            ["Community"],
            [community, contagious, canonical],
            lambda doc: doc.metadata["title"],
            min_count=3,
            limit=5,
            query=query,
        )
        self.assertIn("Works Hope Faith & Patience", labels)

    def test_title_overlap_prefers_prayer_barriers_sermon(self):
        canonical = _doc(
            "Unforgiveness and unbelief are prayer barriers that choke faith.",
            source="Prayer_Barriers.pdf",
            title="Prayer Barriers",
        )
        community = _doc(
            "Prayer in community keeps the church contagious and connected.",
            source="community.pdf",
            title="Community",
        )
        harvest = _doc(
            "Prayer and harvest go together when we ask the Lord of the harvest.",
            source="harvest.pdf",
            title="Harvest",
        )
        query = "What are the prayer barriers Pastor Don teaches about?"
        focus = query_focus_tokens(query)
        self.assertTrue(is_strong_title_match(canonical, focus))
        self.assertFalse(is_strong_title_match(community, focus))
        selected = select_diverse_docs(
            [(community, 0.95), (harvest, 0.90), (canonical, 0.70)],
            k=6,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
            query=query,
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertIn("Prayer_Barriers.pdf", sources)
        self.assertNotIn("community.pdf", sources)
        self.assertNotIn("harvest.pdf", sources)

        kept = retain_title_matches(
            [(community, 0.95), (harvest, 0.90), (canonical, 0.70)],
            [(community, 0.95), (harvest, 0.90)],
            query,
        )
        kept_sources = [doc.metadata["source"] for doc, _score in kept]
        self.assertIn("Prayer_Barriers.pdf", kept_sources)
        self.assertEqual(kept_sources[0], "Prayer_Barriers.pdf")

    def _prayer_catalog(self):
        """Live-like retrieved set: C-titles first (high embedding), titled sermons later."""
        return [
            _doc(
                "Community life in the church body as we gather and love one another.",
                source="community.pdf",
                title="Community",
            ),
            _doc(
                "Contagious Christianity outreach notes for the city.",
                source="contagious.pdf",
                title="Contagious Christianity",
            ),
            _doc(
                "Christian boundaries for dating and friendship in the church.",
                source="boundaries.pdf",
                title="Christian Boundaries",
            ),
            _doc(
                "Fasting and prayer notes for seeking God with a clean heart.",
                source="fasting.pdf",
                title="Fasting and Prayer",
            ),
            _doc(
                "Filled by the Spirit teaching for daily Christian living.",
                source="filled.pdf",
                title="Filled by the Spirit",
            ),
            _doc(
                "In the beginning God created the heaven and the earth.",
                source="nkjv-bible.pdf",
                title="NKJV",
            ),
            _doc(
                "Unforgiveness and unbelief are prayer barriers that choke faith.",
                source="PRAYER BARRIERS.pdf",
                title="Prayer Barriers",
            ),
            _doc(
                "Alcohol and the Christian walk from Pastor Don's notes.",
                source="THE CHRISTIAN AND ALCOHOL.pdf",
                title="The Christian and Alcohol",
            ),
            _doc(
                "Why receive the Holy Spirit as a gift after salvation.",
                source="WHY RECEIVE THE HOLY SPIRIT.pdf",
                title="Why Receive the Holy Spirit",
            ),
            _doc(
                "Faith works with hope and patience until the promise comes.",
                source="Works, Hope, Faith & Patience.pdf",
                title="Works, Hope, Faith & Patience",
            ),
        ]

    def test_az_fill_no_longer_drops_prayer_barriers(self):
        query = "What are the prayer barriers Pastor Don teaches about?"
        docs = self._prayer_catalog()
        az_titles = sorted(doc.metadata["title"] for doc in docs)
        self.assertEqual(
            az_titles[:5],
            [
                "Christian Boundaries",
                "Community",
                "Contagious Christianity",
                "Fasting and Prayer",
                "Filled by the Spirit",
            ],
        )
        self.assertNotIn("Prayer Barriers", az_titles[:5])

        answer = (
            "Pastor Don teaches that unforgiveness and unbelief hinder prayer "
            "and keep the believer from receiving."
        )
        labels = select_chat_source_chips(
            docs,
            answer,
            lambda doc: doc.metadata["title"],
            min_count=3,
            limit=5,
            query=query,
            rng=random.Random(0),
        )
        self.assertIn("Prayer Barriers", labels)
        self.assertGreaterEqual(len(labels), 3)
        self.assertLessEqual(len(labels), 5)
        self.assertNotIn("NKJV", labels)

        # Old views.py path: every retrieved title, sorted A–Z, passed as preferred.
        az_preferred = ensure_source_media_mix(
            az_titles,
            docs,
            lambda doc: doc.metadata["title"],
            min_count=3,
            limit=5,
            query=query,
            rng=random.Random(0),
        )
        self.assertIn("Prayer Barriers", az_preferred)
        self.assertNotEqual(az_preferred, az_titles[:5])

    def test_strong_title_match_is_selected_for_source_chips(self):
        query = "What are the prayer barriers Pastor Don teaches about?"
        docs = self._prayer_catalog()
        focus = query_focus_tokens(query)
        prayer = next(doc for doc in docs if doc.metadata["title"] == "Prayer Barriers")
        community = next(doc for doc in docs if doc.metadata["title"] == "Community")
        self.assertTrue(is_strong_title_match(prayer, focus))
        self.assertFalse(is_strong_title_match(community, focus))
        self.assertGreater(
            source_chip_relevance_score(prayer, query, retrieval_rank=6, n_docs=10),
            source_chip_relevance_score(community, query, retrieval_rank=0, n_docs=10),
        )
        labels = select_chat_source_chips(
            docs,
            "Here is an outline on hindrances to answered prayer.",
            lambda doc: doc.metadata["title"],
            query=query,
            rng=random.Random(7),
        )
        self.assertIn("Prayer Barriers", labels)

    def test_source_chips_random_among_relevant_not_always_community(self):
        query = "What are the prayer barriers Pastor Don teaches about?"
        docs = self._prayer_catalog()
        answer = "Unforgiveness and unbelief choke faith when we pray."
        prayer_hits = 0
        community_hits = 0
        unique_sets = set()
        for seed in range(40):
            labels = select_chat_source_chips(
                docs,
                answer,
                lambda doc: doc.metadata["title"],
                min_count=3,
                limit=5,
                query=query,
                rng=random.Random(seed),
            )
            unique_sets.add(tuple(labels))
            if "Prayer Barriers" in labels:
                prayer_hits += 1
            if "Community" in labels:
                community_hits += 1
            self.assertNotIn("NKJV", labels)
            self.assertGreaterEqual(len(labels), 3)
            self.assertLessEqual(len(labels), 5)
        self.assertGreaterEqual(prayer_hits, 36, (prayer_hits, unique_sets))
        self.assertLess(community_hits, prayer_hits)
        self.assertLess(community_hits, 40, "Community must not occupy a slot on every draw")
        self.assertGreaterEqual(len(unique_sets), 2)

    def test_nkjv_does_not_fill_sermon_chips_for_sermon_question(self):
        query = "What are the prayer barriers Pastor Don teaches about?"
        docs = self._prayer_catalog()
        self.assertFalse(looks_like_bible_query(query))
        labels = select_chat_source_chips(
            docs,
            "Prayer is hindered by unforgiveness.",
            lambda doc: doc.metadata["title"],
            query=query,
            rng=random.Random(3),
        )
        self.assertNotIn("NKJV", labels)
        lowered = " ".join(labels).lower()
        self.assertNotIn("king james", lowered)
        self.assertNotIn("nkjv", lowered)

        bible_query = "What does John 3:16 say in the NKJV?"
        self.assertTrue(looks_like_bible_query(bible_query))
        bible_labels = select_chat_source_chips(
            docs,
            "John 3:16 says God so loved the world.",
            lambda doc: doc.metadata["title"],
            min_count=3,
            limit=5,
            query=bible_query,
            rng=random.Random(3),
        )
        self.assertIn("NKJV", bible_labels)

    def test_pin_docs_drops_loosely_related_sermons_when_title_matches(self):
        church = _doc(
            "This church is a big deal because gifts grow here for evangelism.",
            source="this-church.pdf",
            title="This Church Is a Big Deal",
        )
        community = _doc(
            "The church should be a place of forgiveness, mercy, and harvest.",
            source="community.pdf",
            title="Community",
        )
        five_fold = _doc(
            "The five fold church equips saints for ministry.",
            source="five-fold.pdf",
            title="Five Fold Church",
        )
        nkjv = _doc(
            "For God so loved the world that He gave His only begotten Son.",
            source="nkjv-bible.pdf",
            title="New King James Version",
        )
        query = "Why does Pastor Don say this church is a big deal?"
        pinned = pin_docs_to_strong_title_matches(
            [community, church, five_fold, nkjv],
            query,
            candidate_hits=[(community, 0.95), (five_fold, 0.9), (church, 0.72), (nkjv, 0.8)],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = [doc.metadata["source"] for doc in pinned]
        self.assertEqual(sources, ["this-church.pdf"])

    def test_pin_docs_keeps_multiple_sermons_when_no_title_match(self):
        weariness = _doc(
            "Do not grow weary in doing good to the household of faith.",
            source="weariness.pdf",
            title="Weariness",
        )
        community = _doc(
            "Love one another in community as a witness to the world.",
            source="community.pdf",
            title="Community",
        )
        query = "What does Pastor Don teach about love?"
        kept = pin_docs_to_strong_title_matches(
            [weariness, community],
            query,
            candidate_hits=[(community, 0.94), (weariness, 0.80)],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = [doc.metadata["source"] for doc in kept]
        self.assertEqual(set(sources), {"weariness.pdf", "community.pdf"})

    def test_select_diverse_docs_stops_filling_after_strong_title_match(self):
        canonical = _doc(
            "This church is a big deal because evangelism and gifts grow here.",
            source="this-church.pdf",
            title="This Church Is a Big Deal",
        )
        extra_chunk = _doc(
            "The local church develops spiritual gifts for world evangelism.",
            source="this-church.pdf",
            title="This Church Is a Big Deal",
        )
        community = _doc(
            "The church is a place of forgiveness and harvest in community.",
            source="community.pdf",
            title="Community",
        )
        selected = select_diverse_docs(
            [(community, 0.96), (canonical, 0.74), (extra_chunk, 0.73)],
            k=8,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
            query="Why does Pastor Don say this church is a big deal?",
        )
        sources = [doc.metadata["source"] for doc in selected]
        self.assertTrue(sources)
        self.assertTrue(all(src == "this-church.pdf" for src in sources), sources)

    def test_followup_pin_query_does_not_collapse_to_prior_sermon(self):
        prayer = _doc(
            "Unforgiveness and unbelief are prayer barriers that choke faith.",
            source="PRAYER BARRIERS.pdf",
            title="Prayer Barriers",
        )
        community = _doc(
            "Community life in the church body as we gather and love one another.",
            source="community.pdf",
            title="Community",
        )
        blend = (
            "What barriers to prayer does Pastor Don talk about? "
            "Which of those barriers should someone deal with first?"
        )
        follow = "Which of those barriers should someone deal with first, based on what you just said?"
        kept = pin_docs_to_strong_title_matches(
            [community, prayer],
            blend,
            pin_query=follow,
            candidate_hits=[(community, 0.94), (prayer, 0.80)],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        sources = {doc.metadata["source"] for doc in kept}
        self.assertEqual(sources, {"community.pdf", "PRAYER BARRIERS.pdf"})

        selected = select_diverse_docs(
            [(community, 0.94), (prayer, 0.80)],
            k=6,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
            query=blend,
            pin_query=follow,
        )
        selected_sources = {doc.metadata["source"] for doc in selected}
        self.assertIn("PRAYER BARRIERS.pdf", selected_sources)
        self.assertIn("community.pdf", selected_sources)

        labels = select_chat_source_chips(
            [community, prayer],
            "Start with unconfessed sin as listed above.",
            lambda doc: doc.metadata["title"],
            min_count=3,
            limit=5,
            query=blend,
            rng=__import__("random").Random(1),
        )
        self.assertIn("Prayer Barriers", labels)

    def test_topic_change_still_pins_new_filename(self):
        church = _doc(
            "This church is a big deal because it is a house of mercy.",
            source="this-church.pdf",
            title="This Church Is a Big Deal",
        )
        tithe = _doc(
            "Tithing is the first key to abundance with a good attitude.",
            source="abundance.pdf",
            title="Stop Tithing",
        )
        pinned = pin_docs_to_strong_title_matches(
            [church, tithe],
            "Why does Pastor Don say this church is a big deal? Why should a Christian stop tithing?",
            pin_query="Why should a Christian stop tithing?",
            candidate_hits=[(church, 0.9), (tithe, 0.8)],
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        self.assertEqual([doc.metadata["source"] for doc in pinned], ["abundance.pdf"])


if __name__ == "__main__":
    unittest.main()
