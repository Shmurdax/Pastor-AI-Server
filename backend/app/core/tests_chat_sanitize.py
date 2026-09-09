import unittest

from .chat_sanitize import sanitize_chat_answer, sanitize_stream_delta


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
