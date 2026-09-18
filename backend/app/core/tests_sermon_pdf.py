from django.test import SimpleTestCase

from pathlib import Path

from core.sermon_pdf import (
    _source_candidates,
    build_sermon_pdf_bytes,
    write_library_pdf_from_text,
)


class SermonPdfHelpersTests(SimpleTestCase):
    def test_source_candidates_prefer_markdown(self):
        candidates = _source_candidates("WHAT HE LEFT BEHIND")
        self.assertEqual(candidates[0], "WHAT HE LEFT BEHIND.md")
        self.assertIn("WHAT HE LEFT BEHIND.pdf", candidates)

    def test_source_candidates_strip_txt(self):
        candidates = _source_candidates("The Giver and His Gifts.txt")
        self.assertIn("The Giver and His Gifts.pdf", candidates)
        self.assertIn("The Giver and His Gifts.md", candidates)

    def test_build_pdf_bytes(self):
        data = build_sermon_pdf_bytes("Title", "Body text", truncated=True)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"reconstructed from indexed sermon notes", data)

    def test_library_pdf_from_long_text_is_not_truncated(self):
        body = "The Holy Spirit is a gift. " * 8000
        data = build_sermon_pdf_bytes("The Giver and His Gifts", body)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertNotIn(b"truncated", data)
        self.assertGreater(len(data), 20_000)

    def test_write_library_pdf_from_text(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "notes.pdf"
            write_library_pdf_from_text(dest, "Working At God's Altar", "Serve at the altar.")
            self.assertTrue(dest.is_file())
            self.assertTrue(dest.read_bytes().startswith(b"%PDF"))
