import unittest

from .chat_language import (
    language_display_name,
    language_generation_reminder,
    language_reply_instruction,
    normalize_chat_language,
)


class ChatLanguageTests(unittest.TestCase):
    def test_normalize_defaults_to_english(self):
        self.assertEqual(normalize_chat_language(None), "en")
        self.assertEqual(normalize_chat_language(""), "en")
        self.assertEqual(normalize_chat_language("xx"), "en")

    def test_normalize_supported_codes(self):
        self.assertEqual(normalize_chat_language("es"), "es")
        self.assertEqual(normalize_chat_language("ES"), "es")
        self.assertEqual(normalize_chat_language("pt-BR"), "pt")
        self.assertEqual(normalize_chat_language("zh_CN"), "zh")
        self.assertEqual(normalize_chat_language("zh-Hans"), "zh")

    def test_aliases(self):
        self.assertEqual(normalize_chat_language("spa"), "es")
        self.assertEqual(normalize_chat_language("fra"), "fr")

    def test_display_name(self):
        self.assertEqual(language_display_name("es"), "Spanish")
        self.assertEqual(language_display_name("ko"), "Korean")

    def test_english_instruction(self):
        text = language_reply_instruction("en")
        self.assertIn("English", text)
        self.assertIn("<language>", text)
        self.assertIn("Never write Chinese", text)
        self.assertIn("reshape", text.lower())

    def test_spanish_instruction(self):
        text = language_reply_instruction("es")
        self.assertIn("Spanish", text)
        self.assertIn("NKJV", text)
        self.assertNotIn("Write your entire reply in English.", text)

    def test_generation_reminder_locks_english_on_long_threads(self):
        reminder = language_generation_reminder("en")
        self.assertIn("Write the reply only in English", reminder)
        self.assertIn("Do not output Chinese", reminder)
        self.assertEqual(language_generation_reminder("zh"), "")
