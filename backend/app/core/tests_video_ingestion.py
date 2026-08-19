import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.transcript_normalize import (
    TranscriptSegment,
    format_segment_line,
    format_timestamp,
    format_timestamp_range,
    normalize_transcript_segments,
    segments_from_whisper,
)
from core.video_ingestion import (
    AUDIO_EXTENSIONS,
    MEDIA_EXTENSIONS,
    group_segments_into_chunks,
    ingest_video_files,
    is_audio_filename,
    is_video_filename,
)
from core.views import _strip_source_label


class TimestampFormatTests(TestCase):
    def test_minutes_and_hours(self):
        self.assertEqual(format_timestamp(5), "00:05")
        self.assertEqual(format_timestamp(75), "01:15")
        self.assertEqual(format_timestamp(3661), "01:01:01")

    def test_range_and_line(self):
        self.assertEqual(format_timestamp_range(12, 34), "00:12–00:34")
        seg = TranscriptSegment(start=12, end=34, text="Jesus is Lord.")
        self.assertEqual(format_segment_line(seg), "[00:12–00:34] Jesus is Lord.")


class TranscriptNormalizeTests(TestCase):
    def test_strips_fillers_and_subscribe_fluff(self):
        segments = [
            TranscriptSegment(0, 3, "Um, uh, you know, welcome back to the channel."),
            TranscriptSegment(3, 8, "Don't forget to like and subscribe."),
            TranscriptSegment(8, 20, "Jesus taught that faith without works is dead."),
        ]
        result = normalize_transcript_segments(segments)
        texts = [seg.text.lower() for seg in result.segments]
        self.assertTrue(any("jesus" in text for text in texts))
        self.assertFalse(any("subscribe" in text for text in texts))
        self.assertFalse(any("welcome back to the channel" in text for text in texts))
        self.assertGreater(result.stats.fluff_segments_removed, 0)

    def test_drops_isolated_off_topic_but_keeps_neighbors(self):
        segments = [
            TranscriptSegment(0, 5, "The weather in Houston is rainy today."),
            TranscriptSegment(5, 10, "Also the Texans play tonight."),
            TranscriptSegment(10, 15, "Then we talked about grocery prices."),
            TranscriptSegment(15, 25, "Scripture says God is our refuge and strength."),
            TranscriptSegment(25, 30, "That illustration about the storm still applies."),
        ]
        result = normalize_transcript_segments(segments)
        texts = " ".join(seg.text for seg in result.segments)
        self.assertIn("Scripture", texts)
        self.assertIn("illustration", texts)
        self.assertIn("grocery", texts)
        self.assertNotIn("Texans", texts)
        self.assertNotIn("weather", texts.lower())

    def test_keeps_social_issue_content(self):
        segments = [
            TranscriptSegment(0, 8, "Marriage and family are under pressure in this culture."),
            TranscriptSegment(8, 16, "Abortion is not just politics; it is a moral question."),
        ]
        result = normalize_transcript_segments(segments)
        self.assertEqual(len(result.segments), 2)

    def test_keeps_everything_when_lexicon_misses(self):
        segments = [
            TranscriptSegment(0, 5, "The speaker continued the story."),
            TranscriptSegment(5, 10, "Then the crowd grew quiet."),
        ]
        result = normalize_transcript_segments(segments)
        self.assertEqual(len(result.segments), 2)

    def test_segments_from_whisper(self):
        raw = [{"start": 1.2, "end": 3.4, "text": "  Amen.  "}]
        segs = segments_from_whisper(raw)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].text, "Amen.")
        self.assertEqual(segs[0].start, 1.2)


class VideoHelpersTests(TestCase):
    def test_video_extensions(self):
        self.assertTrue(is_video_filename("sermon.MP4"))
        self.assertTrue(is_video_filename("clip.webm"))
        self.assertTrue(is_video_filename("tape.m2ts"))
        self.assertFalse(is_video_filename("notes.pdf"))
        self.assertFalse(is_video_filename("slides.docx"))

    def test_audio_extensions(self):
        self.assertTrue(is_audio_filename("talk.m4a"))
        self.assertTrue(is_video_filename("talk.M4A"))
        self.assertTrue(is_video_filename("clip.mp3"))
        self.assertTrue(is_video_filename("room.wav"))
        self.assertTrue(is_video_filename("sermon.flac"))
        self.assertTrue(is_video_filename("podcast.aac"))
        self.assertTrue(is_video_filename("session.ogg"))
        self.assertTrue(is_video_filename("voice.opus"))
        self.assertIn(".m4a", AUDIO_EXTENSIONS)
        self.assertTrue(AUDIO_EXTENSIONS.issubset(MEDIA_EXTENSIONS))

    def test_django_allows_500_plus_uploads(self):
        self.assertGreaterEqual(settings.DATA_UPLOAD_MAX_NUMBER_FILES, 500)
        self.assertGreaterEqual(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS, 500)

    def test_group_segments_respects_chunk_size(self):
        segments = [
            TranscriptSegment(0, 2, "Jesus called the disciples."),
            TranscriptSegment(2, 4, "Faith comes by hearing the word."),
            TranscriptSegment(4, 6, "The church must love its neighbors."),
        ]
        groups = group_segments_into_chunks(segments, chunk_size=60, overlap_segments=0)
        self.assertGreaterEqual(len(groups), 2)
        self.assertTrue(all(group for group in groups))

    def test_strip_source_label(self):
        self.assertEqual(_strip_source_label("Faith [12:34–14:02]"), "Faith")
        self.assertEqual(_strip_source_label("Faith.mp4"), "Faith")
        self.assertEqual(_strip_source_label("Faith.pdf"), "Faith")


class VideoIngestPipelineTests(TestCase):
    def test_ingest_video_creates_timestamped_chunks(self):
        class FakeUpload:
            name = "faith_that_moves.mp4"

            def read(self):
                return b"fake-video-bytes"

        segments = [
            TranscriptSegment(12, 20, "Um, Jesus taught that faith moves mountains."),
            TranscriptSegment(20, 28, "Don't forget to subscribe."),
            TranscriptSegment(28, 40, "The Bible says this kind comes by prayer."),
        ]

        def fake_transcribe(_path):
            return segments

        fake_embeddings = MagicMock()
        fake_embeddings.embed_documents.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)
        fake_qdrant = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.video_ingestion.admin_video_ingestion_dir", return_value=Path(tmp)), patch(
                "core.video_ingestion.get_embeddings", return_value=fake_embeddings
            ), patch("core.video_ingestion.QdrantClient", return_value=fake_qdrant), patch(
                "core.video_ingestion.ensure_sermon_collection"
            ):
                result = ingest_video_files(
                    [FakeUpload()],
                    transcribe_fn=fake_transcribe,
                )

            self.assertEqual(result.files_processed, 1)
            self.assertGreater(result.chunks_created, 0)
            sidecar = Path(tmp) / "faith_that_moves.transcript.json"
            self.assertTrue(sidecar.is_file())
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertTrue(payload["segments_normalized"])
            self.assertTrue((Path(tmp) / "faith_that_moves.mp4").is_file())
            upserted = fake_qdrant.upsert.call_args.kwargs["points"]
            self.assertTrue(upserted)
            first_payload = upserted[0].payload
            self.assertEqual(first_payload["content_type"], "video_transcript")
            self.assertIn("timestamp", first_payload)
            self.assertIn("[", first_payload["text"])
            self.assertIn("Jesus", first_payload["text"])
            self.assertNotIn("subscribe", first_payload["text"].lower())

    def test_ingest_m4a_audio_creates_timestamped_chunks(self):
        class FakeUpload:
            name = "sunday_talk.m4a"

            def read(self):
                return b"fake-audio-bytes"

        segments = [
            TranscriptSegment(0, 8, "The Bible says the word became flesh."),
        ]

        fake_embeddings = MagicMock()
        fake_embeddings.embed_documents.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)
        fake_qdrant = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.video_ingestion.admin_video_ingestion_dir", return_value=Path(tmp)), patch(
                "core.video_ingestion.get_embeddings", return_value=fake_embeddings
            ), patch("core.video_ingestion.QdrantClient", return_value=fake_qdrant), patch(
                "core.video_ingestion.ensure_sermon_collection"
            ):
                result = ingest_video_files(
                    [FakeUpload()],
                    transcribe_fn=lambda _path: segments,
                )

            self.assertEqual(result.files_processed, 1)
            self.assertTrue((Path(tmp) / "sunday_talk.m4a").is_file())
            self.assertTrue((Path(tmp) / "sunday_talk.transcript.json").is_file())


class VideoIngestionAdminTests(TestCase):
    def test_video_admin_urls_resolve(self):
        self.assertEqual(reverse("admin:core_video_ingestion"), "/admin/core/video-ingestion/")
        self.assertEqual(reverse("admin:core_ingested_videos"), "/admin/core/ingested-videos/")
        self.assertTrue(
            reverse("admin:core_ingested_video_file", args=["sermon.mp4"]).endswith(
                "/ingested-videos/file/sermon.mp4/"
            )
        )

    def setUp(self):
        self.user = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    @patch("core.admin.enqueue_video_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_admin_accepts_m4a(self, _stage, mock_enqueue):
        upload = SimpleUploadedFile("sermon.m4a", b"audio-bytes", content_type="audio/mp4")
        response = self.client.post(
            reverse("admin:core_video_ingestion"),
            {"videos": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["files_received"], 1)
        mock_enqueue.assert_called_once()

    @patch("core.admin.enqueue_video_ingestion_job")
    @patch("core.admin._stage_uploads", return_value=[])
    def test_admin_accepts_over_500_audio_files(self, _stage, mock_enqueue):
        uploads = [
            SimpleUploadedFile(f"sermon_{index:04d}.m4a", b"a", content_type="audio/mp4")
            for index in range(501)
        ]
        response = self.client.post(
            reverse("admin:core_video_ingestion"),
            {"videos": uploads},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["files_received"], 501)
        mock_enqueue.assert_called_once()

    def test_admin_rejects_pdf_on_video_endpoint(self):
        upload = SimpleUploadedFile("notes.pdf", b"%PDF", content_type="application/pdf")
        response = self.client.post(
            reverse("admin:core_video_ingestion"),
            {"videos": upload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video and audio", response.json()["error"])