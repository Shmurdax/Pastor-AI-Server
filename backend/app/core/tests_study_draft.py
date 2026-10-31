import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from api.models import Profile
from core.basic_chat import (
    build_draft_plan,
    draft_writer_messages,
    resolve_chat_route,
    retrieve_draft_passages,
)
from core.models import ChatMessage
from core.study_draft import (
    CLASSIFIER_SYSTEM,
    PIPELINE_CHAT,
    PIPELINE_DRAFT,
    decision_from_classifier,
    draft_system_prompt,
    missing_scripture_refs,
    parse_plan_text,
    render_plan,
    rule_route,
)

User = get_user_model()

LABELED = (
    "An in-depth study on living water\n"
    "Subtitle: Thirst and the gift of God\n"
    "Primary Biblical Texts: John 4:14 and John 7:37-39\n"
    "Supporting Biblical Texts: Isaiah 55:1"
)

RULE_CASES = [
    ("What is the Trinity?", PIPELINE_CHAT),
    ("Explain the Trinity from the notes.", PIPELINE_CHAT),
    ("Explain the Godhead from the sermon notes.", PIPELINE_CHAT),
    ("How does faith work?", PIPELINE_CHAT),
    ("Tell me about love", PIPELINE_CHAT),
    ("Do the sermons talk about the Trinity?", PIPELINE_CHAT),
    ("What does Pastor Don teach about repentance?", PIPELINE_CHAT),
    ("What do the notes say about water baptism?", PIPELINE_CHAT),
    ("Help me understand the Holy Spirit", PIPELINE_CHAT),
    ("Is baptism in the sermons?", PIPELINE_CHAT),
    ("Write an in-depth Bible study on repentance", PIPELINE_DRAFT),
    ("Please draft sermon notes for Sunday on baptism", PIPELINE_DRAFT),
    ("Prepare a 3-point sermon on faith", PIPELINE_DRAFT),
    ("I need notes for Sunday on the Holy Spirit", PIPELINE_DRAFT),
    ("Make me a lesson on James 2", PIPELINE_DRAFT),
    ("Create teaching notes about forgiveness", PIPELINE_DRAFT),
    ("Give me a 3 point sermon on faith", PIPELINE_DRAFT),
    ("Prep Sunday's message on baptism", PIPELINE_DRAFT),
    ("Help me prep Wednesday's message on baptism", PIPELINE_DRAFT),
    (LABELED, PIPELINE_DRAFT),
    ("make a presentation about love", None),
    ("Can you put together a lesson on James 2?", None),
    ("I need something I can stand up and teach Wednesday on forgiveness", None),
    ("talk about grace for a minute", None),
    ("What is a Bible study?", None),
]


def _hit(title, text, score=0.5):
    return SimpleNamespace(score=score, payload={"title": title, "text": text})


class StudyDraftRuleTests(SimpleTestCase):
    def test_rule_balance_on_creative_prompts(self):
        for query, expected in RULE_CASES:
            route = rule_route(query)
            if expected is None:
                self.assertIsNone(route, msg=query)
            else:
                self.assertIsNotNone(route, msg=query)
                self.assertEqual(route.pipeline, expected, msg=query)
                self.assertEqual(route.source, "rules", msg=query)

    def test_labeled_request_keeps_scripture_sections(self):
        route = rule_route(LABELED)
        self.assertEqual(route.subtitle, "Thirst and the gift of God")
        self.assertEqual(route.primary_texts, ("John 4:14", "John 7:37-39"))
        self.assertEqual(route.supporting_texts, ("Isaiah 55:1",))
        self.assertIn("living water", route.topic.lower())

    def test_classifier_prompt_keeps_vague_presentations_on_chat(self):
        self.assertIn("make a presentation about love", CLASSIFIER_SYSTEM)
        self.assertIn("pastoral_chat with confidence below 0.6", CLASSIFIER_SYSTEM)
        self.assertIn("put together a lesson on James 2", CLASSIFIER_SYSTEM)

    def test_low_confidence_draft_stays_on_chat(self):
        raw = json.dumps(
            {
                "pipeline": "study_sermon_draft",
                "confidence": 0.42,
                "format": "lesson",
                "topic": "love",
                "reason": "vague presentation",
            }
        )
        route = decision_from_classifier("make a presentation about love", raw, min_confidence=0.75)
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "classifier")
        self.assertAlmostEqual(route.confidence, 0.42)

    def test_confident_creative_draft_is_accepted(self):
        raw = json.dumps(
            {
                "pipeline": "study_sermon_draft",
                "confidence": 0.91,
                "format": "lesson",
                "topic": "James 2",
                "primary_texts": ["James 2:14-26"],
                "reason": "asked for a lesson",
            }
        )
        route = decision_from_classifier(
            "Can you put together a lesson on James 2?",
            raw,
            min_confidence=0.75,
        )
        self.assertTrue(route.is_draft)
        self.assertEqual(route.format, "lesson")
        self.assertEqual(route.primary_texts, ("James 2:14-26",))

    def test_classifier_json_can_be_fenced(self):
        raw = '```json\n{"pipeline":"pastoral_chat","confidence":0.2,"reason":"question"}\n```'
        route = decision_from_classifier("talk about grace for a minute", raw)
        self.assertEqual(route.pipeline, PIPELINE_CHAT)

    def test_broken_classifier_json_stays_on_chat(self):
        route = decision_from_classifier("talk about grace", "not json")
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "classifier_failed")

    def test_obvious_question_does_not_call_the_classifier(self):
        with patch("core.basic_chat.complete_llm_text", side_effect=AssertionError("classifier")):
            route = resolve_chat_route("What is faith?")
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "rules")

    def test_unsure_prompt_uses_the_classifier(self):
        payload = json.dumps(
            {
                "pipeline": "pastoral_chat",
                "confidence": 0.33,
                "reason": "no teaching document",
            }
        )
        with patch("core.basic_chat.complete_llm_text", return_value=payload) as complete, patch(
            "core.basic_chat.warm_llm", return_value=True
        ):
            route = resolve_chat_route("make a presentation about love")
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "classifier")
        self.assertIn("presentation about love", CLASSIFIER_SYSTEM)
        self.assertEqual(complete.call_args.args[0][1]["content"], "make a presentation about love")

    def test_classifier_failure_stays_on_chat(self):
        with patch(
            "core.basic_chat.complete_llm_text", side_effect=RuntimeError("timeout")
        ), patch("core.basic_chat.warm_llm", return_value=True):
            route = resolve_chat_route("make a presentation about love")
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "classifier_failed")

    def test_draft_pipeline_can_be_turned_off(self):
        with patch.dict(os.environ, {"CHAT_DRAFT": "0"}):
            route = resolve_chat_route("Write a Bible study on repentance")
        self.assertEqual(route.pipeline, PIPELINE_CHAT)
        self.assertEqual(route.source, "disabled")


class StudyDraftGenerationTests(SimpleTestCase):
    def test_missing_scripture_detects_chapter_mentions(self):
        self.assertEqual(
            missing_scripture_refs("See John 4 later.", ("John 4:14", "Isaiah 55:1")),
            ["Isaiah 55:1"],
        )
        self.assertEqual(
            missing_scripture_refs("John 14:16 is the promise.", ("John 1:1",)),
            ["John 1:1"],
        )
        self.assertEqual(missing_scripture_refs("Read John 14:16.", ("John 14:16",)), [])

    def test_plan_render_and_writer_prompt(self):
        plan = parse_plan_text(
            '{"big_idea":"Living water","points":[{"heading":"Ask"}],"gaps":["Isaiah 55:1"]}'
        )
        rendered = render_plan(plan)
        self.assertIn("Living water", rendered)
        self.assertIn("1. Ask", rendered)
        self.assertIn("Isaiah 55:1", rendered)
        route = rule_route(LABELED)
        messages = draft_writer_messages(
            LABELED,
            route,
            [{"title": "Woman at the Well", "text": "Jesus offers living water."}],
            plan,
        )
        system = messages[0]["content"]
        user = messages[1]["content"]
        self.assertIn("Title:", system)
        self.assertIn("Gaps:", system)
        self.assertNotIn("2–4 short paragraphs", system)
        self.assertIn("Thirst and the gift of God", user)
        self.assertIn("John 4:14", user)
        self.assertIn("Woman at the Well", user)
        self.assertIn("Living water", user)
        self.assertIn("Bible study notes", draft_system_prompt(route))

    def test_sermon_format_names_sermon_notes(self):
        route = rule_route("Draft sermon notes for Sunday on baptism")
        self.assertEqual(route.format, "sermon")
        self.assertIn("sermon notes", draft_system_prompt(route))

    def test_draft_retrieval_searches_hyde_topic_and_scripture(self):
        calls = []

        class Embeddings:
            def embed_query(self, text):
                calls.append(text)
                return [len(calls)]

        def search(client, collection, vector, top_k):
            title = f"Hit {vector[0]}"
            return [_hit(title, f"body {vector[0]} about repentance and Romans")]

        route = rule_route("Write a Bible study on repentance\nPrimary Biblical Texts: Romans 6:23")
        with patch.dict(os.environ, {"CHAT_HYDE": "1"}), patch(
            "qdrant_client.QdrantClient", return_value=object()
        ), patch(
            "core.embeddings_utils.get_embeddings", return_value=Embeddings()
        ), patch("core.basic_chat._search_qdrant", side_effect=search), patch(
            "core.basic_chat.generate_draft_hyde_with_retry",
            return_value=("Repentance turns the heart back to God.", "ok"),
        ):
            result = retrieve_draft_passages(
                "Write a Bible study on repentance\nPrimary Biblical Texts: Romans 6:23",
                route,
                include_debug=True,
            )

        self.assertEqual(result["searches"], ["query", "hyde", "topic", "scripture"])
        self.assertIn("Romans 6:23", calls[-1])
        self.assertEqual(calls[1], "Repentance turns the heart back to God.")
        self.assertGreaterEqual(len(result["passages"]), 1)
        self.assertNotIn("UNIQUE", result["hyde_text"])

    def test_plan_failure_returns_an_empty_plan(self):
        route = rule_route("Write a Bible study on repentance")
        with patch("core.basic_chat.complete_llm_text", side_effect=RuntimeError("down")):
            plan = build_draft_plan("Write a Bible study on repentance", route, [])
        self.assertEqual(plan, {})


class StudyDraftAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="draft@example.com",
            email="draft@example.com",
            password="pass12345",
        )
        profile = self.user.profile
        profile.subscription_status = Profile.SubscriptionStatus.ACTIVE
        profile.email_verified = True
        profile.save(update_fields=["subscription_status", "email_verified"])
        Token.objects.create(user=self.user)
        token = Token.objects.get(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_draft_request_streams_notes_without_the_chat_retriever(self):
        passages = [{"title": "It Is Time for the Cross", "text": "Repentance turns the heart."}]

        def fake_stream(messages, *, max_tokens):
            self.assertGreater(max_tokens, 800)
            blob = messages[0]["content"] + messages[1]["content"]
            self.assertIn("Title:", blob)
            self.assertIn("Repentance turns the heart.", blob)
            yield "Title: Repentance\n\nBig idea: Turn back to God."

        with patch(
            "core.basic_chat_views.retrieve_draft_passages", return_value=passages
        ) as draft_retrieve, patch(
            "core.basic_chat_views.retrieve_passages",
            side_effect=AssertionError("chat retrieval"),
        ), patch(
            "core.basic_chat_views.build_draft_plan",
            return_value={"big_idea": "Turn back", "points": [{"heading": "Turn"}]},
        ), patch(
            "core.basic_chat_views.stream_message_tokens", side_effect=fake_stream
        ), patch(
            "core.basic_chat_views.stream_llm_tokens",
            side_effect=AssertionError("chat stream"),
        ):
            res = self.client.post(
                "/api/chat/",
                {
                    "query": "Write a Bible study on repentance",
                    "session_id": "draft-sse",
                    "stream": True,
                },
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
            body = b"".join(res.streaming_content).decode()

        self.assertEqual(res.status_code, 200)
        draft_retrieve.assert_called_once()
        self.assertLess(body.find('"phase": "planning"'), body.find('"type": "delta"'))
        self.assertIn("Title: Repentance", body)
        self.assertIn('"pipeline": "study_sermon_draft"', body)
        saved = ChatMessage.objects.get(session_id="draft-sse")
        self.assertIn("Turn back to God", saved.ai_response)

    def test_missing_requested_text_appends_a_gap_note(self):
        passages = [{"title": "Faith Lift", "text": "Faith trusts God."}]

        def fake_stream(messages, *, max_tokens):
            if max_tokens == 240:
                yield "Gaps: James 2:14-26 was not in the sermon excerpts."
                return
            yield "Title: Faith\n\nBig idea: Trust God."

        with patch(
            "core.basic_chat_views.retrieve_draft_passages", return_value=passages
        ), patch(
            "core.basic_chat_views.build_draft_plan", return_value={}
        ), patch(
            "core.basic_chat_views.stream_message_tokens", side_effect=fake_stream
        ):
            res = self.client.post(
                "/api/chat/",
                {
                    "query": "Write a Bible study on faith\nPrimary Biblical Texts: James 2:14-26",
                    "session_id": "draft-gap",
                },
                format="json",
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["pipeline"], PIPELINE_DRAFT)
        self.assertIn("Gaps: James 2:14-26", res.data["answer"])
        self.assertIn("Title: Faith", res.data["answer"])
