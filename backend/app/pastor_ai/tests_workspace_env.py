import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pastor_ai import workspace_env


class LoadWorkspaceEnvTests(unittest.TestCase):
    def test_reapplies_secrets_after_environ_is_zeroed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "config.env").write_text(
                "RUNPOD_API_KEY=rpa_live_key\nVLLM_API_KEY=not-needed\nCPU_ONLY=1\n"
            )
            os.environ["RUNPOD_API_KEY"] = "not-needed"
            os.environ["VLLM_API_KEY"] = "not-needed"
            os.environ.pop("CPU_ONLY", None)
            with patch.object(workspace_env, "_candidate_files", return_value=[root / "config.env"]):
                workspace_env.load_workspace_env()
                self.assertEqual(os.environ["RUNPOD_API_KEY"], "rpa_live_key")
                self.assertEqual(os.environ["VLLM_API_KEY"], "not-needed")
                self.assertEqual(os.environ["CPU_ONLY"], "1")
                os.environ["RUNPOD_API_KEY"] = ""
                workspace_env.load_workspace_env()
                self.assertEqual(os.environ["RUNPOD_API_KEY"], "rpa_live_key")
                overlay = workspace_env.env_with_workspace({"RUNPOD_API_KEY": "", "CPU_ONLY": "1"})
                self.assertEqual(overlay["RUNPOD_API_KEY"], "rpa_live_key")
                self.assertEqual(overlay["CPU_ONLY"], "1")

    def test_file_endpoint_id_beats_stale_pod_env(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "tokens.env").write_text(
                "RUNPOD_VLLM_ENDPOINT_ID=vllm-dev-endpoint\n"
                "VLLM_URL=https://api.runpod.ai/v2/vllm-dev-endpoint/openai/v1\n"
                "VLLM_MODE=serverless\n"
            )
            stale = {
                "RUNPOD_VLLM_ENDPOINT_ID": "4kjnsgh3pek3vu",
                "VLLM_URL": "https://api.runpod.ai/v2/4kjnsgh3pek3vu/openai/v1",
                "VLLM_MODE": "serverless",
                "CHAT_MAX_TOKENS": "512",
            }
            os.environ.update(stale)
            with patch.object(workspace_env, "_candidate_files", return_value=[root / "tokens.env"]):
                workspace_env.load_workspace_env()
                self.assertEqual(os.environ["RUNPOD_VLLM_ENDPOINT_ID"], "vllm-dev-endpoint")
                overlay = workspace_env.env_with_workspace(stale)
                self.assertEqual(overlay["RUNPOD_VLLM_ENDPOINT_ID"], "vllm-dev-endpoint")
                self.assertEqual(
                    overlay["VLLM_URL"],
                    "https://api.runpod.ai/v2/vllm-dev-endpoint/openai/v1",
                )
                self.assertEqual(overlay["CHAT_MAX_TOKENS"], "512")

    def test_keeps_apostrophe_in_from_email(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "config.env").write_text(
                'DEFAULT_FROM_EMAIL="Nordin\'s AI <info@thenordins.org>"\n'
                "GMAIL_SENDER=info@thenordins.org\n"
            )
            with patch.object(workspace_env, "_candidate_files", return_value=[root / "config.env"]):
                values = workspace_env.workspace_env_values()
        self.assertEqual(values["GMAIL_SENDER"], "info@thenordins.org")
        self.assertEqual(values["DEFAULT_FROM_EMAIL"], "Nordin's AI <info@thenordins.org>")

    def tearDown(self):
        for key in (
            "RUNPOD_API_KEY",
            "VLLM_API_KEY",
            "CPU_ONLY",
            "RUNPOD_VLLM_ENDPOINT_ID",
            "VLLM_URL",
            "VLLM_MODE",
            "CHAT_MAX_TOKENS",
        ):
            os.environ.pop(key, None)
