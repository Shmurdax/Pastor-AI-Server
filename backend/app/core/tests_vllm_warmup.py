import unittest
from unittest.mock import MagicMock, patch

from core.vllm_warmup import reset_warmup_state_for_tests, warmup_vllm_worker


class VllmWarmupTests(unittest.TestCase):
    def setUp(self):
        reset_warmup_state_for_tests()

    def tearDown(self):
        reset_warmup_state_for_tests()

    def test_first_call_starts_background_ping(self):
        env = {
            "RUNPOD_VLLM_ENDPOINT_ID": "ep1",
            "RUNPOD_API_KEY": "rp_secret",
        }
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = MagicMock(status=200)
            result = warmup_vllm_worker(env=env, wait=True, timeout_s=2.0, cooldown_s=45)
        self.assertTrue(result["warming"])
        self.assertFalse(result["skipped"])
        req = mock_open.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.runpod.ai/v2/ep1/openai/v1/models")
        self.assertEqual(req.get_header("Authorization"), "Bearer rp_secret")

    def test_cooldown_skips_second_ping(self):
        env = {"VLLM_URL": "http://127.0.0.1:8010/v1"}
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = MagicMock(status=200)
            first = warmup_vllm_worker(env=env, wait=True, timeout_s=2.0, cooldown_s=45)
            second = warmup_vllm_worker(env=env, wait=True, timeout_s=2.0, cooldown_s=45)
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])
        self.assertEqual(mock_open.call_count, 1)

    def test_failed_ping_still_reports_warming(self):
        env = {"VLLM_URL": "http://127.0.0.1:9/v1"}
        with patch("urllib.request.urlopen", side_effect=TimeoutError("cold start")):
            result = warmup_vllm_worker(env=env, wait=True, timeout_s=2.0, cooldown_s=45)
        self.assertTrue(result["ok"])
        self.assertTrue(result["warming"])


if __name__ == "__main__":
    unittest.main()
