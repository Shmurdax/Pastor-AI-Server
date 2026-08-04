from django.test import SimpleTestCase

from core.sermon_pdf import _source_candidates, build_sermon_pdf_bytes


class SermonPdfHelpersTests(SimpleTestCase):
    def test_source_candidates_prefer_markdown(self):
        candidates = _source_candidates("WHAT HE LEFT BEHIND")
        self.assertEqual(candidates[0], "WHAT HE LEFT BEHIND.md")
        self.assertIn("WHAT HE LEFT BEHIND.pdf", candidates)

    def test_build_pdf_bytes(self):
        data = build_sermon_pdf_bytes("Title", "Body text", truncated=True)
        self.assertTrue(data.startswith(b"%PDF"))
