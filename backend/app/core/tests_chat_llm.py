import unittest
from unittest.mock import MagicMock, patch

from core.chat_llm import (
    get_chat_llm,
    normalize_vllm_base_url,
    resolve_vllm_api_key,
    resolve_vllm_model,
    resolve_vllm_url,
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

        self.assertEqual(resolve_chat_context_window({"CHAT_CONTEXT_WINDOW": "8192"}), 8192)
        self.assertEqual(
            resolve_chat_context_window({
                "CHAT_CONTEXT_WINDOW": "8192",
                "VLLM_MAX_MODEL_LEN": "4096",
            }),
            4096,
        )

    def test_chat_view_uses_get_chat_llm_not_placeholder_key(self):
        from pathlib import Path

        source = Path(__file__).with_name("views.py").read_text(encoding="utf-8")
        self.assertIn("from .chat_llm import get_chat_llm", source)
        self.assertIn("llm = get_chat_llm(", source)
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
