import unittest

from .chat_translate import _parse_numbered_items


class ChatTranslateParseTests(unittest.TestCase):
    def test_parse_items(self):
        raw = (
            "<<<ITEM 1>>>\nHola mundo\n<<<END ITEM 1>>>\n\n"
            "<<<ITEM 2>>>\nSegunda respuesta\n<<<END ITEM 2>>>"
        )
        self.assertEqual(
            _parse_numbered_items(raw, 2),
            ["Hola mundo", "Segunda respuesta"],
        )

    def test_parse_incomplete_returns_none(self):
        raw = "<<<ITEM 1>>>\nOnly one\n<<<END ITEM 1>>>"
        self.assertIsNone(_parse_numbered_items(raw, 2))
