import unittest
from types import SimpleNamespace

from core.chat_retrieval import (
    is_bible_source,
    pin_docs_to_strong_title_matches,
    select_diverse_docs,
)
from core.rerank import (
    RERANK_CANDIDATES,
    _select_candidates,
    rerank_enabled,
    rerank_scored_hits,
)


def _doc(text, *, source, file_hash=None, title=None):
    return SimpleNamespace(
        page_content=text,
        metadata={
            "source": source,
            "file_hash": file_hash or source,
            "title": title or source,
        },
    )


class RerankTests(unittest.TestCase):
    def test_candidates_default_is_forty(self):
        self.assertEqual(RERANK_CANDIDATES, 40)

    def test_disabled_is_noop(self):
        intro = _doc("Welcome to tonight's gathering.", source="sippin.pdf", title="Sippin Saints")
        thesis = _doc(
            "Total abstinence from alcoholic beverages is the only acceptable lifestyle.",
            source="sippin.pdf",
            title="Sippin Saints",
        )
        hits = [(intro, 1.0), (thesis, 0.71)]
        out = rerank_scored_hits(
            "Can Christians drink?",
            hits,
            pinned_docs=[intro, thesis],
            predict=lambda pairs: [9.0, -9.0],
            enabled=False,
        )
        self.assertEqual([doc.page_content for doc, _ in out], [intro.page_content, thesis.page_content])

    def test_catalog_intro_loses_to_thesis_window(self):
        intro = _doc(
            "Welcome notes and opening announcements for this series.",
            source="sippin.pdf",
            title="Sippin Saints",
        )
        thesis = _doc(
            "Christian Temple and this Pastor teach that total abstinence from alcoholic "
            "beverages is the only acceptable lifestyle for Christians. Alcoholism is a sin, "
            "not a sickness or disease.",
            source="sippin.pdf",
            title="Sippin Saints",
        )
        hits = [(intro, 1.0), (thesis, 0.62)]

        def predict(pairs):
            scores = []
            for _query, passage in pairs:
                scores.append(8.0 if "total abstinence" in passage.lower() else -4.0)
            return scores

        out = rerank_scored_hits(
            "Can Christians drink?",
            hits,
            pinned_docs=[intro, thesis],
            predict=predict,
            enabled=True,
        )
        self.assertEqual(out[0][0].page_content, thesis.page_content)
        self.assertGreater(out[0][1], 0.9)
        self.assertLess(out[1][1], 0.2)

    def test_forced_catalog_windows_are_kept_even_when_ann_rank_is_low(self):
        extras = [
            _doc(f"Generic faith remark number {index} about believing.", source=f"ann-{index}.pdf")
            for index in range(50)
        ]
        catalog = _doc(
            "Faith is the evidence of things we cannot yet see.",
            source="nerve.pdf",
            title="It Is Time to Get Our Nerve Back",
        )
        hits = [(doc, 0.99 - (index * 0.001)) for index, doc in enumerate(extras)]
        hits.append((catalog, 0.11))
        chosen = _select_candidates(hits, pinned_docs=[catalog], limit=40)
        texts = [chunk.page_content for chunk, _ in chosen]
        self.assertIn(catalog.page_content, texts)
        self.assertEqual(len(chosen), 40)

    def test_forced_catalog_can_exceed_forty(self):
        catalog = [
            _doc(f"Catalog window {index} with a teaching sentence.", source="major.pdf")
            for index in range(48)
        ]
        hits = [(doc, 1.0) for doc in catalog]
        chosen = _select_candidates(hits, pinned_docs=catalog, limit=40)
        self.assertEqual(len(chosen), 48)

    def test_predict_failure_keeps_original_hits(self):
        intro = _doc("Opening slide.", source="a.pdf")
        thesis = _doc("We must love the homosexual but stand against the lifestyle.", source="a.pdf")
        hits = [(intro, 1.0), (thesis, 0.7)]

        def boom(_pairs):
            raise RuntimeError("offline")

        out = rerank_scored_hits("Can gay people be Christians?", hits, predict=boom, enabled=True)
        self.assertEqual(out, hits)

    def test_empty_query_is_noop(self):
        doc = _doc("Notes.", source="a.pdf")
        hits = [(doc, 0.8)]
        self.assertEqual(rerank_scored_hits("  ", hits, predict=lambda pairs: [9.0], enabled=True), hits)

    def test_sigmoid_scores_stay_between_zero_and_one(self):
        doc = _doc("Notes about thanksgiving and gratitude every day.", source="grat.pdf")
        out = rerank_scored_hits(
            "gratitude",
            [(doc, 1.0)],
            predict=lambda pairs: [12.0],
            enabled=True,
        )
        self.assertEqual(len(out), 1)
        self.assertGreater(out[0][1], 0.99)
        self.assertLessEqual(out[0][1], 1.0)

    def test_title_lock_still_pins_boundaries_after_rerank(self):
        vice = _doc(
            "lifestyle open themselves up to twenty three additional sinful practices: "
            "unrighteousness, sexual immorality, wickedness, covetousness, maliciousness.",
            source="CHRISTIAN BOUNDARIES.pdf",
            title="Christian Boundaries",
        )
        application = _doc(
            "We must love the homosexual but we are to stand firmly against the lifestyle "
            "which they have chosen to embrace. This is not an acceptable lifestyle "
            "according to natural law and the law of God.",
            source="CHRISTIAN BOUNDARIES.pdf",
            title="Christian Boundaries",
        )
        query = "Can gay people be Christians?"
        ranked = rerank_scored_hits(
            query,
            [(vice, 1.0), (application, 0.71)],
            pinned_docs=[vice, application],
            predict=lambda pairs: [
                8.0 if "stand firmly" in passage.lower() else -3.0 for _q, passage in pairs
            ],
            enabled=True,
        )
        pinned = pin_docs_to_strong_title_matches(
            [item[0] for item in ranked[:2]],
            query,
            candidate_hits=ranked,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
        )
        texts = [doc.page_content.lower() for doc in pinned]
        self.assertTrue(any("stand firmly" in text for text in texts), texts)
        selected = select_diverse_docs(
            ranked,
            k=4,
            bible_ratio=0.3,
            max_per_source=2,
            is_bible=lambda doc: is_bible_source(doc.metadata["source"]),
            source_key=lambda doc: doc.metadata["source"],
            query=query,
            pin_query=query,
        )
        selected_text = " ".join(doc.page_content.lower() for doc in selected)
        self.assertIn("stand firmly", selected_text)

    def test_rerank_enabled_env(self):
        self.assertTrue(rerank_enabled({"RERANK_ENABLED": "1"}))
        self.assertFalse(rerank_enabled({"RERANK_ENABLED": "0"}))
        self.assertTrue(rerank_enabled({}))


if __name__ == "__main__":
    unittest.main()
