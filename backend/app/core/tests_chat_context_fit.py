"""Context-window fitting for multi-turn chat → vLLM prompts."""

from __future__ import annotations

import os
from unittest.mock import patch

from django.test import SimpleTestCase

from core.basic_chat import (
    estimate_message_tokens,
    fit_messages_for_context,
    stream_message_tokens,
)


class FitMessagesForContextTests(SimpleTestCase):
    def setUp(self):
        self._env = {
            key: os.environ.get(key)
            for key in ("CHAT_MAX_MODEL_LEN", "CHAT_CHARS_PER_TOKEN")
        }
        os.environ["CHAT_MAX_MODEL_LEN"] = "8192"
        os.environ["CHAT_CHARS_PER_TOKEN"] = "4"

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_oversized_history_is_dropped_and_max_tokens_clamped(self):
        system = {"role": "system", "content": "sys " * 50}
        history = []
        for i in range(8):
            history.append({"role": "user", "content": f"q{i} " + ("draft " * 400)})
            history.append({"role": "assistant", "content": f"a{i} " + ("notes " * 500)})
        final = {"role": "user", "content": "Write sermon notes on grace.\n" + ("excerpt " * 800)}
        messages = [system, *history, final]
        fitted, max_tokens, meta = fit_messages_for_context(messages, 1600)
        self.assertLess(estimate_message_tokens(fitted) + max_tokens, 8192)
        self.assertTrue(meta["trimmed"])
        self.assertGreater(meta["dropped_messages"], 0)
        self.assertLessEqual(meta["fitted_chars"], meta["original_chars"])
        self.assertLessEqual(max_tokens, 1600)
        self.assertGreaterEqual(max_tokens, 256)
        self.assertEqual(fitted[0]["role"], "system")
        self.assertEqual(fitted[-1]["role"], "user")
        self.assertIn("grace", fitted[-1]["content"])

    def test_small_prompt_unchanged(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is faith?"},
        ]
        fitted, max_tokens, meta = fit_messages_for_context(messages, 800)
        self.assertFalse(meta["trimmed"])
        self.assertEqual(max_tokens, 800)
        self.assertEqual(len(fitted), 2)
        self.assertEqual(fitted[1]["content"], "What is faith?")

    def test_empty_stream_retries_once_after_aggressive_fit(self):
        calls = {"n": 0}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    yield b'data: {"choices":[{"delta":{},"finish_reason":null}]}\n'
                    return
                yield b'data: {"choices":[{"delta":{"content":"Recovered notes"},"finish_reason":null}]}\n'
                yield b"data: [DONE]\n"

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old " * 2000},
            {"role": "assistant", "content": "ans " * 2000},
            {"role": "user", "content": "Write notes on hope"},
        ]
        with patch("core.basic_chat._post_llm", return_value=FakeResp()):
            text = "".join(stream_message_tokens(messages, max_tokens=1600))
        self.assertEqual(text, "Recovered notes")
        self.assertEqual(calls["n"], 2)
