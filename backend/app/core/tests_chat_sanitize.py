import unittest

from .chat_sanitize import (
    looks_like_rewrite_leak,
    sanitize_chat_answer,
    sanitize_history_text,
    sanitize_stream_delta,
)


class ChatSanitizeTests(unittest.TestCase):
    def test_strips_chinese_rewrite_instruction_and_keeps_quoted_draft(self):
        leaked = (
            "Shame needs compassion rather than condemnation.\n\n"
            "Moreover, repairing the damage caused by shame requires more than just "
            "forgiveness; it necessitates rebuilding self-esteem and"
            "重塑回答以确保它包含来自参考文献的直接引文，并且内容充实，符合用户问题的要求。"
            "以下是调整后的回答：\n\n"
            "---\n\n"
            "Pastor Don Nordin teaches, \"People act out because they feel unworthy of love.\" "
            "Restoration begins in a community that tells the truth and stays.\n\n"
            "---\n\n"
            "这段回答包含了直接引用，解释了这些问题的根本原因，并提出了修复羞耻感造成的伤害的方法。"
            "通过创造一个支持性的环境，帮助那些受到这些问题影响的人恢复尊严和自我价值。"
        )
        cleaned = sanitize_chat_answer(leaked, language="en")
        self.assertNotIn("重塑", cleaned)
        self.assertNotIn("调整后的回答", cleaned)
        self.assertNotIn("这段回答包含了", cleaned)
        self.assertIn("unworthy of love", cleaned)
        self.assertIn("Pastor Don Nordin", cleaned)

    def test_stream_delta_drops_han_for_english_ui(self):
        self.assertEqual(sanitize_stream_delta("self-esteem and重塑回答", language="en"), "self-esteem and")
        self.assertIn("重塑", sanitize_stream_delta("重塑回答", language="zh"))

    def test_leaves_a_normal_english_reply_alone(self):
        text = 'Pastor Don Nordin teaches, "Feed the flock." John 21:17 calls us to that work.'
        self.assertEqual(sanitize_chat_answer(text, language="en"), text)

    def test_strips_mid_sentence_chinese_on_long_session_racism_reply(self):
        leaked = (
            "Pastor Don Nordin addresses racism as both a personal sin and a structural sin. "
            "He does not treat it as merely private prejudice, nor as only a social system.\n\n"
            "While terms like \"woke\" and \"CRT\" are part of today's conversation, he insists "
            "they must be tested by Scripture. Reconciliation is not a slogan.\n\n"
            "One of these foundational truths is the concept of \"the image of God.\" This "
            "principle asserts that every human being is created in the likeness of God, "
            "regardless of skin color, socioeconomic status, or any other distinguishing factor. "
            "Recognizing this inherent value in each person compels us to reject"
            "任何形式的歧视，并努力实现真正的和解。\n\n"
            "诺丁牧师强调，种族主义既是个人的罪，也是结构性的罪。他使用圣经语言，"
            "如上帝的形象和同一血脉，而不是当代的政治口号来谈论这个问题。\n\n"
            "真正的和解要求教会承认这两种层面的罪，并在基督里彼此相爱，拒绝任何形式的歧视。"
        )
        cleaned = sanitize_chat_answer(leaked, language="en")
        self.assertNotRegex(cleaned, r"[\u3400-\u9fff]")
        self.assertIn("image of God", cleaned)
        self.assertIn("personal sin", cleaned)
        self.assertNotIn("歧视", cleaned)

    def test_joins_english_when_half_the_reply_is_chinese(self):
        mixed = (
            "Pastor Don Nordin teaches that shame is healed in community. "
            "这段完全是中文而且会污染下一轮对话的上下文。"
            "John 21:17 still calls us to feed the flock."
        )
        cleaned = sanitize_chat_answer(mixed, language="en")
        self.assertNotRegex(cleaned, r"[\u3400-\u9fff]")
        self.assertIn("shame is healed", cleaned)
        self.assertIn("feed the flock", cleaned)

    def test_history_ai_turn_cannot_reseed_chinese(self):
        prior = (
            "Restoration begins with truth. "
            "重塑回答以确保它包含直接引文。以下是调整后的回答： "
            "Keep walking in the light."
        )
        cleaned = sanitize_history_text(prior, language="en")
        self.assertNotRegex(cleaned, r"[\u3400-\u9fff]")
        self.assertIn("Restoration", cleaned)

    def test_detects_rewrite_leak_in_long_session_reply(self):
        self.assertTrue(
            looks_like_rewrite_leak(
                "self-esteem and重塑回答以确保它包含直接引文",
                language="en",
            )
        )
        self.assertFalse(looks_like_rewrite_leak("Feed the flock in love.", language="en"))

    def test_strips_echoed_language_reminder(self):
        text = (
            'Pastor Don Nordin teaches, "Feed the flock."\n\n'
            "[Write the reply only in English. Do not output Chinese, Japanese, "
            "Korean, rewrite plans, or a second draft.]"
        )
        cleaned = sanitize_chat_answer(text, language="en")
        self.assertNotIn("Write the reply only in English", cleaned)
        self.assertIn("Feed the flock", cleaned)

    def test_stream_delta_keeps_leading_space(self):
        self.assertEqual(sanitize_stream_delta(" flock", language="en"), " flock")
