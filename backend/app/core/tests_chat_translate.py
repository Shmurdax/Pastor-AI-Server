import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from .chat_language import SUPPORTED_CHAT_LANGUAGES
from .chat_translate import (
    _parse_numbered_items,
    display_reply,
    english_search_query,
    translate_texts,
)


DISPLAY_LANGUAGES = ("es", "fr", "pt", "de", "ko", "zh")


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


class ChatTranslatePipelineTests(unittest.TestCase):
    def test_supported_languages_cover_the_display_page(self):
        self.assertEqual(
            set(SUPPORTED_CHAT_LANGUAGES),
            {"en", "es", "fr", "pt", "de", "ko", "zh"},
        )

    def test_english_query_skips_translation(self):
        with patch("core.chat_translate.translate_to_english") as mock_to_en:
            self.assertEqual(english_search_query("What is hope?", "en"), "What is hope?")
            mock_to_en.assert_not_called()

    def test_english_reply_skips_translation(self):
        with patch("core.chat_translate.translate_reply") as mock_reply:
            self.assertEqual(display_reply("Faith grows.", "en"), "Faith grows.")
            mock_reply.assert_not_called()

    def test_every_non_english_ui_language_translates_inbound_and_outbound(self):
        with patch("core.chat_translate.translate_to_english", return_value="Hope in Christ") as mock_to_en:
            with patch("core.chat_translate.translate_reply", return_value="translated") as mock_reply:
                for lang in DISPLAY_LANGUAGES:
                    self.assertEqual(english_search_query("pregunta", lang), "Hope in Christ")
                    self.assertEqual(display_reply("Faith grows.", lang), "translated")
                self.assertEqual(mock_to_en.call_count, len(DISPLAY_LANGUAGES))
                self.assertEqual(mock_reply.call_count, len(DISPLAY_LANGUAGES))

    def test_batch_parse_failure_translates_each_item(self):
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content="no markers here")
        with patch("core.chat_translate._chat_llm", return_value=llm):
            with patch(
                "core.chat_translate.translate_reply",
                side_effect=lambda text, language: f"{language}:{text}",
            ):
                self.assertEqual(translate_texts(["Hello", "World"], "fr"), ["fr:Hello", "fr:World"])
