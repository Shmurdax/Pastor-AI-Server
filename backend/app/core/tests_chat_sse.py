import unittest
from types import SimpleNamespace

from core.chat_sse import (
    chunk_text,
    iter_chat_tokens,
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


if __name__ == "__main__":
    unittest.main()
