import unittest

from .chat_system_prompt import (
    CONTINUE_STEER,
    FINISH_STEER,
    FOLLOWUP_STEER,
    OPENING_RECALL_STEER,
    MAX_EXPANSION_PASSES,
    MIN_TEACHING_CHARS,
    MIN_TEACHING_WORDS,
    TARGET_TEACHING_CHARS,
    answer_looks_incomplete,
    answer_needs_expansion,
    biblical_characters_instruction,
    build_chat_system_prompt,
    find_biblical_character_names,
    format_opening_recall_steer,
    looks_like_brief_social,
    looks_like_opening_recall,
    query_expects_long_answer,
)
from .document_cleanup import (
    clean_extracted_document,
    clean_markdown_document,
    format_cleanup_log,
)
from .scope_gate import always_in_scope_query, parse_scope_gate_response
from .website_crawl.crawler import normalize_url, path_is_excluded
from .website_crawl.extract import (
    classify_content_type,
    host_allowed_for_page,
    html_to_markdown,
    source_name_for_url,
)


class ChatSystemPromptTests(unittest.TestCase):
    def test_finds_biblical_character_names(self):
        names = find_biblical_character_names("What did Moses and Timothy teach about faith?")
        lowered = {n.lower() for n in names}
        self.assertIn("moses", lowered)
        self.assertIn("timothy", lowered)

    def test_skips_people_as_biblical_name(self):
        names = find_biblical_character_names("Can gay people be Christians?")
        lowered = {n.lower() for n in names}
        self.assertNotIn("people", lowered)
        self.assertEqual(names, [])

    def test_skips_christian_demonym(self):
        names = find_biblical_character_names("Can Christians drink alcohol like Moses?")
        lowered = {n.lower() for n in names}
        self.assertNotIn("christians", lowered)
        self.assertIn("moses", lowered)

    def test_no_biblical_names_when_absent(self):
        self.assertEqual(find_biblical_character_names("How should pastors prepare a sermon?"), [])

    def test_prompt_requires_sermon_notes(self):
        prompt = build_chat_system_prompt(biblical_names=["Moses"])
        self.assertIn("Susan Nordin", prompt)
        self.assertIn("sermon notes", prompt)
        self.assertIn("REFERENCE NOTES", prompt)
        self.assertNotIn("QUOTE IDS", prompt)
        self.assertNotIn("{{Q1}}", prompt)
        self.assertNotIn("{{V1}}", prompt)
        self.assertNotIn("{{Q#}}", FINISH_STEER)
        self.assertNotIn("{{V#}}", FINISH_STEER)
        self.assertIn("Social issues are in scope", prompt)
        self.assertIn("abortion", prompt.lower())
        self.assertIn("Do not say you must redirect", prompt)
        self.assertNotIn("Never say notes were not found", prompt)
        self.assertIn("nearest-neighbor sermons", prompt)
        self.assertIn("Do not invent extra-biblical historians", prompt)
        self.assertIn("say the notes do not cover that subject", prompt)
        self.assertIn("No relevant sermon notes found", prompt)
        self.assertIn("Let the user's question and the notes decide", prompt)
        self.assertIn("Write the way Pastor Don and Susan preach", prompt)
        self.assertIn("Do not write like a generic modern assistant", prompt)
        self.assertNotIn("the way a modern assistant would", prompt)
        self.assertIn("Match the user's requested layout", prompt)
        self.assertIn("labeled points", prompt)
        self.assertIn("Do not invent extra points", prompt)
        self.assertIn("From the retrieved notes", prompt)
        self.assertNotIn("Do not wait for the user to ask for quotations or Scripture", prompt)
        self.assertNotIn("at least two word-for-word quotation-marked excerpts", prompt)
        self.assertIn("Every idea in the reply must come from REFERENCE NOTES", prompt)
        self.assertIn("Do not fill the gap from general Christian knowledge", prompt)
        self.assertIn("pastoral advice that is not in the notes", prompt)
        self.assertNotIn("headings, categories, or pastoral advice", prompt)
        self.assertNotIn("Use Markdown sparingly", prompt)
        self.assertNotIn("natural paragraphs, direct and", prompt)
        self.assertIn("Skipping quotations and Scripture citations is correct", prompt)
        self.assertIn("Never attribute Scripture", prompt)
        self.assertIn("communion excerpts", prompt.lower())
        self.assertIn("happiness headings", prompt.lower())
        self.assertIn("homosexuality", prompt.lower())
        self.assertIn("Use Pastor Don's and Susan's speaking style", prompt)
        self.assertIn("Do not flatten it into a generic Christian pastoral tone", prompt)
        self.assertNotIn("do not imitate Pastor Don", prompt)
        self.assertIn("REQUIRED TEACHING POINTS", prompt)
        self.assertIn("LGBTQ inclusion frame", prompt)
        self.assertIn("Romans 14 liberty", prompt)
        self.assertIn("Cover every numbered point", prompt)
        self.assertIn("labeled Markdown points", prompt)
        self.assertNotIn("first sentence must paraphrase point 1", prompt)
        self.assertIn("Do not begin by saying gay people can be Christians", prompt)
        self.assertIn("NKJV lines in REFERENCE NOTES support the sermon notes", prompt)
        self.assertIn("REQUIRED TEACHING POINTS", CONTINUE_STEER)
        self.assertIn("REFERENCE NOTES", CONTINUE_STEER)
        self.assertIn("You may use paragraphs, bullets, or headings", CONTINUE_STEER)
        self.assertNotIn("Do not add theology, headings", CONTINUE_STEER)
        self.assertIn("REQUIRED TEACHING POINTS", FINISH_STEER)
        self.assertNotIn("bold headings", FINISH_STEER)
        self.assertNotIn("Do not add new headings, categories, verses, or advice.", FINISH_STEER)
        self.assertIn("Follow-up turns may expand the last answer", prompt)
        self.assertIn("Do not invent a recap", FOLLOWUP_STEER)
        self.assertNotIn("2000 characters", prompt)
        self.assertNotIn("<length_close>", prompt)
        self.assertNotIn("LENGTH (teaching answers):", prompt)
        self.assertNotIn("Follow-up turns must use new {{Q#}}", prompt)
        self.assertNotIn("Do not reuse a quote ID or NKJV ID", prompt)
        self.assertNotIn("a one-sentence reply is a failed answer", prompt)
        self.assertIn("CASUAL CONVERSATION EXCEPTION", prompt)
        self.assertIn("Do not pull sermon quotes", prompt)
        self.assertIn("Do not volunteer phone/email on ordinary greetings", prompt)
        self.assertEqual(TARGET_TEACHING_CHARS, 2000)
        self.assertEqual(MIN_TEACHING_CHARS, 1500)
        self.assertEqual(MIN_TEACHING_WORDS, 250)
        self.assertEqual(MAX_EXPANSION_PASSES, 1)
        self.assertTrue(query_expects_long_answer(
            "According to Pastor Don's sermons, what is the main purpose of the church?"
        ))
        self.assertTrue(query_expects_long_answer(
            "Summarize his view of the Holy Spirit's work in conversion."
        ))
        self.assertFalse(query_expects_long_answer("Thanks!"))
        self.assertTrue(looks_like_brief_social("Hello how are you today?"))
        self.assertTrue(looks_like_brief_social("Hi"))
        self.assertFalse(looks_like_brief_social(
            "According to Pastor Don's sermons, what is the main purpose of the church?"
        ))
        self.assertFalse(query_expects_long_answer("Hello how are you today?"))
        self.assertTrue(looks_like_opening_recall("What topic did we start this chat with?"))
        self.assertTrue(looks_like_opening_recall("What Bible story did we start this chat with?"))
        self.assertFalse(looks_like_opening_recall("Teach on Esther standing before the king."))
        self.assertFalse(query_expects_long_answer("What topic did we start this chat with?"))
        self.assertIn("{opening}", OPENING_RECALL_STEER)
        self.assertIn("Esther standing before the king", format_opening_recall_steer(
            "Teach on Esther standing before the king."
        ))
        self.assertNotIn("{opening}", format_opening_recall_steer("Teach on Esther."))
        short = (
            "According to Pastor Don's sermon, the main purpose of the church is to "
            "feed the flock spiritually, as emphasized in John 21:15-17."
        )
        filler = [
            f"Pastoral point {index}: love God, love people, and keep the gospel first in this church body."
            for index in range(40)
        ]
        mid = " ".join(filler)[:1200]
        long_enough = (" ".join(filler) + " This is the closing sentence.")[:1500]
        if not long_enough.endswith("."):
            long_enough = long_enough.rsplit(" ", 1)[0] + "."
        while len(long_enough) < 1500:
            long_enough = "Pastoral counsel for the church. " + long_enough
        self.assertEqual(len(mid), 1200)
        self.assertGreaterEqual(len(long_enough), 1500)
        query = "According to Pastor Don's sermons, what is the main purpose of the church?"
        self.assertTrue(answer_needs_expansion(short, query=query))
        self.assertFalse(answer_needs_expansion(mid, query=query))
        self.assertFalse(answer_needs_expansion(long_enough, query=query))
        concluded = (
            ("Pastoral counsel for the student and parents. " * 24)
            + "\n\nIn conclusion, speak with grace and truth, and pray together."
        )
        self.assertGreaterEqual(len(concluded), 1000)
        self.assertFalse(answer_needs_expansion(concluded, query=query))
        self.assertTrue(answer_needs_expansion(
            short,
            query="Summarize his view of the Holy Spirit's work in conversion.",
        ))
        self.assertFalse(answer_needs_expansion("Thanks for asking — glad to help.", query="Hi"))
        self.assertIn("Moses", biblical_characters_instruction(["Moses"]))
        self.assertIn("No Biblical character names were detected", biblical_characters_instruction([]))

    def test_short_teaching_answer_still_requests_expansion(self):
        query = (
            "According to this pastor's sermons, what is the main purpose of the church? "
            "Quote or closely paraphrase the language he actually uses."
        )
        answer = (
            "According to Pastor Don Nordin, the primary purpose of the church is to serve "
            "as a place where believers can receive ministry and grow spiritually. In one of "
            "his sermons, he illustrates this point through a story about visiting a member "
            "who had stopped attending church. The Pastor found the man sitting by a blazing "
            "fire and noticed that when he isolated one burning ember from the rest, it "
            "quickly died out. However, when placed back among the other embers in the center "
            "of the fire, it regained its strength and warmth. This metaphor emphasizes how "
            "crucial it is for believers to remain connected within their local church "
            "community for ongoing spiritual nourishment and encouragement.\n\n"
            "Churches are ordained by God specifically for ministering to believers and "
            "reaching out to those who do not yet know Christ. As Pastor Don teaches:\n\n"
            '"God ordained the church and fellowship with other believers for the purpose '
            'of ministering to the saints and reaching the world."\n\n'
            "Furthermore, Pastor Don highlights that individuals cannot effectively reach "
            "others if they themselves are not receiving ministry from their local church "
            "community. Therefore, attending church regularly ensures continuous growth and "
            "support essential for living a Christ-centered life."
        )
        self.assertLess(len(answer), MIN_TEACHING_CHARS)
        self.assertGreaterEqual(len(answer.strip()), 800)
        self.assertFalse(answer_needs_expansion(answer, query=query))
        from .chat_system_prompt import continuation_token_budget
        self.assertGreater(continuation_token_budget(answer, completion_tokens=1024), 0)
        self.assertLess(continuation_token_budget(answer, completion_tokens=1024), 400)
        self.assertEqual(continuation_token_budget(("x" * 2299) + ".", completion_tokens=1024), 0)
        brush_off = "The church exists to worship God and love people."
        self.assertTrue(answer_needs_expansion(brush_off, query=query))
        from .chat_system_prompt import should_run_expansion
        self.assertFalse(
            should_run_expansion(brush_off, query, has_retrieved_notes=True)
        )
        self.assertTrue(
            should_run_expansion(brush_off, query, has_retrieved_notes=False)
        )
        self.assertFalse(
            should_run_expansion(answer, query, has_retrieved_notes=False)
        )

    def test_missing_quotes_do_not_trigger_quote_repair(self):
        from .chat_system_prompt import (
            QUOTE_CONTINUE_MIN_TOKENS,
            QUOTE_CONTINUE_STEER,
            answer_missing_required_quotes,
            continuation_token_budget,
            quote_repair_token_budget,
            skip_rewrite_repair,
        )

        query = "Recount what Pastor Don believes about faith?"
        paraphrase = (
            "Pastor Don teaches that faith is trust in God rather than a feeling. "
            * 25
        )
        self.assertGreaterEqual(len(paraphrase.strip()), 800)
        self.assertFalse(answer_needs_expansion(paraphrase, query=query))
        self.assertFalse(
            answer_missing_required_quotes(
                paraphrase, query=query, has_reference_notes=True
            )
        )
        quoted = (
            paraphrase
            + '\n\nPastor Don says, "Faith is the substance of things hoped for in Christ."'
        )
        self.assertFalse(
            answer_missing_required_quotes(
                quoted, query=query, has_reference_notes=True
            )
        )
        self.assertFalse(
            answer_missing_required_quotes(
                paraphrase, query=query, has_reference_notes=False
            )
        )
        self.assertFalse(
            answer_missing_required_quotes(
                paraphrase, query="Hi", has_reference_notes=True
            )
        )
        long_done = ("x" * 2299) + "."
        self.assertEqual(continuation_token_budget(long_done, completion_tokens=1024), 0)
        self.assertGreaterEqual(
            quote_repair_token_budget(long_done, completion_tokens=1024),
            QUOTE_CONTINUE_MIN_TOKENS,
        )
        self.assertLessEqual(
            quote_repair_token_budget(long_done, completion_tokens=1024),
            192,
        )
        self.assertGreaterEqual(
            continuation_token_budget(
                long_done, completion_tokens=1024, min_tokens=QUOTE_CONTINUE_MIN_TOKENS
            ),
            QUOTE_CONTINUE_MIN_TOKENS,
        )
        self.assertIn("Do not invent Pastor Don or Susan quotations", QUOTE_CONTINUE_STEER)
        self.assertIn("Do not add a quotation or verse just to have one", QUOTE_CONTINUE_STEER)
        self.assertIn("Do not say Certainly", QUOTE_CONTINUE_STEER)
        self.assertIn("Do not repeat headings", QUOTE_CONTINUE_STEER)
        self.assertIn("communion or Lord's Table", QUOTE_CONTINUE_STEER)
        self.assertIn("Happiness headings", QUOTE_CONTINUE_STEER)
        self.assertIn("homosexuality or gay-people", QUOTE_CONTINUE_STEER)
        self.assertTrue(skip_rewrite_repair(paraphrase))
        self.assertTrue(skip_rewrite_repair(quoted))
        self.assertFalse(
            answer_missing_required_quotes(
                quoted, query=query, has_reference_notes=True, has_bible_notes=True
            )
        )
        with_verse = quoted + " Hebrews 11:1 says faith is the substance of things hoped for."
        self.assertFalse(
            answer_missing_required_quotes(
                with_verse, query=query, has_reference_notes=True, has_bible_notes=True
            )
        )

    def test_join_continuation_strips_restarted_opening(self):
        from .chat_system_prompt import CONTINUE_STEER, join_continuation

        first = (
            "According to Pastor Don Nordin, the main purpose of the church is to provide "
            "a place where believers can receive ministry and reach out to the world. He "
            "illustrates this through a story about visiting a member of his congregation "
            "who had stopped attending church. During his visit, Pastor Don noticed a fire "
            "burning in the fireplace and used it as a metaphor for the church's role in "
            "nurturing spiritual growth. Just as the lone ember needed to be placed back "
            "into the midst of the other burning coals to reignite its flame, believers "
            "need the warmth and encouragement of the church community to thrive spiritually. "
            "This underscores the importance of fellowship and mutual support within the "
            "local church. As Pastor Don emphasizes, \"We cannot very well reach the world "
            "if we are not receiving ministry from others.\" Therefore, the church serves "
            "as a vital hub for both receiving and distributing divine ministry among its "
            "members and beyond."
        )
        extra = (
            "According to Pastor Don Nordin, the main purpose of the church is to provide "
            "a place where believers can receive ministry and reach out to the world. He "
            "illustrates this through a story about visiting a member of his congregation "
            "who had stopped attending church. During his visit, Pastor Don noticed a fire "
            "burning in the fireplace and used it as a metaphor for the church's role in "
            "nurturing spiritual growth. Just as the lone ember needed to be placed back "
            "into the midst of the other burning coals to reignite its flame, believers "
            "need the warmth and encouragement of the church community to thrive spiritually. "
            "This underscores the importance of fellowship and mutual support within the "
            "local church.\n\n"
            "Moreover, Pastor Don emphasizes the significance of the church as a place "
            "where believers can find authentic connection and support."
        )
        joined = join_continuation(first, extra)
        self.assertTrue(joined.startswith(first))
        self.assertIn("Moreover, Pastor Don emphasizes", joined)
        self.assertEqual(joined.count("the main purpose of the church is to provide"), 1)
        self.assertEqual(join_continuation(first, first), first)
        self.assertEqual(
            join_continuation(first, "Serve one another in the local church body."),
            first + "\n\nServe one another in the local church body.",
        )
        self.assertIn("Do not repeat any sentence already written", CONTINUE_STEER)
        self.assertIn("Do not open with a conversational continuer", CONTINUE_STEER)

    def test_cut_off_mid_sentence_still_requests_expansion(self):
        from .chat_system_prompt import (
            FINISH_STEER,
            answer_looks_incomplete,
            continuation_token_budget,
            join_continuation,
        )

        query = (
            "If Jesus came to our Wednesday potluck, would he sit with the regulars "
            "or the visitors who leave before the closing prayer?"
        )
        cut_off = (
            ("Hospitality reflects God's heart of love and acceptance. " * 40)
            + "The Bible provides numerous examples of Jesus' inclusive behavior. "
            "For instance, in Mark 2:16, Jesus defends His decision to dine with "
            "tax collectors and sinners. Moreover, in John 1"
        )
        self.assertGreaterEqual(len(cut_off), 1500)
        self.assertTrue(answer_looks_incomplete(cut_off))
        self.assertTrue(answer_needs_expansion(cut_off, query=query))
        self.assertGreater(continuation_token_budget(cut_off, completion_tokens=1024), 0)
        self.assertIn("do not replace the draft with a shorter answer", FINISH_STEER)
        self.assertTrue(
            answer_looks_incomplete(
                "speaking in tongues when I was 13 years old. The initial physical "
                "evidence of this baptism was speaking in tongues, which is a powerful "
                "sign of the Holy Spirit's presence and work within a"
            )
        )
        complete_bullets = (
            cut_off.rsplit("Moreover, in John 1", 1)[0]
            + "Welcome every guest as Christ welcomed us.\n\n"
            "- Inclusive attitude: greet regulars and newcomers.\n"
            "- Model Christ's love"
        )
        self.assertFalse(answer_looks_incomplete(complete_bullets))
        joined = join_continuation(cut_off, "1:14 the Word became flesh and dwelt among us.")
        self.assertTrue(joined.startswith(cut_off))
        self.assertIn("1:14 the Word became flesh", joined)
        self.assertNotIn("\n\n", joined[len(cut_off):])
        self.assertFalse(answer_looks_incomplete(
            "In conclusion, welcome every guest as Christ welcomed us."
        ))

    def test_join_continuation_drops_continue_dump(self):
        from .chat_system_prompt import join_continuation, looks_like_continue_dump

        first = (
            "Faith is trusting God's promises, hope waits on His timing, and "
            "patience keeps us from quitting before the harvest. Pastor Don "
            "teaches that these three work together so believers do not faint."
        )
        dumps = [
            "Certainly, let’s continue with more from the notes. Weariness "
            "comes when 44% of the church stops giving and the body grows anemic.",
            "Sure, let's continue. Saul delayed Samuel, and we should fear Him "
            "who can cast into hell, like the unjust judge.",
            "Of course, I'll continue. The target audience was Gentiles, not "
            "the lost sheep of Israel.",
            "Absolutely, continuing with the teaching. Discernment means praying "
            "against cancer rather than answering the alcohol question.",
            "Let's continue with the teaching points. Do not go to the Gentiles "
            "or the Samaritans.",
            "Teaching Points\n1. Community is everything\n2. Contagious Christianity",
        ]
        for extra in dumps:
            self.assertTrue(looks_like_continue_dump(first, extra), extra)
            joined = join_continuation(first, extra)
            self.assertEqual(joined, first, extra)
            self.assertNotIn("Certainly", joined)
            self.assertNotIn("Let’s continue", joined)
            self.assertNotIn("Let's continue", joined)

        moreover = (
            "Moreover, Pastor Don emphasizes that patience is the proof of "
            "hope when the answer is delayed."
        )
        self.assertFalse(looks_like_continue_dump(first, moreover))
        self.assertIn("patience is the proof", join_continuation(first, moreover))

        cut_off = first.rsplit(".", 1)[0] + " so we do not faint before the"
        self.assertTrue(answer_looks_incomplete(cut_off))
        self.assertFalse(
            looks_like_continue_dump(cut_off, "harvest God promised in due season.")
        )

    def test_join_continuation_drops_restated_outline_headers(self):
        from .chat_system_prompt import (
            compact_teaching_answer,
            join_continuation,
        )

        first = (
            "Certainly! Here's a 3-point sermon on the topic of faith based on Pastor Don's teachings:\n\n"
            "**Faith Over Doubt**\n"
            "1*. Faith Sees Beyond Immediate Circumstances\n"
            "Faith operates on a higher plane compared to reality. It sees the unseen "
            "and hopes for what is yet to come.\n"
            "2. Faith Transcends Doubt\n"
            "Faith must surpass the IF FACTOR of doubt and disbelief.\n"
            "3. Faith Receives Divine Blessings\n"
            "Faith is the key to receiving miracles and divine blessings. "
            "Pastor Don teaches that believers receive what God promised because they trust His word "
            "instead of the visible circumstance in front of them.\n\n"
            "By focusing on these points, we can see how faith operates as a powerful force."
        )
        extra = (
            "Faith Over Doubt\n"
            "1. Faith Sees Beyond Immediate Circumstances\n"
            "Faith operates on a higher plane compared to reality. It sees the unseen "
            "and hopes for what is yet to come.\n"
            '"For God so loved the world that He gave His only begotten Son." (John 3:16, NKJV)\n'
            "2. Faith Transcends Doubt\n"
            '"For I am not ashamed of the gospel of Christ." (Romans 1:16, NKJV)\n'
            "3. Faith Receives Divine Blessings\n"
            '"There is no condemnation for those who belong to Christ Jesus." (Romans 8:1, NKJV)'
        )
        joined = join_continuation(first, extra)
        self.assertEqual(joined.lower().count("faith over doubt"), 1, joined)
        self.assertEqual(joined.count("Faith Transcends Doubt"), 1, joined)
        self.assertIn("John 3:16", joined)
        self.assertIn("Romans 1:16", joined)
        recap = (
            first
            + "\n\nHe teaches that faith is the foundation of effective prayer, "
            "much like Noah's faith in building the ark based on God's promise."
        )
        compacted = compact_teaching_answer(recap)
        self.assertNotIn("He teaches that faith is the foundation", compacted)


class ScopeGateParserTests(unittest.TestCase):
    def test_yes_plain(self):
        self.assertIs(parse_scope_gate_response("YES"), True)

    def test_no_plain(self):
        self.assertIs(parse_scope_gate_response("NO"), False)

    def test_yes_with_punctuation(self):
        self.assertIs(parse_scope_gate_response("Yes."), True)

    def test_no_extra_words_defaults_first_token(self):
        self.assertIs(parse_scope_gate_response("NO — out of scope"), False)

    def test_empty_returns_none(self):
        self.assertIsNone(parse_scope_gate_response(""))
        self.assertIsNone(parse_scope_gate_response("   "))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_scope_gate_response("maybe"))

    def test_scope_gate_prompt_lists_abortion_and_broad_social_issues(self):
        from .scope_gate import _SCOPE_GATE_SYSTEM

        lowered = _SCOPE_GATE_SYSTEM.lower()
        self.assertIn("abortion", lowered)
        self.assertIn("prefer yes", lowered)
        self.assertIn("do not answer no just because a topic is sensitive", lowered)
        self.assertIn("can christians have abortions?", lowered)

    def test_always_in_scope_for_abortion_and_christians(self):
        self.assertTrue(always_in_scope_query("Can Christians have abortions?"))
        self.assertTrue(always_in_scope_query("What about abortion?"))
        self.assertTrue(always_in_scope_query("What is the meaning of life?"))
        self.assertTrue(always_in_scope_query("What is my purpose in life?"))
        self.assertTrue(always_in_scope_query("What topic did we start this chat with?"))
        self.assertTrue(always_in_scope_query("What Bible story did we start this chat with?"))
        self.assertTrue(always_in_scope_query("Hello how are you today?"))
        self.assertFalse(always_in_scope_query("Write a Python sort function"))
        self.assertFalse(always_in_scope_query("Who won the game last night?"))


class WebsiteCrawlHelperTests(unittest.TestCase):
    def test_excludes_cart_and_thank_you(self):
        self.assertTrue(path_is_excluded("https://thenordins.org/store/cart"))
        self.assertTrue(path_is_excluded("https://thenordins.org/booking-thank-you"))
        self.assertTrue(path_is_excluded("https://thenordins.org/signin"))
        self.assertFalse(path_is_excluded("https://thenordins.org/about"))

    def test_socials_not_allowed(self):
        self.assertTrue(host_allowed_for_page("https://mycthouston.org/visit"))
        self.assertFalse(host_allowed_for_page("https://www.facebook.com/TheNordins"))

    def test_content_type_classification(self):
        self.assertEqual(
            classify_content_type("https://thenordins.org/store-default/kings-and-priests"),
            "book_resource",
        )
        self.assertEqual(classify_content_type("https://mycthouston.org/visit"), "church_info")
        self.assertEqual(
            classify_content_type("https://thenordins.org/know-your-why-session-one"),
            "teaching_media",
        )

    def test_normalize_strips_www_and_trailing_slash(self):
        self.assertEqual(
            normalize_url("https://www.mycthouston.org/visit/"),
            "https://mycthouston.org/visit",
        )

    def test_html_to_markdown_keeps_service_times(self):
        html = (
            "<html><head><title>Visit Us</title></head><body><main>"
            "<h1>Visit Us</h1>"
            "<p>Services begin at 10am both in person and online.</p>"
            "<p>Youth Services every Wednesday at 7pm.</p>"
            "</main></body></html>"
        )
        title, content_type, markdown = html_to_markdown(
            html, "https://mycthouston.org/visit", "CT Houston"
        )
        self.assertEqual(title, "Visit Us")
        self.assertEqual(content_type, "church_info")
        self.assertIn("10am", markdown)
        self.assertIn("Source URL: https://mycthouston.org/visit", markdown)
        self.assertTrue(source_name_for_url("https://mycthouston.org/visit").startswith("web__"))


class DocumentCleanupTests(unittest.TestCase):
    def test_removes_page_chrome_boilerplate_and_fixes_hyphens(self):
        raw = (
            "Faith That Moves Mountains\n"
            "Pastor Don\n"
            "Page 1 of 3\n"
            "\x0c"
            "Faith That Moves Mountains\n"
            "All rights reserved.\n"
            "Copyright © 2020 Example Ministry.\n"
            "\n"
            "Today we look at faith that moves moun-\n"
            "tains for the glory of God.\n"
            "\n"
            "- 2 -\n"
            "\x0c"
            "Faith That Moves Mountains\n"
            "Downloaded from the church portal.\n"
            "www.example.org\n"
            "\n"
            "Believe God for the breakthrough.\n"
            "Page 3 of 3\n"
        )
        result = clean_extracted_document(raw, title="Faith That Moves Mountains")
        text = result.text
        self.assertIn("faith that moves mountains", text.lower())
        self.assertIn("Believe God for the breakthrough.", text)
        self.assertNotIn("All rights reserved", text)
        self.assertNotIn("Copyright ©", text)
        self.assertNotIn("Downloaded from", text)
        self.assertNotIn("Page 1 of 3", text)
        self.assertNotIn("moun-\ntains", text)
        self.assertIn("mountains", text.lower())
        self.assertGreater(result.stats.boilerplate_removed, 0)
        self.assertGreaterEqual(result.stats.hyphen_fixes, 1)

    def test_preserves_mid_document_content_and_structure(self):
        raw = (
            "Introduction\n\n"
            "Jesus taught his disciples about prayer.\n\n"
            "Point One\n\n"
            "Ask in faith without doubting.\n"
        )
        result = clean_extracted_document(raw)
        self.assertIn("Jesus taught his disciples about prayer.", result.text)
        self.assertIn("Ask in faith without doubting.", result.text)

    def test_markdown_cleanup_keeps_headings(self):
        raw = (
            "# Visit Us\n\n"
            "- Source URL: https://example.org/visit\n\n"
            "Services begin at 10am.\n\n"
            "Page 2\n\n"
            "All rights reserved.\n\n"
            "## Youth\n\n"
            "Wednesday at 7pm.\n"
        )
        result = clean_markdown_document(raw)
        self.assertIn("# Visit Us", result.text)
        self.assertIn("## Youth", result.text)
        self.assertIn("Services begin at 10am.", result.text)
        self.assertNotIn("All rights reserved", result.text)

    def test_format_cleanup_log_includes_counts(self):
        result = clean_extracted_document("Hello world.\n\nAll rights reserved.\n")
        log = format_cleanup_log(result.stats, source_label="demo.pdf")
        self.assertIn("Cleanup (demo.pdf):", log)
        self.assertIn("boilerplate=", log)


class PersistDbTests(unittest.TestCase):
    def test_dump_path_uses_env_override(self):
        import os
        from pathlib import Path

        from .persist_db import dump_path

        previous = os.environ.get("PERSIST_PG_DUMP")
        os.environ["PERSIST_PG_DUMP"] = "/tmp/custom_ai_db.dump"
        try:
            self.assertEqual(dump_path(), Path("/tmp/custom_ai_db.dump"))
        finally:
            if previous is None:
                os.environ.pop("PERSIST_PG_DUMP", None)
            else:
                os.environ["PERSIST_PG_DUMP"] = previous

    def test_dump_skips_invalid_database_name(self):
        import os

        from .persist_db import dump_persistent_postgres

        previous = os.environ.get("POSTGRES_DB")
        os.environ["POSTGRES_DB"] = "ai_db; drop table"
        try:
            self.assertFalse(dump_persistent_postgres())
        finally:
            if previous is None:
                os.environ.pop("POSTGRES_DB", None)
            else:
                os.environ["POSTGRES_DB"] = previous

    def test_dump_skips_when_django_uses_sqlite(self):
        from django.conf import settings

        from .persist_db import dump_persistent_postgres

        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" not in engine:
            self.skipTest("this guard is for SQLite test runs")
        self.assertFalse(dump_persistent_postgres())


class DocxToPdfTests(unittest.TestCase):
    def test_fallback_writes_pdf_when_soffice_missing(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from docx import Document

        from .docx_to_pdf import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notes.docx"
            dest = Path(tmp) / "notes.pdf"
            doc = Document()
            doc.add_paragraph("The Lord is my shepherd.")
            doc.save(src)
            previous = os.environ.get("SOFFICE_PATH")
            os.environ["SOFFICE_PATH"] = "soffice-not-installed"
            try:
                with patch("core.docx_to_pdf.shutil.which", return_value=None):
                    method = convert_docx_to_pdf(src, dest)
            finally:
                if previous is None:
                    os.environ.pop("SOFFICE_PATH", None)
                else:
                    os.environ["SOFFICE_PATH"] = previous
            self.assertEqual(method, "fpdf")
            self.assertTrue(dest.is_file())
            self.assertGreater(dest.stat().st_size, 100)
            self.assertIn(b"%PDF", dest.read_bytes()[:8])


class StoragePathTests(unittest.TestCase):
    def test_ingestion_dir_uses_env_override(self):
        import os
        import tempfile
        from pathlib import Path

        from .storage_paths import admin_ingestion_dir, admin_video_ingestion_dir

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("INGESTION_UPLOAD_DIR")
            previous_video = os.environ.get("VIDEO_INGESTION_UPLOAD_DIR")
            os.environ["INGESTION_UPLOAD_DIR"] = tmp
            video_tmp = str(Path(tmp) / "videos")
            os.environ["VIDEO_INGESTION_UPLOAD_DIR"] = video_tmp
            try:
                path = admin_ingestion_dir()
                self.assertEqual(path, Path(tmp).resolve())
                self.assertTrue(path.is_dir())
                video_path = admin_video_ingestion_dir()
                self.assertEqual(video_path, Path(video_tmp).resolve())
                self.assertTrue(video_path.is_dir())
            finally:
                if previous is None:
                    os.environ.pop("INGESTION_UPLOAD_DIR", None)
                else:
                    os.environ["INGESTION_UPLOAD_DIR"] = previous
                if previous_video is None:
                    os.environ.pop("VIDEO_INGESTION_UPLOAD_DIR", None)
                else:
                    os.environ["VIDEO_INGESTION_UPLOAD_DIR"] = previous_video


if __name__ == "__main__":
    unittest.main()
