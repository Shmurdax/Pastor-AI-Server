import unittest

from core.bible_chunking import parse_nkjv_verses, split_nkjv_document
from core.bible_refs import format_verse_ref, parse_verse_refs


class BibleChunkingTests(unittest.TestCase):
    def test_parses_inline_nkjv_refs(self):
        text = (
            "Genesis 1:1 In the beginning God created the heavens and the earth. "
            "Genesis 1:2 The earth was without form, and void; and darkness was on the face of the deep. "
            "Genesis 1:3 Then God said, Let there be light; and there was light. "
            "Genesis 1:4 And God saw the light, that it was good. "
            "Genesis 1:5 God called the light Day, and the darkness He called Night. "
            "Genesis 1:6 Then God said, Let there be a firmament. "
            "Genesis 1:7 Thus God made the firmament. "
            "Genesis 1:8 And God called the firmament Heaven. "
            "Psalm 34:18 The Lord is near to those who have a broken heart, and saves such as have a contrite spirit."
        )
        verses = parse_nkjv_verses(text)
        refs = {(item.book, item.chapter, item.verse) for item in verses}
        self.assertIn(("genesis", 1, 1), refs)
        self.assertIn(("psalm", 34, 18), refs)
        beginning = next(item for item in verses if item.verse == 1 and item.book == "genesis")
        self.assertIn("In the beginning God created", beginning.text)

    def test_parses_chapter_and_numbered_lines(self):
        text = "\n".join(
            [
                "John",
                "Chapter 1",
                "1 In the beginning was the Word, and the Word was with God, and the Word was God.",
                "2 He was in the beginning with God.",
                "3 All things were made through Him, and without Him nothing was made that was made.",
                "4 In Him was life, and the life was the light of men.",
                "5 And the light shines in the darkness, and the darkness did not comprehend it.",
                "6 There was a man sent from God, whose name was John.",
                "7 This man came for a witness, to bear witness of the Light.",
                "8 He was not that Light, but was sent to bear witness of that Light.",
            ]
        )
        verses = parse_nkjv_verses(text)
        self.assertGreaterEqual(len(verses), 8)
        self.assertEqual(verses[0].book, "john")
        self.assertEqual(verses[0].chapter, 1)
        self.assertTrue(verses[0].text.startswith("In the beginning was the Word"))

    def test_split_sets_verse_payload(self):
        text = "\n".join(
            f"Psalm 23:{n} The Lord is my shepherd verse number {n} with enough words here."
            for n in range(1, 10)
        )
        chunks, metas = split_nkjv_document(text)
        self.assertTrue(chunks)
        self.assertEqual(metas[0]["chunk_kind"], "bible_verse")
        self.assertEqual(metas[0]["book"], "psalm")
        self.assertEqual(metas[0]["chapter"], 23)
        self.assertIn("verse_start", metas[0])
        self.assertTrue(metas[0]["quote_text"])

    def test_parse_verse_refs_from_answer(self):
        refs = parse_verse_refs('As Psalm 34:18 (NKJV) says, "The Lord is near." John 3:16 also.')
        self.assertIn(("psalm", 34, 18), refs)
        self.assertIn(("john", 3, 16), refs)
        self.assertEqual(format_verse_ref("psalm", 34, 18), "Psalm 34:18")


if __name__ == "__main__":
    unittest.main()
