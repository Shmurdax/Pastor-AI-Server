import unittest

from core.quote_chunking import extract_quote_spans, split_sermon_quote_chunks, spoken_text_without_timestamps


class QuoteChunkingTests(unittest.TestCase):
    def test_extracts_quoted_speech_and_sentences(self):
        text = (
            'Pastor Don Nordin teaches, "We love the sinner but we will not bless the sin." '
            "Then he told the church to stay near brokenhearted people and pray with them in the kitchen. "
            "God is faithful in every season of grief and loss."
        )
        spans = extract_quote_spans(text)
        self.assertTrue(any("love the sinner" in item.lower() for item in spans), spans)
        chunks, metas = split_sermon_quote_chunks(text, target_size=400, overlap=40)
        self.assertTrue(chunks)
        self.assertEqual(metas[0]["chunk_kind"], "sermon_quote")
        self.assertTrue(metas[0]["quote_text"])

    def test_windows_stay_quote_sized(self):
        paragraphs = [
            f"Pastoral sentence number {index} about comfort, children, and the heart of God in sorrow."
            for index in range(12)
        ]
        chunks, metas = split_sermon_quote_chunks("\n\n".join(paragraphs), target_size=500, overlap=60)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(meta["chunk_kind"] == "sermon_quote" for meta in metas))
        self.assertTrue(all(len(chunk) < 900 for chunk in chunks))

    def test_strips_video_timestamps_for_quote_text(self):
        text = "[08:50–09:12] I tell parents to sit with their child and weep together."
        self.assertEqual(
            spoken_text_without_timestamps(text),
            "I tell parents to sit with their child and weep together.",
        )


if __name__ == "__main__":
    unittest.main()
