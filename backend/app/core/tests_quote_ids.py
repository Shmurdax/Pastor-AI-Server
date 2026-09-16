import unittest

from core.quote_ids import (
    QuoteIdStreamer,
    build_quote_catalog,
    expand_quote_ids,
    finalize_quote_ids,
    flushable_expanded,
    format_quote_id_block,
)


class QuoteIdTests(unittest.TestCase):
    def test_expands_sermon_and_nkjv_ids(self):
        catalog = build_quote_catalog(
            ["Comfort the child and stay in the kitchen with them."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        text = expand_quote_ids(
            "Pastor Don Nordin teaches, {{Q1}} As David writes, {{V1}}",
            catalog,
        )
        self.assertIn('"Comfort the child and stay in the kitchen with them."', text)
        self.assertIn("Psalm 34:18 (NKJV)", text)
        self.assertIn("broken heart", text)
        self.assertNotIn("{{Q1}}", text)
        self.assertNotIn("{{V1}}", text)

    def test_unknown_id_is_dropped(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        text = expand_quote_ids("He said {{Q9}} and then {{Q1}}", catalog)
        self.assertNotIn("{{Q9}}", text)
        self.assertIn("Comfort the child", text)

    def test_holds_incomplete_slot_during_stream(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        expanded, held = flushable_expanded("Pastor Don teaches, {{Q", catalog)
        self.assertEqual(expanded, "Pastor Don teaches, ")
        self.assertEqual(held, "{{Q")

        streamer = QuoteIdStreamer(catalog)
        events = []
        for token in ["Pastor Don teaches, ", "{{", "Q1", "}}", " today."]:
            events.extend(streamer.ingest(token))
        painted = "".join(event["text"] for event in events if event["type"] == "delta")
        self.assertIn("Comfort the child and stay in the kitchen with them.", painted)
        self.assertNotIn("{{Q1}}", painted)
        final, _ = streamer.finish()
        self.assertTrue(final.endswith(" today."))

    def test_strips_freehand_don_quote(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        text = finalize_quote_ids(
            'Pastor Don teaches, "Your dog is in dog heaven waiting for you." Stay close.',
            catalog,
        )
        self.assertNotIn("dog heaven", text)
        self.assertIn("Stay close.", text)

    def test_keeps_attributed_quote_that_matches_catalog(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        text = finalize_quote_ids(
            'Pastor Don teaches, "Comfort the child and stay in the kitchen with them."',
            catalog,
        )
        self.assertIn("Comfort the child", text)

    def test_block_lists_ids_not_copy_instructions(self):
        catalog = build_quote_catalog(
            ["Comfort the child and stay in the kitchen with them."],
            [("Psalm 34:18", "The Lord is near to those who have a broken heart.")],
        )
        block = format_quote_id_block(catalog)
        self.assertIn("{{Q1}}", block)
        self.assertIn("Q1:", block)
        self.assertIn("V1", block)
        self.assertIn("never retype", block.lower())


if __name__ == "__main__":
    unittest.main()
