import unittest
from types import SimpleNamespace

from core.chat_sse import (
    ChatGenerationError,
    EMPTY_STREAM_USER_MESSAGE,
    chunk_text,
    is_empty_generation_error,
    is_retryable_stream_error,
    iter_chat_tokens,
    iter_tokens_with_retries,
    iter_with_sse_heartbeats,
    split_stream_text,
    sse_keepalive,
    sse_pack,
    wants_chat_stream,
)


class ChatSseTests(unittest.TestCase):
    def test_chunk_text_reads_string_and_list_content(self):
        self.assertEqual(chunk_text(SimpleNamespace(content="Hello")), "Hello")
        self.assertEqual(
            chunk_text(SimpleNamespace(content=[{"type": "text", "text": "Hi"}])),
            "Hi",
        )

    def test_sse_pack_and_stream_flag(self):
        self.assertEqual(
            sse_pack({"type": "delta", "text": "a"}),
            'data: {"type": "delta", "text": "a"}\n\n',
        )
        self.assertTrue(wants_chat_stream(True, ""))
        self.assertTrue(wants_chat_stream(False, "text/event-stream"))
        self.assertFalse(wants_chat_stream(False, "application/json"))
        self.assertGreaterEqual(len(sse_keepalive()), 4096)
        self.assertTrue(sse_keepalive().startswith(": keepalive"))
        self.assertEqual(split_stream_text("short"), ["short"])
        self.assertEqual(split_stream_text("abcdefghij", max_chars=4), ["abcd", "efgh", "ij"])

    def test_iter_chat_tokens_skips_empty_chunks(self):
        bound = SimpleNamespace(
            stream=lambda _messages: [
                SimpleNamespace(content="Faith "),
                SimpleNamespace(content=""),
                SimpleNamespace(content="grows"),
            ]
        )
        self.assertEqual(list(iter_chat_tokens(bound, [])), ["Faith ", "grows"])

    def test_heartbeats_while_producer_blocks(self):
        import time

        def producer():
            time.sleep(0.22)
            yield sse_pack({"type": "delta", "text": "Hi"})

        chunks = list(iter_with_sse_heartbeats(producer, interval_s=0.05))
        self.assertTrue(any(item == sse_keepalive() for item in chunks))
        self.assertEqual(chunks[-1], sse_pack({"type": "delta", "text": "Hi"}))

    def test_empty_generation_error_is_retryable(self):
        exc = ValueError("No generation chunks were returned")
        self.assertTrue(is_empty_generation_error(exc))
        self.assertTrue(is_retryable_stream_error(exc))
        self.assertFalse(is_retryable_stream_error(PermissionError("invalid_auth")))

    def test_iter_tokens_retries_langchain_empty_error_then_yields(self):
        calls = {"n": 0}

        def fake_stream():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("No generation chunks were returned")
            yield "Grace"

        tokens = list(
            iter_tokens_with_retries(
                fake_stream,
                attempts=3,
                wait_s=0,
                warmup=lambda: None,
                sleep=lambda _s: None,
            )
        )
        self.assertEqual(tokens, ["Grace"])
        self.assertEqual(calls["n"], 2)

    def test_iter_tokens_retries_empty_stream_then_yields(self):
        calls = {"n": 0}
        warmups = []
        sleeps = []

        def stream_fn():
            calls["n"] += 1
            if calls["n"] < 3:
                return []
            return [type("Chunk", (), {"content": "Faith"})()]

        def fake_stream():
            for chunk in stream_fn():
                yield chunk.content

        tokens = list(
            iter_tokens_with_retries(
                fake_stream,
                attempts=3,
                wait_s=4,
                warmup=lambda: warmups.append(True),
                sleep=lambda s: sleeps.append(s),
            )
        )
        self.assertEqual(tokens, ["Faith"])
        self.assertEqual(calls["n"], 3)
        self.assertEqual(warmups, [True, True])
        self.assertEqual(sleeps, [4, 4])

    def test_iter_tokens_raises_after_exhausted_empty_retries(self):
        def fake_stream():
            if False:
                yield "x"

        with self.assertRaises(ValueError) as ctx:
            list(
                iter_tokens_with_retries(
                    fake_stream,
                    attempts=2,
                    wait_s=0,
                    warmup=lambda: None,
                    sleep=lambda _s: None,
                )
            )
        self.assertTrue(is_empty_generation_error(ctx.exception))

    def test_iter_tokens_does_not_retry_after_tokens_started(self):
        def fake_stream():
            yield "Faith"
            raise ConnectionError("connection reset")

        with self.assertRaises(ConnectionError):
            list(
                iter_tokens_with_retries(
                    fake_stream,
                    attempts=3,
                    wait_s=4,
                    warmup=lambda: self.fail("must not warmup after tokens"),
                    sleep=lambda _s: self.fail("must not sleep after tokens"),
                )
            )

    def test_chat_generation_error_is_user_facing(self):
        exc = ChatGenerationError(EMPTY_STREAM_USER_MESSAGE)
        self.assertIsInstance(exc, RuntimeError)
        self.assertIn("GPU chat worker", str(exc))


if __name__ == "__main__":
    unittest.main()
