import unittest

from .pii_redaction import REDACTED, query_text_for_llm, redact_user_query
from .scope_gate import parse_scope_gate_response
from .website_crawl.crawler import normalize_url, path_is_excluded
from .website_crawl.extract import (
    classify_content_type,
    host_allowed_for_page,
    html_to_markdown,
    source_name_for_url,
)


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


class WebsiteCrawlHelperTests(unittest.TestCase):
    def test_excludes_cart_and_thank_you(self):
        self.assertTrue(path_is_excluded("https://thenordins.org/store/cart"))
        self.assertTrue(path_is_excluded("https://thenordins.org/booking-thank-you"))
        self.assertTrue(path_is_excluded("https://thenordins.org/signin"))
        self.assertFalse(path_is_excluded("https://thenordins.org/about"))

    def test_socials_not_allowed(self):
        self.assertTrue(host_allowed_for_page("https://mycthouston.org/visit"))
        self.assertFalse(host_allowed_for_page("https://www.facebook.com/TheNordins"))

    def test_content_type_classification(self):
        self.assertEqual(
            classify_content_type("https://thenordins.org/store-default/kings-and-priests"),
            "book_resource",
        )
        self.assertEqual(classify_content_type("https://mycthouston.org/visit"), "church_info")
        self.assertEqual(
            classify_content_type("https://thenordins.org/know-your-why-session-one"),
            "teaching_media",
        )

    def test_normalize_strips_www_and_trailing_slash(self):
        self.assertEqual(
            normalize_url("https://www.mycthouston.org/visit/"),
            "https://mycthouston.org/visit",
        )

    def test_html_to_markdown_keeps_service_times(self):
        html = (
            "<html><head><title>Visit Us</title></head><body><main>"
            "<h1>Visit Us</h1>"
            "<p>Services begin at 10am both in person and online.</p>"
            "<p>Youth Services every Wednesday at 7pm.</p>"
            "</main></body></html>"
        )
        title, content_type, markdown = html_to_markdown(
            html, "https://mycthouston.org/visit", "CT Houston"
        )
        self.assertEqual(title, "Visit Us")
        self.assertEqual(content_type, "church_info")
        self.assertIn("10am", markdown)
        self.assertIn("Source URL: https://mycthouston.org/visit", markdown)
        self.assertTrue(source_name_for_url("https://mycthouston.org/visit").startswith("web__"))


if __name__ == "__main__":
    unittest.main()
