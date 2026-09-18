import unittest

from core.bible_chunking import parse_nkjv_verses, split_nkjv_document
from core.bible_refs import canonical_book_key, format_verse_ref, parse_verse_refs, scripture_refs_from_metadata, scripture_refs_from_text


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

    def test_scripture_refs_from_text_expands_ranges(self):
        refs = scripture_refs_from_text(
            'As John 3:16-17 (NKJV) says, "God so loved." Psalm 23:1 also.'
        )
        self.assertEqual(refs, ["John 3:16", "John 3:17", "Psalm 23:1"])
        self.assertEqual(scripture_refs_from_metadata({"scripture_refs": refs}), refs)

    def test_ordinal_book_names(self):
        self.assertEqual(canonical_book_key("1st Samuel"), "1 samuel")
        self.assertEqual(canonical_book_key("2nd Corinthians"), "2 corinthians")

    def test_parses_word_export_glued_verse_numbers(self):
        text = "\n".join(
            [
                "Genesis",
                "1In the beginning God created the heavens and the earth.",
                "2The earth was without form, and void; and darkness was on the face of the deep.",
                "3Then God said, \"Let there be light\"; and there was light.",
                "4And God saw the light, that it was good; and God divided the light from the darkness.",
                "5God called the light Day, and the darkness He called Night. So the evening and the morning were the first day.",
                "6Then God said, \"Let there be a firmament in the midst of the waters.\"",
                "7Thus God made the firmament, and divided the waters.",
                "8And God called the firmament Heaven. So the evening and the morning were the second day.",
                "9Then God said, \"Let the waters under the heavens be gathered together.\"",
                "10And God called the dry land Earth, and the gathering together of the waters He called Seas.",
                "11Then God said, \"Let the earth bring forth grass.\"",
                "12And the earth brought forth grass.",
                "13So the evening and the morning were the third day.",
                "14Then God said, \"Let there be lights in the firmament of the heavens.\"",
                "15and let them be for lights in the firmament of the heavens to give light on the earth\"; and it was so.",
                "16Then God made two great lights: the greater light to rule the day.",
                "17God set them in the firmament of the heavens to give light on the earth,",
                "18and to rule over the day and over the night, and to divide the light from the darkness. And God saw that it was good.",
                "19So the evening and the morning were the fourth day.",
                "20Then God said, \"Let the waters abound with an abundance of living creatures.\"",
                "21So God created great sea creatures.",
                "22And God blessed them, saying, \"Be fruitful and multiply.\"",
                "23So the evening and the morning were the fifth day.",
                "24Then God said, \"Let the earth bring forth the living creature according to its kind.\"",
                "25And God made the beast of the earth according to its kind.",
                "26Then God said, \"Let Us make man in Our image.\"",
                "27So God created man in His own image; in the image of God He created him.",
                "28Then God blessed them, and God said to them, \"Be fruitful and multiply.\"",
                "29And God said, \"See, I have given you every herb that yields seed.\"",
                "30Also, to every beast of the earth, to every bird of the air, I have given every green herb for food\"; and it was so.",
                "31Then God saw everything that He had made, and indeed it was very good. So the evening and the morning were the sixth day.",
                "2Thus the heavens and the earth, and all the host of them, were finished.",
                "2And on the seventh day God ended His work which He had done, and He rested on the seventh day from all His work which He had done.",
                "3Then God blessed the seventh day and sanctified it.",
            ]
        )
        verses = parse_nkjv_verses(text)
        refs = {(item.book, item.chapter, item.verse) for item in verses}
        self.assertIn(("genesis", 1, 1), refs)
        self.assertIn(("genesis", 1, 31), refs)
        self.assertIn(("genesis", 2, 1), refs)
        self.assertIn(("genesis", 2, 2), refs)
        gen1 = [item for item in verses if item.book == "genesis" and item.chapter == 1]
        self.assertEqual(len(gen1), 31)
        self.assertTrue(
            next(item for item in verses if item.chapter == 2 and item.verse == 1).text.startswith(
                "Thus the heavens"
            )
        )

    def test_word_export_chapter_number_followed_by_verse_two(self):
        lines = ["Genesis", "Chapter 23"]
        lines.extend(
            f"{n}Genesis chapter twenty-three verse {n} has enough words here."
            for n in range(1, 21)
        )
        lines.extend(
            [
                "24Now Abraham was old, well advanced in age; and the LORD had blessed Abraham in all things.",
                "2So Abraham said to the oldest servant of his house, who ruled over all that he had.",
                "3and I will make you swear by the LORD, the God of heaven and the God of the earth.",
            ]
        )
        verses = parse_nkjv_verses("\n".join(lines))
        self.assertEqual(
            {(item.chapter, item.verse) for item in verses if item.book == "genesis" and item.chapter in {23, 24}},
            {(23, n) for n in range(1, 21)} | {(24, 1), (24, 2), (24, 3)},
        )
        self.assertTrue(
            next(item for item in verses if item.chapter == 24 and item.verse == 1).text.startswith(
                "Now Abraham was old"
            )
        )

    def test_parses_psalm_headers_and_glued_verses(self):
        text = "\n".join(
            [
                "PSALM 120",
                "1In my distress I cried to the LORD, And He heard me.",
                "2Deliver my soul, O LORD, from lying lips And from a deceitful tongue.",
                "3What shall be given to you, Or what shall be done to you, You false tongue?",
                "4Sharp arrows of the warrior, With coals of the broom tree!",
                "5Woe is me, that I dwell in Meshech, That I dwell among the tents of Kedar!",
                "6My soul has dwelt too long With one who hates peace.",
                "7I am for peace; But when I speak, they are for war.",
                "PSALM 121",
                "1I will lift up my eyes to the hills -- From whence comes my help?",
                "2My help comes from the LORD, Who made heaven and earth.",
            ]
        )
        verses = parse_nkjv_verses(text)
        self.assertEqual(verses[0].book, "psalm")
        self.assertEqual(verses[0].chapter, 120)
        self.assertEqual(verses[0].verse, 1)
        self.assertIn("distress", verses[0].text)
        psalm121 = [item for item in verses if item.chapter == 121]
        self.assertGreaterEqual(len(psalm121), 2)
        self.assertTrue(psalm121[0].text.startswith("I will lift up my eyes"))

    def test_glued_verse_starting_with_parenthesis(self):
        text = "\n".join(
            [
                "John",
                "Chapter 4",
                "1Therefore, when the Lord knew that the Pharisees had heard that Jesus made and baptized more disciples than John",
                "2(though Jesus Himself did not baptize, but His disciples),",
                "3He left Judea and departed again to Galilee.",
                "4But He needed to go through Samaria.",
                "5So He came to a city of Samaria which is called Sychar.",
            ]
        )
        verses = parse_nkjv_verses(text)
        refs = {(item.chapter, item.verse) for item in verses if item.book == "john"}
        self.assertEqual(refs, {(4, n) for n in range(1, 6)})
        self.assertTrue(verses[1].text.startswith("(though Jesus Himself"))

    def test_weak_parse_does_not_emit_passage_chunks(self):
        chunks, metas = split_nkjv_document("This is not scripture, just a title page and some notes.")
        self.assertEqual(chunks, [])
        self.assertEqual(metas, [])


if __name__ == "__main__":
    unittest.main()
