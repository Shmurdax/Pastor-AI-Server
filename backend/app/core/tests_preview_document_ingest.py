import tempfile
import unittest
from pathlib import Path

from core.preview_document_ingest import preview_text_upload


class PreviewDocumentIngestTests(unittest.TestCase):
    def test_txt_preview_uses_sermon_splitter_and_indexes_verses(self):
        body = (
            "Know Your Why\nDr. Susan Nordin\n\n"
            "## Introduction\n\n"
            "You arrived here on purpose for a purpose. "
            "John 3:16 shows the Father's love, and Jeremiah 1:5 says He knew you.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Know Your Why - Full Transcript.txt"
            path.write_text(body, encoding="utf-8")
            preview = preview_text_upload(
                path,
                queries=["what is my purpose"],
            )

        self.assertEqual(preview.title, "Know Your Why Full")
        self.assertEqual(preview.library_pdf_name, "Know Your Why - Full Transcript.pdf")
        self.assertFalse(preview.is_bible)
        self.assertEqual(preview.splitter, "sermon_quote")
        self.assertGreaterEqual(preview.chunk_count, 1)
        self.assertIn("John 3:16", preview.scripture_refs)
        self.assertEqual(preview.leftover_junk, [])
        self.assertTrue(any(hit.query == "what is my purpose" for hit in preview.retrieval_hits))

    def test_flags_leftover_about_the_author(self):
        body = "## Day 1\n\nBe determined.\n\n## About the Author\n\nP.O. Box 751055\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "One Determined Mom - Full Transcript.txt"
            path.write_text(body, encoding="utf-8")
            preview = preview_text_upload(path)

        self.assertIn("About the Author", preview.leftover_junk)
        self.assertTrue(preview.warnings)


if __name__ == "__main__":
    unittest.main()
