import unittest

from .pii_redaction import REDACTED, query_text_for_llm, redact_user_query
from .scope_gate import parse_scope_gate_response


class ScopeGateParserTests(unittest.TestCase):
    def test_yes_plain(self):
        self.assertIs(parse_scope_gate_response("YES"), True)

    def test_no_plain(self):
        self.assertIs(parse_scope_gate_response("NO"), False)

    def test_yes_with_punctuation(self):
        self.assertIs(parse_scope_gate_response("Yes."), True)

    def test_no_extra_words_defaults_first_token(self):
        self.assertIs(parse_scope_gate_response("NO — out of scope"), False)

    def test_empty_returns_none(self):
        self.assertIsNone(parse_scope_gate_response(""))
        self.assertIsNone(parse_scope_gate_response("   "))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_scope_gate_response("maybe"))


class PiiRedactionTests(unittest.TestCase):
    def test_email_redacted(self):
        out = redact_user_query("Email me at user.name+tag@example.co.uk soon")
        self.assertNotIn("example.co.uk", out)
        self.assertIn(REDACTED, out)

    def test_phone_redacted(self):
        out = redact_user_query("Call (713) 555-0199 or 7135550200")
        self.assertNotIn("713", out)
        self.assertIn(REDACTED, out)

    def test_street_redacted(self):
        out = redact_user_query("We live at 742 Evergreen Terrace Springfield")
        self.assertNotIn("Evergreen", out)
        self.assertIn(REDACTED, out)

    def test_biblical_names_kept(self):
        out = redact_user_query("Paul and Timothy wrote about Mary Magdalene")
        self.assertNotIn(REDACTED, out)
        self.assertIn("Mary", out)

    def test_non_biblical_name_redacted(self):
        out = redact_user_query("Please pray for Jennifer Wilkins during surgery")
        self.assertNotIn("Jennifer", out)
        self.assertNotIn("Wilkins", out)
        self.assertIn(REDACTED, out)

    def test_single_capitalized_name_not_redacted(self):
        """Single Title Case tokens are not treated as names (too many false positives)."""
        out = redact_user_query("Pray for Jennifer during surgery")
        self.assertIn("Jennifer", out)
        self.assertNotIn(REDACTED, out)

    def test_theological_two_word_phrase_kept(self):
        out = redact_user_query("Mercy Grace abound")
        self.assertNotIn(REDACTED, out)

    def test_theology_phrase_kept(self):
        out = redact_user_query("Explain the New Testament view of the Holy Spirit")
        self.assertNotIn(REDACTED, out)

    def test_query_text_for_llm_strips_redacted_markers(self):
        stored = redact_user_query("What do Mary and Joseph do? I am Jennifer Wilkins.")
        self.assertIn(REDACTED, stored)
        llm = query_text_for_llm(stored)
        self.assertNotIn(REDACTED, llm)
        self.assertNotIn("[REDACTED]", llm)
        self.assertIn("Mary", llm)
        self.assertIn("someone", llm.lower())


if __name__ == "__main__":
    unittest.main()
