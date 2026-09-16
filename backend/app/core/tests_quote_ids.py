import unittest

from core.quote_ids import (
    QuoteIdStreamer,
    build_quote_catalog,
    expand_quote_ids,
    finalize_quote_ids,
    flushable_expanded,
    format_quote_id_block,
    looks_like_quote_request,
    quote_request_fill,
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

    def test_detects_quote_requests(self):
        self.assertTrue(looks_like_quote_request(
            "Can you give me quotes from Pastor Don for week one?"
        ))
        self.assertTrue(looks_like_quote_request(
            "Back up each point with Pastor Don quotes."
        ))
        self.assertFalse(looks_like_quote_request("Hello how are you today?"))
        self.assertFalse(looks_like_quote_request("What is communion?"))

    def test_holds_quote_from_pastor_don_and_never_paints_a_fake(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        expanded, held = flushable_expanded('Week 1.\nQuote from Pastor Don: "Honesty is', catalog)
        self.assertEqual(expanded, "Week 1.\n")
        self.assertTrue(held.startswith("Quote from Pastor Don:"))

        streamer = QuoteIdStreamer(catalog)
        events = []
        for token in [
            "Week 1.\n",
            "Quote from Pastor Don: ",
            '"Honesty is the glue that holds a marriage together."',
            " Stay close.",
        ]:
            events.extend(streamer.ingest(token))
        painted = "".join(event["text"] for event in events if event["type"] == "delta")
        self.assertNotIn("Honesty is the glue", painted)
        self.assertNotIn("dog heaven", painted)
        self.assertFalse(any(event["type"] == "replace" for event in events), events)
        final, finish_events = streamer.finish()
        self.assertFalse(any(event["type"] == "replace" for event in finish_events), finish_events)
        self.assertNotIn("Honesty is the glue", final)
        self.assertIn("Stay close.", final)

    def test_quote_request_fill_appends_ids_as_deltas(self):
        catalog = build_quote_catalog(["Comfort the child and stay in the kitchen with them."])
        fill = quote_request_fill(
            "Week 1 is about covenant.",
            catalog,
            quote_request=True,
        )
        self.assertIn("{{Q1}}", fill)
        streamer = QuoteIdStreamer(catalog)
        events = list(streamer.ingest("Week 1 is about covenant."))
        events.extend(streamer.ingest(fill))
        self.assertFalse(any(event["type"] == "replace" for event in events), events)
        painted = "".join(event["text"] for event in events if event["type"] == "delta")
        self.assertIn("Week 1 is about covenant.", painted)
        self.assertIn("Comfort the child", painted)
        self.assertNotIn("{{Q1}}", painted)
        already_quoted = quote_request_fill(
            "Pastor Don Nordin teaches, {{Q1}}",
            catalog,
            quote_request=True,
        )
        self.assertEqual(already_quoted, "")
        empty = quote_request_fill("Week 1.", {}, quote_request=True)
        self.assertIn("don't have a retrieved", empty)

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
