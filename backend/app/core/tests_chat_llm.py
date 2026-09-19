import unittest
from unittest.mock import MagicMock, patch

from core.chat_llm import (
    CHAT_FREQUENCY_PENALTY,
    CHAT_PRESENCE_PENALTY,
    CHAT_TEMPERATURE,
    CHAT_TOP_P,
    CHAT_VLLM_EXTRA_BODY,
    EMPTY_REFERENCE_NOTES,
    estimate_chat_tokens,
    fit_chat_budget,
    get_chat_llm,
    normalize_vllm_base_url,
    resolve_vllm_api_key,
    resolve_vllm_model,
    resolve_vllm_url,
    select_pinned_history_rows,
    vllm_is_remote,
    vllm_url_is_local,
)


class VllmUrlResolutionTests(unittest.TestCase):
    def test_local_defaults_and_hosts(self):
        self.assertEqual(resolve_vllm_url({}), "http://vllm:8000/v1")
        self.assertTrue(vllm_url_is_local("http://127.0.0.1:8010/v1"))
        self.assertTrue(vllm_url_is_local("http://vllm:8000/v1"))
        self.assertFalse(vllm_url_is_local("https://api.runpod.ai/v2/abc/openai/v1"))

    def test_endpoint_id_builds_openai_url(self):
        env = {"RUNPOD_VLLM_ENDPOINT_ID": "abc123", "VLLM_URL": "http://127.0.0.1:8010/v1"}
        self.assertEqual(
            resolve_vllm_url(env),
            "https://api.runpod.ai/v2/abc123/openai/v1",
        )
        self.assertTrue(vllm_is_remote(env))

    def test_normalizes_bare_runpod_endpoint_url(self):
        self.assertEqual(
            normalize_vllm_base_url("https://api.runpod.ai/v2/xyz789/"),
            "https://api.runpod.ai/v2/xyz789/openai/v1",
        )
        self.assertEqual(
            resolve_vllm_url({"VLLM_URL": "https://api.runpod.ai/v2/xyz789"}),
            "https://api.runpod.ai/v2/xyz789/openai/v1",
        )

    def test_mode_flags_force_remote(self):
        self.assertTrue(vllm_is_remote({"VLLM_MODE": "serverless", "VLLM_URL": "http://127.0.0.1:8010/v1"}))
        self.assertTrue(vllm_is_remote({"CPU_ONLY": "1", "VLLM_URL": "http://127.0.0.1:8010/v1"}))
        self.assertFalse(vllm_is_remote({"VLLM_URL": "http://127.0.0.1:8010/v1"}))

    def test_api_key_prefers_vllm_then_runpod(self):
        self.assertEqual(resolve_vllm_api_key({}), "not-needed")
        self.assertEqual(resolve_vllm_api_key({"RUNPOD_API_KEY": "rp_live"}), "rp_live")
        self.assertEqual(
            resolve_vllm_api_key({"VLLM_API_KEY": "direct", "RUNPOD_API_KEY": "rp_live"}),
            "direct",
        )
        self.assertEqual(resolve_vllm_api_key({"RUNPOD_API_KEY": "paste_here"}), "not-needed")
        self.assertEqual(
            resolve_vllm_api_key({
                "VLLM_MODE": "serverless",
                "RUNPOD_VLLM_ENDPOINT_ID": "ep1",
            }),
            "",
        )
        self.assertEqual(
            resolve_vllm_api_key({
                "VLLM_API_KEY": "not-needed",
                "RUNPOD_API_KEY": "rp_live",
                "VLLM_MODE": "serverless",
            }),
            "rp_live",
        )

    def test_model_name(self):
        self.assertEqual(resolve_vllm_model({}), "christianai")
        self.assertEqual(resolve_vllm_model({"VLLM_MODEL": "christianai"}), "christianai")

    def test_context_window_caps_to_vllm_max_model_len(self):
        from core.chat_llm import resolve_chat_context_window

        self.assertEqual(resolve_chat_context_window({}), 32768)
        self.assertEqual(resolve_chat_context_window({"CHAT_CONTEXT_WINDOW": "8192"}), 8192)
        self.assertEqual(
            resolve_chat_context_window({
                "CHAT_CONTEXT_WINDOW": "32768",
                "VLLM_MAX_MODEL_LEN": "4096",
            }),
            4096,
        )
        self.assertEqual(
            resolve_chat_context_window({
                "CHAT_CONTEXT_WINDOW": "32768",
                "VLLM_MAX_MODEL_LEN": "32768",
            }),
            32768,
        )

    def test_fit_chat_budget_stays_inside_4096_with_huge_prompt(self):
        env = {"CHAT_CONTEXT_WINDOW": "8192", "VLLM_MAX_MODEL_LEN": "4096"}
        system = (
            "<priority>" + ("pastoral teaching " * 400) + "</priority>\n"
            "REFERENCE NOTES:\n" + ("sermon chunk " * 800)
        )
        history = [
            type("Msg", (), {"content": "previous question about faith"})(),
            type("Msg", (), {"content": "a long previous pastoral answer " * 40})(),
        ]
        fitted, hist, completion, used = fit_chat_budget(
            system,
            history,
            "What is the meaning of life?",
            2400,
            env=env,
        )
        self.assertLessEqual(used + completion + 96, 4096)
        self.assertGreaterEqual(completion, 128)
        self.assertLessEqual(estimate_chat_tokens(fitted), 4096)
        self.assertNotIn("No relevant sermon notes found.", fitted)
        self.assertIn("sermon chunk", fitted)

    def test_fit_chat_budget_keeps_real_notes_on_4096_window(self):
        from core.chat_system_prompt import build_chat_system_prompt

        notes_body = (
            "Pastor Don Nordin teaches, \"The main purpose of the church is to make disciples "
            "and to preach the gospel of Jesus Christ to the nations.\" "
            "Susan Nordin says, \"We gather to worship and then go into the world.\"\n"
        ) * 50
        system = (
            build_chat_system_prompt(biblical_names=["Philemon"])
            + "\nREFERENCE NOTES:\n"
            + notes_body
        )
        env = {"CHAT_CONTEXT_WINDOW": "4096", "VLLM_MAX_MODEL_LEN": "4096"}
        fitted, _hist, completion, used = fit_chat_budget(
            system,
            [],
            "According to Pastor Don's sermons, what is the main purpose of the church?",
            2400,
            env=env,
        )
        notes = fitted.split("REFERENCE NOTES:\n", 1)[1]
        self.assertNotEqual(notes.strip(), "No relevant sermon notes found.")
        self.assertIn("The main purpose of the church", notes)
        self.assertIn("Pastor Don Nordin", notes)
        self.assertLessEqual(used + completion + 96, 4096)
        self.assertGreaterEqual(completion, 128)
        self.assertIn("REFERENCE NOTES:", fitted)

    def test_fit_chat_budget_keeps_five_to_ten_turns_on_32k_window(self):
        env = {"CHAT_CONTEXT_WINDOW": "32768", "VLLM_MAX_MODEL_LEN": "32768"}
        system = (
            "<priority>pastoral teaching</priority>\n"
            "REFERENCE NOTES:\n" + ("sermon chunk " * 80)
        )
        history = []
        for i in range(10):
            history.append(type("Msg", (), {"content": f"user question {i} about faith and purpose"})())
            history.append(type("Msg", (), {"content": ("pastoral answer with heading and bullets " * 40)})())
        fitted, hist, completion, used = fit_chat_budget(
            system,
            history,
            "What did we just discuss about faith?",
            1024,
            env=env,
        )
        self.assertGreaterEqual(len(hist), 10)
        self.assertIn("user question 5", "\n".join(m.content for m in hist))
        self.assertLessEqual(used + completion + 96, 32768)
        self.assertLessEqual(completion, 1024)
        self.assertGreaterEqual(completion, 128)
        self.assertIn("sermon chunk", fitted)

    def test_fit_chat_budget_pins_opening_exchange_on_tight_window(self):
        env = {"CHAT_CONTEXT_WINDOW": "4096", "VLLM_MAX_MODEL_LEN": "4096"}
        system = "REFERENCE NOTES:\n" + ("sermon chunk " * 400)
        history = [
            type(
                "Msg",
                (),
                {
                    "content": "How should a believer walk in humility like Jesus washing the disciples feet?"
                },
            )(),
            type("Msg", (), {"content": ("humility teaching about serving others " * 50)})(),
        ]
        for i in range(12):
            history.append(
                type("Msg", (), {"content": f"follow up {i} about serving and pride in leadership"})()
            )
            history.append(
                type("Msg", (), {"content": ("later pastoral answer with headings and quotes " * 50)})()
            )
        _fitted, hist, completion, used = fit_chat_budget(
            system,
            history,
            "What topic did we start this chat with?",
            1024,
            env=env,
        )
        blob = "\n".join(m.content for m in hist)
        self.assertIn("washing the disciples feet", blob)
        self.assertLessEqual(used + completion + 96, 4096)

    def test_select_pinned_history_keeps_opening_and_newest(self):
        from datetime import datetime, timedelta

        start = datetime(2026, 1, 1)
        rows = []
        for index in range(12):
            rows.append(
                type(
                    "Row",
                    (),
                    {
                        "id": index + 1,
                        "timestamp": start + timedelta(minutes=index),
                        "user_query": f"turn {index} query about the opening story",
                        "ai_response": f"turn {index} answer " + ("pastoral teaching " * 60),
                    },
                )()
            )
        window = list(reversed(rows))[:10]
        selected = select_pinned_history_rows(
            window,
            first_row=rows[0],
            max_turns=10,
            max_chars=5000,
        )
        queries = [row.user_query for row in selected]
        self.assertTrue(queries[0].startswith("turn 0 query"))
        self.assertTrue(any(query.startswith("turn 11 query") for query in queries))
        self.assertFalse(any(query.startswith("turn 1 query") for query in queries))
        self.assertLessEqual(len(selected), 10)
        used = sum(len(f"{row.user_query} {row.ai_response}") for row in selected)
        self.assertLessEqual(used, 5000 + len(f"{rows[0].user_query} {rows[0].ai_response}"))
        self.assertEqual(len({row.id for row in selected}), len(selected))

    def test_chat_view_uses_get_chat_llm_not_placeholder_key(self):
        from pathlib import Path

        source = Path(__file__).with_name("views.py").read_text(encoding="utf-8")
        self.assertIn("from .chat_llm import", source)
        self.assertIn("get_chat_llm", source)
        self.assertIn("fit_chat_budget", source)
        self.assertIn("EMPTY_REFERENCE_NOTES", source)
        self.assertNotIn("{{V1}}", EMPTY_REFERENCE_NOTES)
        self.assertIn("NOTES_MARKER", source)
        self.assertIn("MAX_HISTORY_TURNS", source)
        self.assertIn("first_row", source)
        self.assertIn("CHAT_MAX_HISTORY_TURNS", source)
        self.assertIn("answer_char_count", source)
        self.assertIn('os.getenv("CHAT_MAX_HISTORY_CHARS", "20000")', source)
        self.assertIn('os.getenv("CHAT_MAX_TOKENS", "1024")', source)
        self.assertIn("answer_needs_expansion", source)
        self.assertIn("answer_looks_incomplete", source)
        self.assertIn("CONTINUE_STEER", source)
        self.assertIn("FINISH_STEER", source)
        self.assertIn("MAX_EXPANSION_PASSES", source)
        self.assertIn("CHAT_TEMPERATURE", source)
        self.assertIn("CHAT_TOP_P", source)
        self.assertIn("CHAT_VLLM_EXTRA_BODY", source)
        self.assertIn("frequency_penalty=CHAT_FREQUENCY_PENALTY", source)
        self.assertNotIn("frequency_penalty=0.5", source)
        self.assertNotIn("presence_penalty=0.3", source)
        self.assertNotIn("trim_runaway_generation", source)
        self.assertNotIn("generation_should_stop", source)
        self.assertNotIn("next_stream_payload", source)
        self.assertIn("expand_search_queries", source)
        self.assertIn("prior_ai_texts=", source)
        self.assertIn("topic_anchor_query", source)
        self.assertNotIn("classify_followup_intent", source)
        self.assertNotIn("uniqueness_instruction", source)
        self.assertNotIn("ANGLE_STEER", source)
        self.assertNotIn("CLARIFY_STEER", source)
        self.assertNotIn("APPLY_STEER", source)
        self.assertNotIn("LENGTH_STEER", source)
        self.assertIn('identity = f"u:{user.pk}"', source)
        self.assertIn("drop_oldest_history(2)", Path(__file__).with_name("chat_llm.py").read_text(encoding="utf-8"))
        self.assertIn("select_pinned_history_rows", source)
        self.assertIn("select_diverse_docs", source)
        self.assertIn("select_chat_source_chips", source)
        self.assertNotIn("def _unique_sources", source)
        self.assertIn("lookup_nkjv_verses", source)
        self.assertIn("extract_teaching_claims", source)
        self.assertIn("format_teaching_claims_block", source)
        self.assertIn("looks_like_library_pull", source)
        self.assertIn("restrict_docs_to_primary_source", source)
        self.assertIn("pin_docs_to_strong_title_matches", source)
        self.assertIn("LIBRARY_PULL_STEER", source)
        self.assertIn("FOLLOWUP_STEER", source)
        self.assertIn("OPENING_RECALL_STEER", source)
        self.assertIn("looks_like_opening_recall", source)
        self.assertIn("format_opening_recall_steer", source)
        self.assertIn("brief_social or opening_recall", source)
        self.assertIn("pin_query=user_query_llm", source)
        self.assertIn('query=prepared.get("topic_query") or user_query_llm', source)
        self.assertIn("_claim_repair_plan", source)
        self.assertIn("_quote_repair_plan", source)
        self.assertIn("_grounding_repair_plan", source)
        self.assertIn("verify_answer_grounding", source)
        self.assertIn("_rag_grounding_fallback", source)
        self.assertIn("_finalize_teaching_answer", source)
        self.assertIn("weave_into_answer", source)
        self.assertIn("strip_retrieval_meta", source)
        self.assertIn("_missing_required_quotes", source)
        self.assertNotIn("appending on-topic retrieved excerpts", source)
        self.assertNotIn("then append notes if needed", source)
        self.assertIn("skip_rewrite_repair", source)
        self.assertIn("compact_teaching_answer", source)
        self.assertIn("QUOTE_CONTINUE_STEER", source)
        self.assertIn("answer_missing_required_quotes", source)
        self.assertIn("has_bible_notes", source)
        self.assertIn("quote_repair_token_budget", source)
        self.assertIn("LiveHistoryPublisher", source)
        self.assertIn("live_history.publish", source)
        self.assertIn("close_old_connections", source)
        self.assertIn("claim_repair_steer", source)
        self.assertIn("repairable_claims", source)
        self.assertIn("_finish_incomplete_extra", source)
        self.assertIn("looks_like_continue_dump", source)
        self.assertIn("retain_title_matches", source)
        self.assertNotIn("_apply_quote_ids", source)
        self.assertNotIn("QuoteIdStreamer", source)
        self.assertNotIn("format_grounding_block", source)
        self.assertNotIn("quote_catalog", source)
        self.assertNotIn("_compact_prior_ai", source)
        self.assertIn("_iter_continuation_tokens", source)
        self.assertIn("_trim_continuation_messages", source)
        self.assertIn("join_continuation", source)
        self.assertNotIn("quote_request_fill", source)
        self.assertNotIn("QUOTE_REQUEST_STEER", source)
        self.assertNotIn("looks_like_quote_request", source)
        self.assertNotIn(
            'yield _sse({"type": "replace", "text": joined_visible})',
            source,
        )
        self.assertIn("keeping the first answer", source)
        self.assertIn("AIMessage(content=msg.ai_response or \"\")", source)
        self.assertIn("looks_like_brief_social", source)
        self.assertIn("CONVERSATIONAL_STEER", source)
        self.assertIn("Skipping Qdrant for brief social message", source)
        self.assertIn("prepared[\"messages\"] = trimmed", source)
        self.assertNotIn("min_tokens", source)
        self.assertNotIn('"No relevant sermon notes found."', source)
        self.assertNotIn("pii_redaction", source)
        self.assertNotIn("redact_user_query", source)
        self.assertIn("llm = get_chat_llm(", source)
        self.assertIn("sse_keepalive()", source)
        self.assertIn("iter_with_sse_heartbeats", source)
        self.assertIn("iter_tokens_with_retries", source)
        self.assertIn("ChatGenerationError", source)
        self.assertIn("EMPTY_STREAM_USER_MESSAGE", source)
        self.assertIn("EMPTY_STREAM_RETRY_TIMEOUT_S", source)
        self.assertIn("is_empty_generation_error", source)
        self.assertIn("wait=False", source)
        self.assertIn("force=True", source)
        self.assertIn("ChatWarmupAPIView", source)
        self.assertNotIn("from langchain_openai import ChatOpenAI", source)
        self.assertNotIn('api_key="not-needed"', source)
        self.assertNotIn("api_key='not-needed'", source)


class GetChatLlmTests(unittest.TestCase):
    @patch("langchain_openai.ChatOpenAI")
    def test_serverless_client_uses_runpod_openai_url(self, mock_cls):
        mock_cls.return_value = MagicMock()
        env = {
            "RUNPOD_VLLM_ENDPOINT_ID": "ep1",
            "RUNPOD_API_KEY": "rp_secret",
            "VLLM_MODEL": "christianai",
            "CHAT_MAX_TOKENS": "2400",
            "CHAT_TIMEOUT_S": "600",
        }
        get_chat_llm(env=env, temperature=0.7)
        kwargs = mock_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://api.runpod.ai/v2/ep1/openai/v1")
        api_key = kwargs["api_key"]
        self.assertTrue(callable(api_key))
        with patch("core.chat_llm.resolve_vllm_api_key", return_value=""):
            self.assertEqual(api_key(), "rp_secret")
        self.assertEqual(kwargs["default_headers"]["Authorization"], "Bearer rp_secret")
        self.assertEqual(kwargs["model"], "christianai")
        self.assertEqual(kwargs["timeout"], 600.0)
        self.assertEqual(kwargs["max_retries"], 1)

    @patch("langchain_openai.ChatOpenAI")
    def test_local_client_keeps_placeholder_key(self, mock_cls):
        mock_cls.return_value = MagicMock()
        env = {"VLLM_URL": "http://127.0.0.1:8010/v1"}
        get_chat_llm(env=env)
        kwargs = mock_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "http://127.0.0.1:8010/v1")
        self.assertEqual(kwargs["api_key"], "not-needed")
        self.assertNotIn("Authorization", kwargs["default_headers"])
        self.assertEqual(kwargs["max_retries"], 2)
        self.assertEqual(kwargs["temperature"], CHAT_TEMPERATURE)
        self.assertEqual(kwargs["top_p"], CHAT_TOP_P)
        self.assertEqual(kwargs["presence_penalty"], CHAT_PRESENCE_PENALTY)
        self.assertEqual(kwargs["frequency_penalty"], CHAT_FREQUENCY_PENALTY)
        self.assertEqual(kwargs["extra_body"], CHAT_VLLM_EXTRA_BODY)
