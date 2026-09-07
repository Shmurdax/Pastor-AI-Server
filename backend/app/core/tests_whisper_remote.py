from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.transcript_normalize import TranscriptSegment
from core.whisper_remote import (
    parse_runsync_payload,
    post_whisper_runsync,
    resolve_whisper_api_key,
    resolve_whisper_runsync_url,
    stitch_chunk_segments,
    whisper_is_remote,
)
from core.whisper_transcribe import transcribe_audio_file


class WhisperRemoteResolutionTests(SimpleTestCase):
    def test_endpoint_id_builds_runsync_url(self):
        env = {"RUNPOD_WHISPER_ENDPOINT_ID": "whisp1", "WHISPER_URL": "ignore-me"}
        self.assertEqual(
            resolve_whisper_runsync_url(env),
            "https://api.runpod.ai/v2/whisp1/runsync",
        )
        self.assertTrue(whisper_is_remote(env))

    def test_bare_runpod_url_appends_runsync(self):
        self.assertEqual(
            resolve_whisper_runsync_url({"WHISPER_URL": "https://api.runpod.ai/v2/abc"}),
            "https://api.runpod.ai/v2/abc/runsync",
        )

    def test_vllm_openai_url_does_not_enable_whisper(self):
        env = {"VLLM_URL": "https://api.runpod.ai/v2/llm/openai/v1"}
        self.assertFalse(whisper_is_remote(env))
        self.assertEqual(resolve_whisper_runsync_url(env), "")

    def test_api_key_fallback(self):
        self.assertEqual(resolve_whisper_api_key({}), "")
        self.assertEqual(resolve_whisper_api_key({"RUNPOD_API_KEY": "rpa_live"}), "rpa_live")
        self.assertEqual(
            resolve_whisper_api_key({"WHISPER_API_KEY": "wh", "RUNPOD_API_KEY": "rpa_live"}),
            "wh",
        )


class WhisperRunsyncParseTests(SimpleTestCase):
    def test_parses_completed_worker_output(self):
        segs = parse_runsync_payload(
            {
                "status": "COMPLETED",
                "output": {
                    "segments": [
                        {"start": 0.1, "end": 2.4, "text": " Scripture is true."},
                    ],
                    "transcription": "Scripture is true.",
                },
            }
        )
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].text, "Scripture is true.")
        self.assertEqual(segs[0].start, 0.1)

    def test_failed_job_raises(self):
        with self.assertRaises(RuntimeError):
            parse_runsync_payload({"status": "FAILED", "error": "oom"})

    def test_stitch_skips_overlap_on_later_chunks(self):
        first = [TranscriptSegment(0.0, 5.0, "one"), TranscriptSegment(5.0, 10.0, "two")]
        second = [TranscriptSegment(0.0, 3.0, "overlap"), TranscriptSegment(4.0, 8.0, "three")]
        merged = stitch_chunk_segments([(0.0, first), (8.0, second)], overlap_s=4.0)
        texts = [seg.text for seg in merged]
        self.assertEqual(texts, ["one", "two", "three"])
        self.assertEqual(merged[-1].start, 12.0)


class WhisperTranscribeRoutingTests(SimpleTestCase):
    @patch("core.whisper_remote.transcribe_audio_remote")
    @patch("core.whisper_remote.whisper_is_remote", return_value=True)
    def test_transcribe_audio_uses_remote_when_configured(self, _remote_flag, mock_remote):
        mock_remote.return_value = [TranscriptSegment(0.0, 1.0, "Amen.")]
        segs = transcribe_audio_file(Path("/tmp/sermon.wav"))
        self.assertEqual(segs[0].text, "Amen.")
        mock_remote.assert_called_once()

    @patch("requests.post")
    def test_post_runsync_sends_faster_whisper_input(self, mock_post):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "COMPLETED",
            "output": {"segments": [{"start": 0, "end": 1, "text": "Hi"}]},
        }
        mock_post.return_value = response
        segs = post_whisper_runsync(
            audio_base64="YQ==",
            env={
                "RUNPOD_WHISPER_ENDPOINT_ID": "wh1",
                "RUNPOD_API_KEY": "rpa",
                "WHISPER_MODEL": "base",
            },
        )
        self.assertEqual(segs[0].text, "Hi")
        sent = mock_post.call_args.kwargs["json"]["input"]
        self.assertEqual(sent["audio_base64"], "YQ==")
        self.assertEqual(sent["model"], "base")
        self.assertIn("Authorization", mock_post.call_args.kwargs["headers"])
