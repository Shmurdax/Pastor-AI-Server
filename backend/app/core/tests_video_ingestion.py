import json
import os
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
            with patch.dict(os.environ, {"VIDEO_TOPIC_METADATA_LLM": "0"}), patch(
                "core.video_ingestion.admin_video_ingestion_dir", return_value=Path(tmp)
            ), patch(
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
            self.assertTrue((Path(tmp) / "sunday_talk.m4a").is_file())
            self.assertTrue((Path(tmp) / "sunday_talk.transcript.json").is_file())

    def test_ingest_skips_empty_audio_without_failing_job(self):
        class FakeUpload:
            name = "382077209.m4a"

            def read(self):
                return b""

        fake_embeddings = MagicMock()
        fake_qdrant = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.video_ingestion.admin_video_ingestion_dir", return_value=Path(tmp)), patch(
                "core.video_ingestion.get_embeddings", return_value=fake_embeddings
            ), patch("core.video_ingestion.QdrantClient", return_value=fake_qdrant), patch(
                "core.video_ingestion.ensure_sermon_collection"
            ):
                result = ingest_video_files(
                    [FakeUpload()],
                    transcribe_fn=lambda _path: [],
                )

        self.assertEqual(result.files_received, 1)
        self.assertEqual(result.files_processed, 0)
        self.assertEqual(result.files_failed, 0)
        self.assertEqual(result.files_skipped_as_duplicates, 1)


class VideoIngestionAdminTests(TestCase):
    def test_video_admin_urls_resolve(self):
        prefix = f"/{settings.ADMIN_URL_PATH}"
        self.assertEqual(reverse("admin:core_video_ingestion"), f"{prefix}/core/video-ingestion/")
        self.assertEqual(reverse("admin:core_video_ingestion_chunk"), f"{prefix}/core/video-ingestion/chunk/")
        self.assertEqual(reverse("admin:core_ingested_videos"), f"{prefix}/core/ingested-videos/")
        self.assertEqual(reverse("admin:core_embedded_videos"), f"{prefix}/core/embedded-videos/")
        self.assertEqual(
            reverse("admin:core_embedded_video_detail", args=["1217796650"]),
            f"{prefix}/core/embedded-videos/1217796650/",
        )
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

    def test_video_ingestion_page_captures_dropped_files_synchronously(self):
        template = Path(__file__).resolve().parent / "templates" / "admin" / "core" / "video_ingestion.html"
        body = template.read_text(encoding="utf-8")
        self.assertIn("getAsFile()", body)
        self.assertIn("arrayBuffer", body)
        self.assertIn("Select folder", body)

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

    @patch("core.admin._queue_video_job_from_path")
    def test_chunked_upload_assembles_file_then_queues(self, mock_queue):
        captured = {}

        def capture_job(**kwargs):
            captured["name"] = kwargs["original_name"]
            captured["bytes"] = Path(kwargs["source_path"]).read_bytes()
            job = MagicMock()
            job.id = 77
            return job

        mock_queue.side_effect = capture_job
        upload_id = "11111111-1111-4111-8111-111111111111"
        url = reverse("admin:core_video_ingestion_chunk")
        first = SimpleUploadedFile("chunk", b"hello ", content_type="application/octet-stream")
        second = SimpleUploadedFile("chunk", b"m4a!!", content_type="application/octet-stream")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.admin._video_chunk_root", return_value=Path(tmp)):
                start = self.client.post(
                    url,
                    {
                        "upload_id": upload_id,
                        "file_name": "talk.m4a",
                        "chunk_index": "0",
                        "chunk_count": "2",
                        "file_size": "11",
                        "chunk": first,
                    },
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertEqual(start.status_code, 200)
                self.assertFalse(start.json()["complete"])
                mock_queue.assert_not_called()

                finish = self.client.post(
                    url,
                    {
                        "upload_id": upload_id,
                        "file_name": "talk.m4a",
                        "chunk_index": "1",
                        "chunk_count": "2",
                        "file_size": "11",
                        "chunk": second,
                    },
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
        self.assertEqual(finish.status_code, 200)
        payload = finish.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["job_id"], 77)
        self.assertEqual(captured["name"], "talk.m4a")
        self.assertEqual(captured["bytes"], b"hello m4a!!")

    def test_chunked_upload_rejects_pdf(self):
        response = self.client.post(
            reverse("admin:core_video_ingestion_chunk"),
            {
                "upload_id": "22222222-2222-4222-8222-222222222222",
                "file_name": "notes.pdf",
                "chunk_index": "0",
                "chunk_count": "1",
                "file_size": "4",
                "chunk": SimpleUploadedFile("chunk", b"%PDF"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)

    def test_chunked_upload_skips_empty_file(self):
        response = self.client.post(
            reverse("admin:core_video_ingestion_chunk"),
            {
                "upload_id": "33333333-3333-4333-8333-333333333333",
                "file_name": "382077209.m4a",
                "chunk_index": "0",
                "chunk_count": "1",
                "file_size": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "empty")


class VideoJobPersistenceTests(TestCase):
    def test_jobs_and_chunks_follow_env_dirs(self):
        from core.storage_paths import admin_video_ingestion_chunks_dir, admin_video_ingestion_jobs_dir

        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "jobs"
            chunks = Path(tmp) / "chunks"
            with patch.dict(
                os.environ,
                {
                    "VIDEO_INGESTION_JOBS_DIR": str(jobs),
                    "VIDEO_INGESTION_CHUNKS_DIR": str(chunks),
                },
            ):
                self.assertEqual(admin_video_ingestion_jobs_dir(), jobs.resolve())
                self.assertEqual(admin_video_ingestion_chunks_dir(), chunks.resolve())

    def test_manifest_round_trip_keeps_original_names(self):
        from core.ingestion_tasks import StagedUpload
        from core.video_job_queue import load_video_job_uploads, persist_video_job_manifest

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"VIDEO_INGESTION_JOBS_DIR": tmp}):
                job_dir = Path(tmp) / "job_9"
                job_dir.mkdir()
                staged = job_dir / "0000_458394609.m4a"
                staged.write_bytes(b"audio")
                persist_video_job_manifest(
                    9,
                    [StagedUpload(original_name="458394609.m4a", staged_path=str(staged))],
                    False,
                )
                uploads, replace = load_video_job_uploads(9)
                self.assertFalse(replace)
                self.assertEqual(len(uploads), 1)
                self.assertEqual(uploads[0].original_name, "458394609.m4a")
                self.assertTrue(Path(uploads[0].staged_path).is_file())

    def test_stale_marker_keeps_video_jobs_that_still_have_staging(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.admin import _mark_stale_running_jobs_failed
        from core.ingestion_tasks import StagedUpload
        from core.models import IngestionJob
        from core.video_job_queue import persist_video_job_manifest

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"VIDEO_INGESTION_JOBS_DIR": tmp}):
                job = IngestionJob.objects.create(
                    started_by="test",
                    job_kind="video",
                    status="running",
                    files_received=1,
                )
                staged = Path(tmp) / f"job_{job.id}" / "0000_talk.m4a"
                staged.parent.mkdir(parents=True)
                staged.write_bytes(b"audio")
                persist_video_job_manifest(
                    job.id,
                    [StagedUpload(original_name="talk.m4a", staged_path=str(staged))],
                    False,
                )
                old = timezone.now() - timedelta(minutes=600)
                IngestionJob.objects.filter(id=job.id).update(created_at=old, updated_at=old)
                self.assertEqual(_mark_stale_running_jobs_failed(), 0)
                job.refresh_from_db()
                self.assertEqual(job.status, "running")

    def test_stale_marker_fails_video_jobs_without_staging(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.admin import _mark_stale_running_jobs_failed
        from core.models import IngestionJob

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"VIDEO_INGESTION_JOBS_DIR": tmp}):
                job = IngestionJob.objects.create(
                    started_by="test",
                    job_kind="video",
                    status="running",
                    files_received=1,
                )
                old = timezone.now() - timedelta(minutes=600)
                IngestionJob.objects.filter(id=job.id).update(created_at=old, updated_at=old)
                self.assertEqual(_mark_stale_running_jobs_failed(), 1)
                job.refresh_from_db()
                self.assertEqual(job.status, "failed")

    def test_enqueue_video_job_does_not_use_gunicorn_thread_pool(self):
        from core.ingestion_tasks import StagedUpload, enqueue_video_ingestion_job

        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "job_12" / "0000_a.m4a"
            staged.parent.mkdir()
            staged.write_bytes(b"x")
            with patch.dict(os.environ, {"VIDEO_INGESTION_JOBS_DIR": tmp}), patch(
                "core.ingestion_tasks._executor.submit"
            ) as submit:
                enqueue_video_ingestion_job(
                    12,
                    [StagedUpload(original_name="a.m4a", staged_path=str(staged))],
                    False,
                )
                submit.assert_not_called()
                self.assertTrue((Path(tmp) / "job_12" / "manifest.json").is_file())

    def test_worker_once_runs_staged_job(self):
        from django.core.management import call_command

        from core.ingestion_service import IngestionResult
        from core.ingestion_tasks import StagedUpload
        from core.models import IngestionJob
        from core.video_job_queue import persist_video_job_manifest

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"VIDEO_INGESTION_JOBS_DIR": tmp}):
                job = IngestionJob.objects.create(
                    started_by="test",
                    job_kind="video",
                    status="running",
                    files_received=1,
                )
                staged = Path(tmp) / f"job_{job.id}" / "0000_talk.m4a"
                staged.parent.mkdir(parents=True)
                staged.write_bytes(b"audio-bytes")
                persist_video_job_manifest(
                    job.id,
                    [StagedUpload(original_name="talk.m4a", staged_path=str(staged))],
                    False,
                )
                with patch("core.video_ingestion.ingest_video_files") as ingest, patch(
                    "core.ingestion_tasks.dump_persistent_postgres"
                ):
                    ingest.return_value = IngestionResult(files_received=1, files_processed=1)
                    call_command("run_video_ingestion_worker", "--once")
                ingest.assert_called_once()
                job.refresh_from_db()
                self.assertEqual(job.status, "completed")