"""Qdrant ingest upserts must stay under the 32MiB REST JSON cap."""

import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from core.ingestion_service import (
    DEFAULT_QDRANT_UPSERT_BATCH,
    MAX_QDRANT_UPSERT_BATCH,
    _upsert_chunks,
    iter_point_batches,
    qdrant_upsert_batch_size,
)
from core.models import IngestedChunk, IngestedDocument


class QdrantUpsertBatchSizeTests(SimpleTestCase):
    def test_default_stays_well_under_qdrant_json_limit(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INGEST_QDRANT_UPSERT_BATCH", None)
            self.assertEqual(qdrant_upsert_batch_size(), DEFAULT_QDRANT_UPSERT_BATCH)
        # 128 * ~19KB/point ≈ 2.4MB vs Qdrant's 32MiB JSON payload limit.
        self.assertLess(DEFAULT_QDRANT_UPSERT_BATCH * 19_000, 32 * 1024 * 1024)
        self.assertLess(MAX_QDRANT_UPSERT_BATCH * 19_000, 32 * 1024 * 1024)

    def test_invalid_or_too_large_values_are_clamped(self):
        with patch.dict(os.environ, {"INGEST_QDRANT_UPSERT_BATCH": "0"}):
            self.assertEqual(qdrant_upsert_batch_size(), DEFAULT_QDRANT_UPSERT_BATCH)
        with patch.dict(os.environ, {"INGEST_QDRANT_UPSERT_BATCH": "nope"}):
            self.assertEqual(qdrant_upsert_batch_size(), DEFAULT_QDRANT_UPSERT_BATCH)
        with patch.dict(os.environ, {"INGEST_QDRANT_UPSERT_BATCH": "99999"}):
            self.assertEqual(qdrant_upsert_batch_size(), MAX_QDRANT_UPSERT_BATCH)

    def test_iter_point_batches_splits_remainder(self):
        items = list(range(5))
        batches = list(iter_point_batches(items, 2))
        self.assertEqual(batches, [[0, 1], [2, 3], [4]])
        self.assertEqual(list(iter_point_batches([], 2)), [])


class QdrantUpsertChunksTests(TestCase):
    def _document(self, suffix="a"):
        digest = (suffix * 64)[:64]
        return IngestedDocument.objects.create(
            source_name=f"New King James Version-{suffix}.pdf",
            title="New King James Version",
            normalized_title=f"newkingjamesversion{suffix}",
            file_hash=digest,
            content_hash=digest,
            original_extension=".pdf",
        )

    def _embeddings(self):
        embeddings = MagicMock()
        embeddings.embed_documents.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)
        return embeddings

    def test_upserts_nkjv_scale_points_in_small_batches(self):
        doc = self._document("b")
        qdrant = MagicMock()
        chunks = [f"Genesis 1:{i} In the beginning God created {i}." for i in range(1, 6)]
        env = {
            "INGEST_QDRANT_UPSERT_BATCH": "2",
            "INGEST_QDRANT_UPSERT_RETRIES": "1",
        }
        with patch.dict(os.environ, env):
            created, skipped = _upsert_chunks(
                doc.source_name,
                doc.title,
                chunks,
                doc.file_hash,
                document=doc,
                embeddings=self._embeddings(),
                qdrant_client=qdrant,
                collection_name="sermon_brain",
            )

        self.assertEqual(created, 5)
        self.assertEqual(skipped, 0)
        self.assertEqual(qdrant.upsert.call_count, 3)
        sizes = [len(call.kwargs["points"]) for call in qdrant.upsert.call_args_list]
        self.assertEqual(sizes, [2, 2, 1])
        for call in qdrant.upsert.call_args_list:
            self.assertEqual(call.kwargs["collection_name"], "sermon_brain")
            self.assertTrue(call.kwargs["wait"])
        self.assertEqual(IngestedChunk.objects.filter(document=doc).count(), 5)
        qdrant.delete.assert_not_called()

    def test_retries_a_failed_batch_then_continues(self):
        doc = self._document("c")
        qdrant = MagicMock()
        qdrant.upsert.side_effect = [RuntimeError("timeout"), None, None]
        chunks = ["John 3:16 For God so loved the world.", "John 3:17 For God did not send."]
        env = {
            "INGEST_QDRANT_UPSERT_BATCH": "1",
            "INGEST_QDRANT_UPSERT_RETRIES": "3",
            "INGEST_QDRANT_UPSERT_RETRY_DELAY_S": "0",
        }
        with patch.dict(os.environ, env):
            created, skipped = _upsert_chunks(
                doc.source_name,
                doc.title,
                chunks,
                doc.file_hash,
                document=doc,
                embeddings=self._embeddings(),
                qdrant_client=qdrant,
                collection_name="sermon_brain",
            )

        self.assertEqual((created, skipped), (2, 0))
        self.assertEqual(qdrant.upsert.call_count, 3)
        qdrant.delete.assert_not_called()

    def test_rolls_back_qdrant_points_when_a_later_batch_fails(self):
        doc = self._document("d")
        qdrant = MagicMock()
        qdrant.upsert.side_effect = [None, RuntimeError("JSON payload is larger than allowed")]
        chunks = [
            "Psalm 23:1 The Lord is my shepherd.",
            "Psalm 23:2 He makes me to lie down.",
            "Psalm 23:3 He restores my soul.",
        ]
        env = {
            "INGEST_QDRANT_UPSERT_BATCH": "2",
            "INGEST_QDRANT_UPSERT_RETRIES": "1",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(RuntimeError):
                _upsert_chunks(
                    doc.source_name,
                    doc.title,
                    chunks,
                    doc.file_hash,
                    document=doc,
                    embeddings=self._embeddings(),
                    qdrant_client=qdrant,
                    collection_name="sermon_brain",
                )

        qdrant.delete.assert_called_once()
        selector = qdrant.delete.call_args.kwargs["points_selector"]
        must = selector.filter.must
        self.assertEqual(must[0].match.value, doc.source_name)
        self.assertEqual(must[1].match.value, doc.file_hash)
