from django.test import SimpleTestCase

from core.document_titles import normalize_title_key, prettify_title


class DocumentTitlesTests(SimpleTestCase):
    def test_prettify_all_caps_with_teaching_notes_and_copy_number(self):
        self.assertEqual(
            prettify_title("PREGNANT WITH A PROMISE 1 - TEACHING NOTES.pdf"),
            "Pregnant with a Promise",
        )

    def test_prettify_underscores_and_sermon_notes(self):
        self.assertEqual(
            prettify_title("Faith_That_Moves_Mountains_Sermon_Notes.docx"),
            "Faith That Moves Mountains",
        )

    def test_normalize_title_key_matches_name_variants(self):
        a = normalize_title_key("Pregnant With A Promise.pdf")
        b = normalize_title_key("PREGNANT WITH A PROMISE 1.pdf")
        self.assertEqual(a, b)
        self.assertEqual(a, "pregnantwithapromise")

    def test_prettify_copy_suffix_variants(self):
        self.assertEqual(prettify_title("Hope Rising (1).pdf"), "Hope Rising")
        self.assertEqual(prettify_title("Hope Rising - Copy.pdf"), "Hope Rising")
