import unittest
from unittest.mock import MagicMock, patch

from core.chat_llm import (
    discovered_worker_max_model_len,
    estimate_chat_tokens,
    fit_chat_budget,
    get_chat_llm,
    normalize_vllm_base_url,
    parse_context_length_error,
    remember_worker_max_model_len,
    reset_discovered_worker_max_model_len_for_tests,
    resolve_chat_context_window,
    resolve_vllm_api_key,
    resolve_vllm_model,
    resolve_vllm_url,
    vllm_is_remote,
    vllm_url_is_local,
)


class VllmUrlResolutionTests(unittest.TestCase):
    def setUp(self):
        reset_discovered_worker_max_model_len_for_tests()

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
        overflow = (
            "Error code: 400 - This model's maximum context length is 4096 tokens. "
            "However, you requested 4629 tokens (3129 in the messages, 1500 in the completion)."
        )
        self.assertEqual(parse_context_length_error(overflow), 4096)
        remember_worker_max_model_len(4096)
        self.assertEqual(discovered_worker_max_model_len(), 4096)
        self.assertEqual(
            resolve_chat_context_window({
                "CHAT_CONTEXT_WINDOW": "32768",
                "VLLM_MAX_MODEL_LEN": "32768",
            }),
            4096,
        )

    def test_fit_chat_budget_drops_history_on_4096_worker(self):
        env = {"CHAT_CONTEXT_WINDOW": "32768", "VLLM_MAX_MODEL_LEN": "4096"}
        history = [
            type("Msg", (), {"content": "What is the purpose of the church?"})(),
            type("Msg", (), {"content": "A long previous pastoral answer " * 80})(),
        ]
        fitted, hist, completion, used = fit_chat_budget(
            "REFERENCE NOTES:\n" + ("sermon chunk " * 400),
            history,
            "Summarize his view of the Holy Spirit.",
            6144,
            env=env,
        )
        self.assertEqual(hist, [])
        self.assertLessEqual(used + completion + 192, 4096)
        self.assertIn("sermon chunk", fitted)

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

    def test_chat_view_uses_get_chat_llm_not_placeholder_key(self):
        from pathlib import Path

        source = Path(__file__).with_name("views.py").read_text(encoding="utf-8")
        self.assertIn("from .chat_llm import", source)
        self.assertIn("get_chat_llm", source)
        self.assertIn("fit_chat_budget", source)
        self.assertIn("EMPTY_REFERENCE_NOTES", source)
        self.assertIn("NOTES_MARKER", source)
        self.assertIn("LENGTH_STEER", source)
        self.assertIn("answer_needs_expansion", source)
        self.assertIn("CONTINUE_STEER", source)
        self.assertIn("MAX_EXPANSION_PASSES", source)
        self.assertIn("presence_penalty=0.25", source)
        self.assertIn("frequency_penalty=0.15", source)
        self.assertIn("_iter_continuation_tokens", source)
        self.assertIn("_trim_continuation_messages", source)
        self.assertIn("keeping the first answer", source)
        self.assertIn('human_content = f"{LENGTH_STEER}{user_query_llm.strip()}"', source)
        self.assertIn("prepared[\"messages\"] = trimmed", source)
        self.assertIn("parse_context_length_error", source)
        self.assertIn("_refit_prepared", source)
        self.assertNotIn("min_tokens", source)
        self.assertNotIn('"No relevant sermon notes found."', source)
        self.assertNotIn("pii_redaction", source)
        self.assertNotIn("redact_user_query", source)
        self.assertIn("llm = get_chat_llm(", source)
        self.assertIn("sse_keepalive()", source)
        self.assertIn("iter_with_sse_heartbeats", source)
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
        self.assertEqual(kwargs["max_retries"], 6)

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
