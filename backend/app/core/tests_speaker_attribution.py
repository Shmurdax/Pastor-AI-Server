import unittest

from core.speaker_attribution import (
    annotate_scripture_in_sermon,
    is_pastor_own_voice,
    looks_like_divine_speech,
    pastor_attributed_quotes,
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
        remaining = pastor_attributed_quotes(fixed)
        for span, leadin in remaining:
            self.assertFalse(
                looks_like_divine_speech(span),
                f"still wrapped as pastor: {leadin!r} {span!r}",
            )
            self.assertNotIn("destroy the works of the devil", span.lower())

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

    def test_annotates_god_speech_in_sermon_notes(self):
        notes = annotate_scripture_in_sermon(
            "Stay faithful in your calling. Before you were born, I sanctified you "
            "and appointed you as My spokesman to the world."
        )
        self.assertIn("not Pastor Don", notes)
        self.assertIn("Before you were born, I sanctified you", notes)


if __name__ == "__main__":
    unittest.main()
