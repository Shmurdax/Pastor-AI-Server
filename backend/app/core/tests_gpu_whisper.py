"""GPU hide flags and Whisper device selection."""

from __future__ import annotations

import os
from unittest import mock

from django.test import SimpleTestCase

from core.whisper_transcribe import whisper_device
from pastor_ai.gpu_env import should_hide_gpu


class GpuEnvTests(SimpleTestCase):
    def test_gunicorn_hides_gpu(self):
        self.assertTrue(should_hide_gpu(argv=["gunicorn"], env={}))

    def test_video_worker_keeps_gpu(self):
        self.assertFalse(
            should_hide_gpu(argv=["manage.py", "run_video_ingestion_worker"], env={})
        )

    def test_allow_flag_keeps_gpu(self):
        self.assertFalse(should_hide_gpu(argv=["manage.py", "migrate"], env={"PASTOR_AI_ALLOW_GPU": "1"}))


class WhisperDeviceTests(SimpleTestCase):
    def test_explicit_cpu(self):
        with mock.patch.dict(os.environ, {"WHISPER_DEVICE": "cpu"}, clear=False):
            self.assertEqual(whisper_device(), "cpu")

    def test_auto_cuda_when_available(self):
        with mock.patch.dict(os.environ, {"WHISPER_DEVICE": "auto"}, clear=False):
            with mock.patch("core.whisper_transcribe._cuda_is_available", return_value=True):
                self.assertEqual(whisper_device(), "cuda")

    def test_auto_cpu_without_cuda(self):
        with mock.patch.dict(os.environ, {"WHISPER_DEVICE": "auto"}, clear=False):
            with mock.patch("core.whisper_transcribe._cuda_is_available", return_value=False):
                self.assertEqual(whisper_device(), "cpu")
