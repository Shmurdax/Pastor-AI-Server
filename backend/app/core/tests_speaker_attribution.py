import unittest

from core.speaker_attribution import (
    annotate_scripture_in_sermon,
    is_pastor_own_voice,
    known_verse_ref,
    looks_like_divine_speech,
    looks_like_scripture_wording,
    pastor_attributed_quotes,
    quoted_span_voice,
    rewrite_misattributed_quotes,
)


SCREENSHOT_ANSWER = """
Just as God spoke from the lid of the mercy seat in the Holy of Holies, there is no substitute
for you entering His presence to hear His plan for your life. This means setting aside time
to listen to God's voice and discern His purposes for you. According to Jeremiah 1:4-5, God knew
Jeremiah before he was formed in the womb and appointed him as His spokesman. Similarly, God has
an eternal plan for your life, and He desires to reveal it to you. By seeking Him earnestly, you
can discover your unique role and purpose in His kingdom. Pastor Don Nordin teaches,
"Destroyed the works of the devil." Pastor Don and Susan Nordin also teach, "He destroyed the devil."

We must assist you in realizing that God has an eternal plan for your life.

Similarly, God has a unique purpose and plan for your life.

Pastor Don Nordin teaches, "There can be only one logical explanation for the precision of these relationships."

Some agency saw the life-bearing potential of the Earth/Sun system and added the Moon to create and nurture life.

Additionally, he emphasizes, "Before you were born, I sanctified you and appointed you as My spokesman to the world."

These statements highlight God's intentional design and purpose for each individual.

The NKJV scripture supports this idea: "The Lord said to me, 'I knew you before you were formed within your mother's womb'" (Jeremiah 1:5).
"""


class SpeakerAttributionTests(unittest.TestCase):
    def test_detects_jeremiah_commissioning_speech(self):
        span = "Before you were born, I sanctified you and appointed you as My spokesman to the world."
        self.assertTrue(looks_like_divine_speech(span))
        self.assertFalse(is_pastor_own_voice(span))

    def test_keeps_pastor_don_first_person(self):
        span = "I tell parents to sit with their child and weep together in the kitchen."
        self.assertFalse(looks_like_divine_speech(span))
        self.assertTrue(is_pastor_own_voice(span))

    def test_rewrites_screenshot_misattribution(self):
        bible = (
            "Before I formed you in the womb I knew you; Before you were born I sanctified you; "
            "I ordained you a prophet to the nations. He who sins is of the devil, for the devil "
            "has sinned from the beginning. For this purpose the Son of God was manifested, that "
            "He might destroy the works of the devil."
        )
        nkjv = [
            (
                "Jeremiah 1:5",
                "Before I formed you in the womb I knew you; Before you were born I sanctified you; "
                "I ordained you a prophet to the nations.",
            ),
            (
                "1 John 3:8",
                "He who sins is of the devil, for the devil has sinned from the beginning. "
                "For this purpose the Son of God was manifested, that He might destroy the works of the devil.",
            ),
        ]
        fixed = rewrite_misattributed_quotes(
            SCREENSHOT_ANSWER,
            bible_corpus=bible,
            nkjv_pairs=nkjv,
        )
        self.assertNotIn("he emphasizes", fixed.lower())
        self.assertNotRegex(
            fixed,
            r'(?i)pastor don[^\n"]{0,80}"Before you were born',
        )
        self.assertNotRegex(
            fixed,
            r'(?i)pastor don[^\n"]{0,80}"Destroyed the works of the devil',
        )
        self.assertIn("logical explanation", fixed)
        self.assertIn("Pastor Don Nordin teaches", fixed)
        self.assertIn("Jeremiah 1:5", fixed)
        self.assertIn("Lord", fixed)
        self.assertIn("1 John 3:8", fixed)
        remaining = pastor_attributed_quotes(fixed)
        for span, leadin in remaining:
            folded = span.lower()
            self.assertFalse(
                looks_like_divine_speech(span),
                f"still wrapped as pastor: {leadin!r} {span!r}",
            )
            self.assertNotIn("works of the devil", folded)
            self.assertNotIn("sanctified you", folded)

    def test_rewrites_unclosed_pastor_god_speech(self):
        text = (
            "We must assist you in realizing that God has an eternal plan for your life.\n\n"
            'Pastor Don Nordin teaches, "Destroyed the works of the devil."\n'
            'Pastor Don Nordin teaches, "Before you were born, I sanctified you '
            "and appointed you as My spokesman to the world.\n"
            "These statements highlight God's intentional design."
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotRegex(
            fixed,
            r'(?i)pastor don[^\n"]{0,80}"Before you were born',
        )
        self.assertNotRegex(
            fixed,
            r'(?i)pastor don[^\n"]{0,80}"Destroyed the works',
        )
        self.assertIn("Jeremiah 1:5", fixed)
        self.assertIn("1 John 3:8", fixed)
        self.assertIn("Lord", fixed)
        remaining = pastor_attributed_quotes(fixed)
        for span, leadin in remaining:
            self.assertFalse(
                looks_like_divine_speech(span),
                f"still wrapped as pastor: {leadin!r} {span!r}",
            )

    def test_money_illustration_is_not_scripture(self):
        span = (
            "Suppose after one month I check back with her and discover the first guy "
            "has been giving her $2,000.00 each week, the second guy is giving her "
            "$1,000.00 per week, but the third guy gave her $800.00 the first week."
        )
        self.assertFalse(looks_like_scripture_wording(span))
        self.assertTrue(is_pastor_own_voice(span))
        fixed = rewrite_misattributed_quotes(
            f'Pastor Don Nordin teaches, "{span}"'
        )
        self.assertIn("Pastor Don", fixed)

    def test_destroyed_works_matches_1_john(self):
        span = "Destroyed the works of the devil."
        self.assertTrue(looks_like_scripture_wording(span))
        self.assertEqual(known_verse_ref(span), "1 John 3:8")

    def test_finds_unclosed_pastor_quotes(self):
        text = (
            'Pastor Don Nordin teaches, "Before you were born, I sanctified you '
            "and appointed you as My spokesman to the world.\n"
        )
        pairs = pastor_attributed_quotes(text)
        self.assertTrue(pairs, pairs)
        self.assertIn("sanctified you", pairs[0][0].lower())
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotIn("Pastor Don", fixed)
        self.assertIn("Jeremiah 1:5", fixed)

    def test_rewrites_jesus_and_prophet_quotes_wrapped_as_pastor(self):
        samples = {
            'Pastor Don teaches, "If you can believe, all things are possible to him who believes."':
                "Mark 9:23",
            'Pastor Don Nordin teaches, "Gather together and come; assemble, you fugitives from the nations."':
                "Isaiah 45:20",
            'Pastor Don and Susan Nordin also teach, "I am crucified with Christ: nevertheless I live."':
                "Galatians 2:20",
            'Pastor Don teaches, "It is written, My house is a house of prayer, but you have made it a den of thieves."':
                "Luke 19:46",
            'Pastor Don Nordin teaches, "For God did not send His Son into the world to condemn the world, but that the world through Him might be saved."':
                "John 3:17",
            'Pastor Don teaches, "The righteous shall flourish like the palm tree: he shall grow like a cedar in Lebanon. 13Those that be planted in the house of the Lord."':
                "Psalm 92:12",
            'Pastor Don teaches, "By faith we understand that the entire universe was formed at God’s command, that what we now see did not come from anything that can be seen."':
                "Hebrews 11:3",
            'Pastor Don Nordin teaches, "Here mortal men receive tithes, but there he receives them, of whom it is witnessed that he lives."':
                "Hebrews 7:8",
            'Pastor Don and Susan Nordin also teach, "Now concerning the collection for the saints, as I have given order to the churches of Galatia, even so do ye. 2 Upon the first day of the week let every one of you lay by him in store."':
                "1 Corinthians 16:1",
            'Pastor Don and Susan Nordin also teach, "Don’t even be angry with your brother."':
                "Matthew 5:22",
            'Pastor Don and Susan Nordin also teach, "If you look at a woman with lust in your heart you have already committed adultery."':
                "Matthew 5:28",
            'Pastor Don Nordin teaches, "Recall the former days in which, after you were illuminated, you endured a great struggle with sufferings."':
                "Hebrews 10:32",
            'Pastor Don Nordin teaches, "And he said to me, O Daniel, man greatly beloved, understand the words that I speak to you and stand upright, for I have now been sent to you."':
                "Daniel 10:11",
            'Pastor Don and Susan Nordin also teach, "Then he said to me, Do not fear, Daniel, for from the first day that you set your heart to understand and to humble yourself before your God, your words were heard."':
                "Daniel 10:12",
            'Additionally, he emphasizes, "If My people who are called by My name will humble themselves, and pray and seek My face, and turn from their wicked ways, then I will hear from heaven."':
                "2 Chronicles 7:14",
            'Pastor Don and Susan Nordin also teach, "You will do greater things because I will go to My Father and He will send Holy Spirit to abide in you."':
                "John 14:12",
            'Pastor Don Nordin teaches, "Having then gifts differing according to the grace that is given to us, let us use them: if prophecy, let us prophesy in proportion to our faith; 7 or ministry, let us use it in our ministering;"':
                "Romans 12:6",
            'Pastor Don Nordin teaches, "Let us hear the conclusion of the whole matter, fear God and keep His commandments for this is the whole duty of man."':
                "Ecclesiastes 12:13",
        }
        for raw, ref in samples.items():
            fixed = rewrite_misattributed_quotes(raw)
            self.assertNotIn("Pastor Don", fixed, raw)
            self.assertNotIn("also teach", fixed.lower(), raw)
            self.assertIn(ref, fixed)
            remaining = pastor_attributed_quotes(fixed)
            self.assertFalse(remaining, remaining)

    def test_matches_also_teach_leadin(self):
        text = (
            'You don’t have any trouble. All you need is faith in God. '
            'Pastor Don and Susan Nordin also teach, "I am crucified with Christ."'
        )
        pairs = pastor_attributed_quotes(text)
        self.assertTrue(pairs, pairs)
        self.assertIn("crucified", pairs[0][0].lower())

    def test_does_not_rewrite_already_cited_scripture(self):
        text = (
            'Jeremiah 1:5 (NKJV) says, "Before I formed you in the womb I knew you." '
            'Pastor Don Nordin teaches, "God has an eternal plan for your life."'
        )
        fixed = rewrite_misattributed_quotes(
            text,
            bible_corpus="Before I formed you in the womb I knew you",
            nkjv_pairs=[("Jeremiah 1:5", "Before I formed you in the womb I knew you.")],
        )
        self.assertEqual(fixed, text)

    def test_drops_dictionary_and_title_wraps(self):
        text = (
            'Pastor Don teaches, "We cannot talk about giving without talking about stewardship." '
            'Pastor Don Nordin teaches, "An instrument used for moving the bolt of a lock thus locking or unlocking something." '
            'Pastor Don and Susan Nordin also teach, "Who Built the Moon." '
            'Pastor Don and Susan Nordin also teach, "king of peace." '
            'Pastor Don Nordin teaches, "Some of the problem is that He is a person without a body because: □ We are made in the image of God." '
            'Pastor Don teaches, "wed money in my name for people who could not get a loan."'
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertIn("stewardship", fixed)
        self.assertNotIn("instrument used for moving the bolt", fixed.lower())
        self.assertNotIn("Who Built the Moon", fixed)
        self.assertNotIn("Pastor Don and Susan Nordin also teach, \"king of peace", fixed)
        self.assertIn("Hebrews 7:2", fixed)
        self.assertNotIn("□", fixed)
        self.assertNotIn("wed money", fixed.lower())

    def test_title_excerpt_is_not_pastor_voice(self):
        self.assertFalse(is_pastor_own_voice("Who Built the Moon."))
        self.assertFalse(
            is_pastor_own_voice(
                "An instrument used for moving the bolt of a lock thus locking or unlocking something."
            )
        )
        self.assertTrue(
            is_pastor_own_voice(
                "We cannot talk about giving without talking about stewardship."
            )
        )
        self.assertFalse(
            is_pastor_own_voice(
                "You will do greater things because I will go to My Father and He will send Holy Spirit to abide in you."
            )
        )
        self.assertFalse(
            is_pastor_own_voice(
                "wed money in my name for people who could not get a loan."
            )
        )

    def test_annotates_god_speech_in_sermon_notes(self):
        notes = annotate_scripture_in_sermon(
            "Stay faithful in your calling. Before you were born, I sanctified you "
            "and appointed you as My spokesman to the world."
        )
        self.assertIn("not Pastor Don", notes)
        self.assertIn("Before you were born, I sanctified you", notes)

    def test_rewrites_unquoted_hebrews_paraphrase_as_scripture(self):
        text = (
            "Pastor Don teaches that faith is the confident assurance that what we hope "
            "for is going to happen. It is the evidence of things we cannot yet see. "
            "For instance, Noah took God at His word."
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotRegex(fixed, r'(?i)pastor don teaches that faith is the confident')
        self.assertIn("Hebrews 11:1", fixed)
        self.assertIn("Noah took God at His word", fixed)

    def test_holy_spirit_screenshot_does_not_keep_jesus_as_nordin_teaching(self):
        text = (
            "Pastor Don teaches about the Holy Spirit, emphasizing that He is a person "
            "who should be closely embraced by every believer. He clarifies that the term "
            '"Holy Ghost" can sometimes be intimidating or mysterious, but the Holy Spirit '
            "is nothing to fear. Pastor Don Nordin teaches, \"Some of the problem is that "
            "He is a person without a body and that seems odd to us because: □ We are made "
            "in the image of God, therefore we know He has a body... □ Jesus dawned an earth "
            "suit and became Immanuel, God with us... But Holy Spirit?\" Pastor Don and "
            "Susan Nordin also teach, \"You will do greater things because I will go to My "
            "Father and He will send Holy Spirit to abide in you.\"\n\n"
            "Pastor Don also highlights the oil-in-an-engine illustration."
        )
        before = pastor_attributed_quotes(text)
        self.assertTrue(
            any("greater things" in span.lower() for span, _lead in before),
            before,
        )
        greater = next(span for span, _lead in before if "greater things" in span.lower())
        idx = text.lower().index("you will do greater things")
        prefix = text[: idx - 1]
        self.assertEqual(quoted_span_voice(prefix), "pastor")
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotIn("also teach", fixed.lower())
        self.assertNotIn("□", fixed)
        self.assertIn("John 14", fixed)
        self.assertRegex(
            fixed,
            r"(?i)(records the lord saying|jesus said).{0,8}You will do greater things",
        )
        self.assertIn("oil-in-an-engine", fixed)
        self.assertNotRegex(fixed, r'(?i)pastor don and susan.{0,40}greater things')

    def test_splits_pastor_prose_from_jesus_clause_in_same_quote(self):
        text = (
            'Pastor Don Nordin teaches, "It isn\'t until after His Baptism that Jesus '
            "began to perform miracles. You will do greater things because I will go to "
            'My Father and He will send Holy Spirit to abide in you."'
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertIn("Baptism", fixed)
        self.assertIn("Pastor Don", fixed)
        self.assertIn("John 14", fixed)
        self.assertRegex(
            fixed,
            r'(?i)pastor don.{0,40}teaches, "It isn\'t until after His Baptism',
        )
        self.assertNotRegex(
            fixed,
            r"(?i)records the lord saying, \"It isn't until after His Baptism",
        )
        remaining = pastor_attributed_quotes(fixed)
        self.assertFalse(
            any("greater things" in span.lower() for span, _lead in remaining),
            remaining,
        )

    def test_splits_jesus_clause_after_newline_inside_he_teaches_quote(self):
        text = (
            "Pastor Don also emphasizes remaining filled with the Holy Spirit.\n\n"
            'He teaches, "It wasn’t until after His Baptism that Jesus began to perform miracles.\n\n'
            "‘You will do greater things because I will go to My Father and He will send "
            'Holy Spirit to abide in you.’"'
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertIn("John 14", fixed)
        self.assertNotRegex(
            fixed,
            r"(?i)he teaches, \".{0,80}You will do greater things",
        )
        self.assertRegex(
            fixed,
            r"(?i)records the lord saying,.{0,8}You will do greater things",
        )
        remaining = pastor_attributed_quotes(fixed)
        self.assertFalse(
            any("greater things" in span.lower() for span, _lead in remaining),
            remaining,
        )

    def test_genesis_marriage_verse_is_not_pastor_don(self):
        text = (
            'Pastor Don Nordin teaches, "For this reason a man shall leave his father '
            'and mother and be joined to his wife, and the two shall become one flesh."'
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotRegex(fixed, r'(?i)pastor don.{0,40}"For this reason a man shall leave')
        self.assertIn("Genesis 2:24", fixed)

    def test_proverbs_soft_answer_is_not_pastor_don(self):
        text = (
            'Pastor Don and Susan Nordin also teach, "A gentle answer turns away wrath, '
            'but a harsh word stirs up anger."'
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotRegex(fixed, r'(?i)pastor don.{0,50}"A gentle answer')
        self.assertIn("Proverbs 15:1", fixed)

    def test_hosea_command_is_not_pastor_don(self):
        text = (
            'Pastor Don Nordin teaches, "Go and marry a prostitute, so some of her '
            "children will be born to you from other men. This will illustrate the way "
            'my people have been untrue to me, openly committing adultery against the LORD."'
        )
        self.assertTrue(
            looks_like_scripture_wording(
                "Go and marry a prostitute, so some of her children will be born to you."
            )
        )
        self.assertFalse(
            is_pastor_own_voice(
                "Go and marry a prostitute, so some of her children will be born to you."
            )
        )
        fixed = rewrite_misattributed_quotes(text)
        self.assertNotRegex(
            fixed,
            r'(?i)pastor don.{0,40}teaches, "Go and marry a prostitute',
        )
        self.assertIn("Hosea 1:2", fixed)
        remaining = pastor_attributed_quotes(fixed)
        self.assertFalse(
            any("prostitute" in span.lower() for span, _lead in remaining),
            remaining,
        )


if __name__ == "__main__":
    unittest.main()
