import importlib.util
import unittest
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[3] / "serverless" / "apply_vllm_coldstart.py"
    spec = importlib.util.spec_from_file_location("apply_vllm_coldstart", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ApplyVllmColdstartTests(unittest.TestCase):
    def test_merge_points_cache_at_runpod_volume(self):
        mod = _load()
        merged = mod.merge_vllm_env({
            "MODEL_NAME": "Qwen/Qwen2.5-14B-Instruct-AWQ",
            "HF_TOKEN": "hf_secret",
            "DOWNLOAD_DIR": "/models",
        })
        self.assertEqual(merged["HF_TOKEN"], "hf_secret")
        self.assertEqual(merged["DOWNLOAD_DIR"], "/runpod-volume/huggingface-cache")
        self.assertEqual(merged["HF_HOME"], "/runpod-volume/huggingface-cache")
        self.assertEqual(merged["VLLM_CACHE_ROOT"], "/runpod-volume/vllm_cache")

    def test_env_list_and_redact(self):
        mod = _load()
        parsed = mod.env_as_dict([
            {"key": "HF_TOKEN", "value": "hf_secret"},
            {"key": "MODEL_NAME", "value": "Qwen/Qwen2.5-14B-Instruct-AWQ"},
        ])
        self.assertEqual(parsed["HF_TOKEN"], "hf_secret")
        redacted = mod.redact({"HF_TOKEN": "hf_secret", "idleTimeout": 900})
        self.assertTrue(str(redacted["HF_TOKEN"]).endswith("***redacted***"))
        self.assertEqual(redacted["idleTimeout"], 900)


if __name__ == "__main__":
    unittest.main()
