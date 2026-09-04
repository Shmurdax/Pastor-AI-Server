import unittest

from .chat_system_prompt import (
    biblical_characters_instruction,
    build_chat_system_prompt,
    find_biblical_character_names,
)
from .document_cleanup import (
    clean_extracted_document,
    clean_markdown_document,
    format_cleanup_log,
)
from .pii_redaction import REDACTED, query_text_for_llm, redact_user_query
from .scope_gate import always_in_scope_query, parse_scope_gate_response
from .website_crawl.crawler import normalize_url, path_is_excluded
from .website_crawl.extract import (
    classify_content_type,
    host_allowed_for_page,
    html_to_markdown,
    source_name_for_url,
)


class ChatSystemPromptTests(unittest.TestCase):
    def test_finds_biblical_character_names(self):
        names = find_biblical_character_names("What did Moses and Timothy teach about faith?")
        lowered = {n.lower() for n in names}
        self.assertIn("moses", lowered)
        self.assertIn("timothy", lowered)

    def test_skips_christian_demonym(self):
        names = find_biblical_character_names("Can Christians drink alcohol like Moses?")
        lowered = {n.lower() for n in names}
        self.assertNotIn("christians", lowered)
        self.assertIn("moses", lowered)

    def test_no_biblical_names_when_absent(self):
        self.assertEqual(find_biblical_character_names("How should pastors prepare a sermon?"), [])

    def test_prompt_requires_sermon_notes_and_long_paragraphs(self):
        prompt = build_chat_system_prompt(biblical_names=["Moses"])
        self.assertIn("Susan Nordin", prompt)
        self.assertIn("multiple long paragraphs", prompt)
        self.assertIn("sermon notes", prompt)
        self.assertIn("Quality and pastoral depth", prompt)
        self.assertIn("REQUIRED QUOTES", prompt)
        self.assertIn("word-for-word quotations", prompt)
        self.assertIn("Never invent, polish, or reconstruct quotes", prompt)
        self.assertIn("Social issues are in scope", prompt)
        self.assertIn("abortion", prompt.lower())
        self.assertIn("Do not say you must redirect", prompt)
        self.assertIn("Moses", biblical_characters_instruction(["Moses"]))
        self.assertIn("No Biblical character names were detected", biblical_characters_instruction([]))


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

    def test_scope_gate_prompt_lists_abortion_and_broad_social_issues(self):
        from .scope_gate import _SCOPE_GATE_SYSTEM

        lowered = _SCOPE_GATE_SYSTEM.lower()
        self.assertIn("abortion", lowered)
        self.assertIn("prefer yes", lowered)
        self.assertIn("do not answer no just because a topic is sensitive", lowered)
        self.assertIn("can christians have abortions?", lowered)

    def test_always_in_scope_for_abortion_and_christians(self):
        self.assertTrue(always_in_scope_query("Can Christians have abortions?"))
        self.assertTrue(always_in_scope_query("What about abortion?"))
        self.assertTrue(always_in_scope_query("Tell me about marriage and divorce"))
        self.assertFalse(always_in_scope_query("Write a Python sort function"))
        self.assertFalse(always_in_scope_query("Who won the game last night?"))


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

    def test_names_not_redacted(self):
        out = redact_user_query("Please pray for Jennifer Wilkins during surgery")
        self.assertIn("Jennifer", out)
        self.assertIn("Wilkins", out)
        self.assertNotIn(REDACTED, out)

    def test_can_christians_question_kept(self):
        raw = "Can Christians drink alcohol?"
        stored = redact_user_query(raw)
        self.assertEqual(stored, raw)
        self.assertEqual(query_text_for_llm(stored), raw)

    def test_biblical_names_kept(self):
        out = redact_user_query("Paul and Timothy wrote about Mary Magdalene")
        self.assertNotIn(REDACTED, out)
        self.assertIn("Mary", out)

    def test_theology_phrase_kept(self):
        out = redact_user_query("Explain the New Testament view of the Holy Spirit")
        self.assertNotIn(REDACTED, out)

    def test_query_text_for_llm_strips_redacted_markers(self):
        stored = redact_user_query(
            "What do Mary and Joseph do? Email me at user@example.com"
        )
        self.assertIn(REDACTED, stored)
        self.assertIn("Mary", stored)
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


class DocumentCleanupTests(unittest.TestCase):
    def test_removes_page_chrome_boilerplate_and_fixes_hyphens(self):
        raw = (
            "Faith That Moves Mountains\n"
            "Pastor Don\n"
            "Page 1 of 3\n"
            "\x0c"
            "Faith That Moves Mountains\n"
            "All rights reserved.\n"
            "Copyright © 2020 Example Ministry.\n"
            "\n"
            "Today we look at faith that moves moun-\n"
            "tains for the glory of God.\n"
            "\n"
            "- 2 -\n"
            "\x0c"
            "Faith That Moves Mountains\n"
            "Downloaded from the church portal.\n"
            "www.example.org\n"
            "\n"
            "Believe God for the breakthrough.\n"
            "Page 3 of 3\n"
        )
        result = clean_extracted_document(raw, title="Faith That Moves Mountains")
        text = result.text
        self.assertIn("faith that moves mountains", text.lower())
        self.assertIn("Believe God for the breakthrough.", text)
        self.assertNotIn("All rights reserved", text)
        self.assertNotIn("Copyright ©", text)
        self.assertNotIn("Downloaded from", text)
        self.assertNotIn("Page 1 of 3", text)
        self.assertNotIn("moun-\ntains", text)
        self.assertIn("mountains", text.lower())
        self.assertGreater(result.stats.boilerplate_removed, 0)
        self.assertGreaterEqual(result.stats.hyphen_fixes, 1)

    def test_preserves_mid_document_content_and_structure(self):
        raw = (
            "Introduction\n\n"
            "Jesus taught his disciples about prayer.\n\n"
            "Point One\n\n"
            "Ask in faith without doubting.\n"
        )
        result = clean_extracted_document(raw)
        self.assertIn("Jesus taught his disciples about prayer.", result.text)
        self.assertIn("Ask in faith without doubting.", result.text)

    def test_markdown_cleanup_keeps_headings(self):
        raw = (
            "# Visit Us\n\n"
            "- Source URL: https://example.org/visit\n\n"
            "Services begin at 10am.\n\n"
            "Page 2\n\n"
            "All rights reserved.\n\n"
            "## Youth\n\n"
            "Wednesday at 7pm.\n"
        )
        result = clean_markdown_document(raw)
        self.assertIn("# Visit Us", result.text)
        self.assertIn("## Youth", result.text)
        self.assertIn("Services begin at 10am.", result.text)
        self.assertNotIn("All rights reserved", result.text)

    def test_format_cleanup_log_includes_counts(self):
        result = clean_extracted_document("Hello world.\n\nAll rights reserved.\n")
        log = format_cleanup_log(result.stats, source_label="demo.pdf")
        self.assertIn("Cleanup (demo.pdf):", log)
        self.assertIn("boilerplate=", log)


class PersistDbTests(unittest.TestCase):
    def test_dump_path_uses_env_override(self):
        import os
        from pathlib import Path

        from .persist_db import dump_path

        previous = os.environ.get("PERSIST_PG_DUMP")
        os.environ["PERSIST_PG_DUMP"] = "/tmp/custom_ai_db.dump"
        try:
            self.assertEqual(dump_path(), Path("/tmp/custom_ai_db.dump"))
        finally:
            if previous is None:
                os.environ.pop("PERSIST_PG_DUMP", None)
            else:
                os.environ["PERSIST_PG_DUMP"] = previous

    def test_dump_skips_invalid_database_name(self):
        import os

        from .persist_db import dump_persistent_postgres

        previous = os.environ.get("POSTGRES_DB")
        os.environ["POSTGRES_DB"] = "ai_db; drop table"
        try:
            self.assertFalse(dump_persistent_postgres())
        finally:
            if previous is None:
                os.environ.pop("POSTGRES_DB", None)
            else:
                os.environ["POSTGRES_DB"] = previous


class DocxToPdfTests(unittest.TestCase):
    def test_fallback_writes_pdf_when_soffice_missing(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from docx import Document

        from .docx_to_pdf import convert_docx_to_pdf

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notes.docx"
            dest = Path(tmp) / "notes.pdf"
            doc = Document()
            doc.add_paragraph("The Lord is my shepherd.")
            doc.save(src)
            previous = os.environ.get("SOFFICE_PATH")
            os.environ["SOFFICE_PATH"] = "soffice-not-installed"
            try:
                with patch("core.docx_to_pdf.shutil.which", return_value=None):
                    method = convert_docx_to_pdf(src, dest)
            finally:
                if previous is None:
                    os.environ.pop("SOFFICE_PATH", None)
                else:
                    os.environ["SOFFICE_PATH"] = previous
            self.assertEqual(method, "fpdf")
            self.assertTrue(dest.is_file())
            self.assertGreater(dest.stat().st_size, 100)
            self.assertIn(b"%PDF", dest.read_bytes()[:8])


class StoragePathTests(unittest.TestCase):
    def test_ingestion_dir_uses_env_override(self):
        import os
        import tempfile
        from pathlib import Path

        from .storage_paths import admin_ingestion_dir, admin_video_ingestion_dir

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("INGESTION_UPLOAD_DIR")
            previous_video = os.environ.get("VIDEO_INGESTION_UPLOAD_DIR")
            os.environ["INGESTION_UPLOAD_DIR"] = tmp
            video_tmp = str(Path(tmp) / "videos")
            os.environ["VIDEO_INGESTION_UPLOAD_DIR"] = video_tmp
            try:
                path = admin_ingestion_dir()
                self.assertEqual(path, Path(tmp).resolve())
                self.assertTrue(path.is_dir())
                video_path = admin_video_ingestion_dir()
                self.assertEqual(video_path, Path(video_tmp).resolve())
                self.assertTrue(video_path.is_dir())
            finally:
                if previous is None:
                    os.environ.pop("INGESTION_UPLOAD_DIR", None)
                else:
                    os.environ["INGESTION_UPLOAD_DIR"] = previous
                if previous_video is None:
                    os.environ.pop("VIDEO_INGESTION_UPLOAD_DIR", None)
                else:
                    os.environ["VIDEO_INGESTION_UPLOAD_DIR"] = previous_video


if __name__ == "__main__":
    unittest.main()
