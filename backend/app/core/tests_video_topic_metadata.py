"""Tests for searchable video topic metadata used by RAG embeddings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from core.chat_retrieval import apply_retrieval_threshold, sources_cited_in_answer
from core.transcript_normalize import TranscriptSegment
from core.video_ingestion import build_video_chunks_with_topic_metadata, ingest_video_files
from core.video_topic_metadata import (
    build_video_topic_metadata,
    display_title_for_document,
    extract_heuristic_metadata,
    format_searchable_header,
    title_looks_like_date_only,
)


class VideoTopicMetadataTests(TestCase):
    def test_date_only_title_detection(self):
        self.assertTrue(title_looks_like_date_only("May 23"))
        self.assertTrue(title_looks_like_date_only("June 30"))
        self.assertFalse(title_looks_like_date_only("Faith That Moves"))

    def test_heuristic_builds_searchable_header(self):
        transcript = (
            "Pastor Don Nordin teaches that women who lead with humility serve the church. "
            "Elders must be above reproach according to Titus 1:6. "
            "Complementarian and egalitarian views both need careful Scripture study."
        )
        meta = extract_heuristic_metadata(transcript, original_title="May 23")
        self.assertTrue(meta.topic_title)
        self.assertFalse(title_looks_like_date_only(meta.topic_title))
        self.assertTrue(any("titus" in r.lower() for r in meta.scripture_refs))
        header = format_searchable_header(meta)
        self.assertIn("Topics:", header)
        self.assertIn("Keywords:", header)
        self.assertIn("Search phrases:", header)
        display = display_title_for_document(meta, "May 23")
        self.assertIn("May 23", display)
        self.assertNotEqual(display.lower(), "may 23")

    @override_settings()
    def test_llm_merge_prefers_topical_title(self):
        transcript = (
            "Marriage requires covenant faithfulness. Ephesians 5:23 shows Christ and the church. "
            "Husbands love your wives as Christ loved the church."
        )

        def fake_invoke(_client, _prompt):
            return json.dumps(
                {
                    "topic_title": "Covenant Marriage and Christlike Love",
                    "topics": ["marriage", "covenant", "Ephesians 5"],
                    "keywords": ["marriage", "husbands", "wives", "covenant"],
                    "summary": "Teaching on covenant marriage from Ephesians 5.",
                    "scripture_refs": ["Ephesians 5:23"],
                    "speakers": ["Pastor Don Nordin"],
                }
            )

        with patch.dict(os.environ, {"VIDEO_TOPIC_METADATA_LLM": "1"}):
            meta = build_video_topic_metadata(
                transcript,
                original_title="May 23",
                llm=object(),
                invoke_fn=fake_invoke,
            )
        self.assertEqual(meta.topic_title, "Covenant Marriage and Christlike Love")
        self.assertEqual(meta.source, "merged")
        self.assertIn("marriage", [t.lower() for t in meta.topics])

    def test_chunks_include_overview_and_header(self):
        segments = [
            TranscriptSegment(10, 20, "Faith without works is dead according to James 2:17."),
            TranscriptSegment(20, 30, "The church must encourage every believer to serve."),
        ]
        with patch.dict(os.environ, {"VIDEO_TOPIC_METADATA_LLM": "0"}):
            meta, display_title, chunks, per_chunk = build_video_chunks_with_topic_metadata(
                original_title="May 23",
                normalized_segments=segments,
                normalized_text="\n".join(s.text for s in segments),
                chunk_size=500,
                overlap_segments=0,
            )
        self.assertTrue(display_title)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(per_chunk[0]["chunk_kind"], "video_topic_overview")
        self.assertIn("Topics:", chunks[0])
        self.assertTrue(any("James" in chunk or "faith" in chunk.lower() for chunk in chunks))


class RetrievalThresholdAndCitationTests(TestCase):
    def test_threshold_0_8_keeps_only_strong_hits(self):
        docs = [(SimpleNamespace(id=i), score) for i, score in enumerate([0.91, 0.85, 0.72, 0.6])]
        kept = apply_retrieval_threshold(docs, threshold=0.8, retrieval_k=24)
        self.assertEqual([s for _d, s in kept], [0.91, 0.85])

    def test_sources_cited_filters_unused_video(self):
        used = SimpleNamespace(
            page_content="x",
            metadata={
                "title": "Elders Charge",
                "topic_title": "Elders Charge",
                "content_type": "document",
            },
        )
        unused = SimpleNamespace(
            page_content="y",
            metadata={
                "title": "May 23",
                "topic_title": "Weather Talk",
                "timestamp": "10:45–12:43",
                "content_type": "video_transcript",
            },
        )

        def label(doc):
            meta = doc.metadata
            name = meta.get("topic_title") or meta.get("title")
            ts = meta.get("timestamp")
            if ts:
                return f"{name} [{ts}]"
            return name

        answer = (
            'As Pastor Don teaches from Elders Charge, "elders must be above reproach." '
            "Titus 1:6 guides the church."
        )
        cited = sources_cited_in_answer([used, unused], answer, label)
        self.assertEqual(cited, ["Elders Charge"])
        self.assertFalse(any("May 23" in item or "Weather" in item for item in cited))


class VideoIngestTopicMetadataTests(TestCase):
    def test_ingest_embeds_topic_metadata(self):
        class FakeUpload:
            name = "May_23.mp4"

            def read(self):
                return b"fake-video-bytes"

        segments = [
            TranscriptSegment(12, 20, "Women serving as pastors and elders require careful Scripture study."),
            TranscriptSegment(20, 28, "Don't forget to subscribe."),
            TranscriptSegment(28, 40, "Titus 1:6 and Ephesians 5:23 shape how we talk about leadership."),
        ]

        fake_embeddings = MagicMock()
        fake_embeddings.embed_documents.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)
        fake_qdrant = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"VIDEO_TOPIC_METADATA_LLM": "0"}), patch(
                "core.video_ingestion.admin_video_ingestion_dir", return_value=Path(tmp)
            ), patch(
                "core.video_ingestion.get_embeddings", return_value=fake_embeddings
            ), patch("core.video_ingestion.QdrantClient", return_value=fake_qdrant), patch(
                "core.video_ingestion.ensure_sermon_collection"
            ):
                result = ingest_video_files(
                    [FakeUpload()],
                    transcribe_fn=lambda _path: segments,
                )

            self.assertEqual(result.files_processed, 1)
            sidecar = json.loads((Path(tmp) / "May_23.transcript.json").read_text(encoding="utf-8"))
            self.assertIn("topic_metadata", sidecar)
            self.assertTrue(sidecar["topic_metadata"].get("topics") or sidecar["topic_metadata"].get("keywords"))
            upserted = fake_qdrant.upsert.call_args.kwargs["points"]
            texts = [point.payload["text"] for point in upserted]
            self.assertTrue(any("Topics:" in text for text in texts))
            self.assertTrue(any(point.payload.get("chunk_kind") == "video_topic_overview" for point in upserted))
            self.assertTrue(any(point.payload.get("topic_title") for point in upserted))
