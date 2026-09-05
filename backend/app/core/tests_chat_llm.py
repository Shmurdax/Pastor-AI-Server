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

    def test_model_name(self):
        self.assertEqual(resolve_vllm_model({}), "christianai")
        self.assertEqual(resolve_vllm_model({"VLLM_MODEL": "christianai"}), "christianai")


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
        self.assertEqual(kwargs["api_key"], "rp_secret")
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
        self.assertEqual(kwargs["max_retries"], 2)
