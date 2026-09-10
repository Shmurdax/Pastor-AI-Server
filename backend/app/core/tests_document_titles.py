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

    def test_prettify_full_caps_does_not_fake_acronyms(self):
        self.assertEqual(prettify_title("A GOOD MAN.pdf"), "A Good Man")
        self.assertEqual(
            prettify_title("AN UPDATE IS AVAILABLE.pdf"),
            "An Update Is Available",
        )

    def test_prettify_allowlisted_acronyms_stay_all_caps(self):
        self.assertEqual(
            prettify_title("USA MISSIONS UPDATE.pdf"),
            "USA Missions Update",
        )
        self.assertEqual(
            prettify_title("FAITH AND THE NKJV.pdf"),
            "Faith and the NKJV",
        )
        self.assertEqual(
            prettify_title("reading the nkjv.pdf"),
            "Reading the NKJV",
        )

    def test_prettify_strips_video_export_junk_keeps_date(self):
        self.assertEqual(prettify_title("June_30_V1_240p.mp4"), "June 30")
        self.assertEqual(prettify_title("April_10_v1_240p.mp4"), "April 10")
        self.assertEqual(
            prettify_title("Sunday Service HD 720p.mp4"),
            "Sunday Service",
        )
        self.assertEqual(prettify_title("Childhood Faith.pdf"), "Childhood Faith")
        self.assertEqual(prettify_title("Sermon 12.pdf"), "Sermon 12")

    def test_prettify_keeps_single_digit_month_days(self):
        self.assertEqual(prettify_title("January_1_V1_240p.mp4"), "January 1")
        self.assertEqual(prettify_title("January 1.mp4"), "January 1")
        self.assertEqual(prettify_title("Jan 9.mp4"), "Jan 9")
        self.assertEqual(prettify_title("May_3_v1_720p.mp4"), "May 3")
        self.assertEqual(prettify_title("March 4.pdf"), "March 4")
        # Non-date trailing copy digit still drops.
        self.assertEqual(prettify_title("Hope Rising 1.pdf"), "Hope Rising")
