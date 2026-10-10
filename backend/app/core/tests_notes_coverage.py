import unittest
from types import SimpleNamespace

from core.notes_coverage import (
    COVERAGE_FULL,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    coverage_subject_tokens,
    focus_retrieved_notes,
    choose_sermon_by_rerank,
    query_changes_locked_sermon,
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

    def test_followup_stays_unless_the_new_subject_is_absent(self):
        sermon = (
            "The older brother stayed outside. The father ran to the younger son. "
            "A husband who will not love his wife sins against the marriage covenant."
        )
        self.assertFalse(
            query_changes_locked_sermon(
                "What about the older brother?",
                "Explain the parable of the prodigal son from the sermon notes.",
                sermon,
            )
        )
        self.assertFalse(
            query_changes_locked_sermon(
                "What should a husband practice this week?",
                "Create sermon notes on marriage as a covenant.",
                sermon,
            )
        )
        self.assertTrue(
            query_changes_locked_sermon(
                "Now tell me what Pastor Don teaches about Pentecost.",
                "Create sermon notes on marriage as a covenant.",
                sermon,
            )
        )
        self.assertFalse(
            query_changes_locked_sermon(
                "Say more about that.",
                "Explain the parable of the prodigal son from the sermon notes.",
                sermon,
            )
        )

    def test_rerank_score_picks_the_sermon_that_teaches_the_question(self):
        aside = _doc(
            "Jonah ran once. We must wait on God in the wilderness. "
            "Wait on God through the trial. Wait on God again.",
            source="wait.pdf",
        )
        aside.metadata["rerank_score"] = 0.42
        teaching = _doc(
            "Jonah ran from the Lord and the storm found him. "
            "The sermon teaches that running from God does not end the assignment.",
            source="jonah.pdf",
        )
        teaching.metadata["rerank_score"] = 0.86
        weak = _doc(
            "The council discussed many customs in the city.",
            source="customs.pdf",
        )
        weak.metadata["rerank_score"] = 0.18
        chosen, coverage, score = choose_sermon_by_rerank(
            [(aside, 0.42), (teaching, 0.86), (weak, 0.18)],
            min_score=0.5,
        )
        self.assertEqual(coverage, "full")
        self.assertEqual(chosen, [teaching])
        self.assertAlmostEqual(score, 0.86)
        refused, refused_coverage, refused_score = choose_sermon_by_rerank(
            [(weak, 0.18)],
            min_score=0.5,
        )
        self.assertEqual(refused, [])
        self.assertEqual(refused_coverage, "none")
        self.assertAlmostEqual(refused_score, 0.18)

    def test_incidental_word_does_not_count_as_covering_the_question(self):
        from core.notes_coverage import sermon_mentions_question

        hope = _doc(
            "Hope in God and wait expectantly for Him, for I shall yet praise Him.",
            source="It Is Time for Hope",
        )
        self.assertTrue(
            sermon_mentions_question(
                "Create sermon notes on hope for someone who is sick or grieving.",
                [hope],
            )
        )
        selling = _doc(
            "Everywhere you turn you see a new best-selling book about leadership.",
            source="Nextsteps 101",
        )
        self.assertFalse(
            sermon_mentions_question(
                "What did Pastor Don teach about the Council of Trent and selling indulgences in 1545?",
                [selling],
            )
        )

    def test_body_morphology_covers_question_without_title_match(self):
        from core.notes_coverage import sermon_mentions_question

        # Notes use a stem variant; PDF title does not mirror the question.
        repent = _doc(
            "The Lord calls every believer to repent of sin and walk in a new direction.",
            source="Turning Toward God.pdf",
        )
        self.assertTrue(
            sermon_mentions_question(
                "How should we practice repentance in daily life?",
                [repent],
            )
        )
        restore = _doc(
            "Grace restores the broken relationship when people forgive one another freely.",
            source="Relationships In Christ.pdf",
        )
        self.assertTrue(
            sermon_mentions_question(
                "What does the teaching say about forgiveness between people?",
                [restore],
            )
        )
        marriage = _doc(
            "A husband must love and lead with patience inside the marriage covenant.",
            source="Home And Family.pdf",
        )
        self.assertTrue(
            sermon_mentions_question(
                "How should a husband and wife walk together in faith?",
                [marriage],
            )
        )

    def test_title_alone_does_not_count_as_covering_the_question(self):
        from core.notes_coverage import sermon_mentions_question

        titled = _doc(
            "The congregation gathered for announcements and a potluck lunch.",
            source="Forgiveness And Mercy.pdf",
        )
        self.assertFalse(
            sermon_mentions_question(
                "What did the notes teach about forgiveness and mercy?",
                [titled],
            )
        )

    def test_aggregate_rerank_beats_one_hot_aside_chunk(self):
        aside_a = _doc(
            "Someone once sat in a chair and talked about trust for a moment.",
            source="aside.pdf",
        )
        aside_a.metadata["rerank_score"] = 0.91
        aside_b = _doc(
            "The weather was mild that afternoon in the courtyard.",
            source="aside.pdf",
        )
        aside_b.metadata["rerank_score"] = 0.21
        teach_a = _doc(
            "Leaders go the extra distance and serve beyond what is required.",
            source="leadership.pdf",
        )
        teach_a.metadata["rerank_score"] = 0.72
        teach_b = _doc(
            "True leadership carries the load farther than duty demands.",
            source="leadership.pdf",
        )
        teach_b.metadata["rerank_score"] = 0.70
        teach_c = _doc(
            "The call is to keep walking with people past the easy stopping place.",
            source="leadership.pdf",
        )
        teach_c.metadata["rerank_score"] = 0.68
        chosen, coverage, score = choose_sermon_by_rerank(
            [
                (aside_a, 0.91),
                (aside_b, 0.21),
                (teach_a, 0.72),
                (teach_b, 0.70),
                (teach_c, 0.68),
            ],
            min_score=0.5,
        )
        self.assertEqual(coverage, "full")
        self.assertTrue(all(doc.metadata["source"] == "leadership.pdf" for doc in chosen))
        self.assertAlmostEqual(score, 0.72)

    def test_short_topical_sermon_not_beaten_by_long_flat_sum(self):
        from core.notes_coverage import _group_rerank_aggregate

        short = [
            (0.78, _doc("Hope in God when the heart is cast down.", source="hope.pdf")),
        ]
        long_flat = [
            (0.51, _doc("Anoint the sick and pray together.", source="altar.pdf")),
            (0.50, _doc("Confess faults one to another.", source="altar.pdf")),
            (0.50, _doc("The elders gather around the sufferer.", source="altar.pdf")),
        ]
        self.assertGreater(
            _group_rerank_aggregate(short),
            _group_rerank_aggregate(long_flat),
        )

    def test_topk_keeps_secondary_sermon_with_weights(self):
        primary_a = _doc(
            "Hope in God and wait expectantly when the soul is cast down.",
            source="hope.pdf",
        )
        primary_a.metadata["rerank_score"] = 0.82
        secondary_a = _doc(
            "Prisoners of hope hold onto the promise while they wait for joy.",
            source="prisoners.pdf",
        )
        secondary_a.metadata["rerank_score"] = 0.74
        noise = _doc(
            "The courtyard schedule listed choir practice and potluck times.",
            source="noise.pdf",
        )
        noise.metadata["rerank_score"] = 0.20
        chosen, coverage, score = choose_sermon_by_rerank(
            [
                (primary_a, 0.82),
                (secondary_a, 0.74),
                (noise, 0.20),
            ],
            min_score=0.5,
            max_files=3,
            query="What hope do the notes give someone who is cast down?",
        )
        self.assertEqual(coverage, "full")
        self.assertAlmostEqual(score, 0.82)
        sources = {doc.metadata["source"] for doc in chosen}
        self.assertIn("hope.pdf", sources)
        self.assertIn("prisoners.pdf", sources)
        self.assertNotIn("noise.pdf", sources)
        weights = {doc.metadata["source"]: doc.metadata.get("sermon_weight") for doc in chosen}
        self.assertEqual(weights["hope.pdf"], 1.0)
        self.assertEqual(weights["prisoners.pdf"], 0.55)
        self.assertTrue(
            [doc.metadata["source"] for doc in chosen].index("hope.pdf")
            < [doc.metadata["source"] for doc in chosen].index("prisoners.pdf")
        )

    def test_diversify_hits_keeps_multiple_sources(self):
        from core.notes_coverage import diversify_hits_by_source

        hits = []
        for index in range(12):
            hits.append(
                (
                    _doc(f"Long transcript window {index} about many things.", source="long.pdf"),
                    0.9 - index * 0.01,
                )
            )
        hits.append(
            (
                _doc("Short topical passage about the traveler left half dead.", source="short.pdf"),
                0.55,
            )
        )
        kept = diversify_hits_by_source(hits, max_per_source=3, limit=10)
        sources = {doc.metadata["source"] for doc, _score in kept}
        self.assertIn("short.pdf", sources)
        self.assertLessEqual(
            sum(1 for doc, _score in kept if doc.metadata["source"] == "long.pdf"),
            3,
        )

    def test_topic_ordinals_survive_non_outline_queries(self):
        from core.teaching_claims import distinctive_query_tokens, query_topic_tokens

        tokens = distinctive_query_tokens(
            query_topic_tokens("What does second mile leadership look like for servants?")
        )
        self.assertIn("second", tokens)
        self.assertIn("mile", tokens)
        self.assertIn("leadership", tokens)
