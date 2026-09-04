import unittest
from types import SimpleNamespace

from core.chat_sse import chunk_text, iter_chat_tokens, sse_pack, wants_chat_stream


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

    def test_iter_chat_tokens_skips_empty_chunks(self):
        bound = SimpleNamespace(
            stream=lambda _messages: [
                SimpleNamespace(content="Faith "),
                SimpleNamespace(content=""),
                SimpleNamespace(content="grows"),
            ]
        )
        self.assertEqual(list(iter_chat_tokens(bound, [])), ["Faith ", "grows"])


if __name__ == "__main__":
    unittest.main()
