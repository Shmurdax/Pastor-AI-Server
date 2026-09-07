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

    def tearDown(self):
        for key in ("RUNPOD_API_KEY", "VLLM_API_KEY", "CPU_ONLY"):
            os.environ.pop(key, None)
