"""
Whisper transcription for admin video ingestion.

Runs on CPU by default so it does not compete with vLLM for GPU VRAM.
ffmpeg extracts a 16 kHz mono WAV first; openai-whisper then returns
segment timestamps for RAG citations.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from .transcript_normalize import TranscriptSegment, segments_from_whisper

logger = logging.getLogger(__name__)

_WHISPER_MODEL = None
_WHISPER_MODEL_NAME: Optional[str] = None


def whisper_model_name() -> str:
    return (os.getenv("WHISPER_MODEL") or "base").strip() or "base"


def whisper_device() -> str:
    raw = (os.getenv("WHISPER_DEVICE") or "cpu").strip().lower()
    return raw or "cpu"


def whisper_language() -> Optional[str]:
    raw = (os.getenv("WHISPER_LANGUAGE") or "").strip()
    return raw or None


def _ffmpeg_bin() -> str:
    binary = shutil.which(os.environ.get("FFMPEG_PATH", "ffmpeg"))
    if not binary:
        raise RuntimeError(
            "Video transcription requires ffmpeg on PATH. "
            "Install ffmpeg (apt install ffmpeg) or set FFMPEG_PATH."
        )
    return binary


def extract_audio_wav(video_path: Path, wav_path: Path) -> None:
    """Demux audio to 16 kHz mono PCM so Whisper does not parse the container."""
    ffmpeg = _ffmpeg_bin()
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_s = int(os.environ.get("VIDEO_FFMPEG_TIMEOUT_S", "900"))
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"ffmpeg failed to extract audio from {video_path.name}: {detail[:800]}")


def _load_whisper_model():
    global _WHISPER_MODEL, _WHISPER_MODEL_NAME
    name = whisper_model_name()
    if _WHISPER_MODEL is not None and _WHISPER_MODEL_NAME == name:
        return _WHISPER_MODEL

    try:
        import whisper
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "openai-whisper is not installed. Add it with `pip install openai-whisper`."
        ) from exc

    device = whisper_device()
    download_root = (os.getenv("WHISPER_CACHE_DIR") or "").strip() or None
    logger.info("Loading Whisper model %s on device=%s", name, device)
    kwargs = {"device": device}
    if download_root:
        kwargs["download_root"] = download_root
    _WHISPER_MODEL = whisper.load_model(name, **kwargs)
    _WHISPER_MODEL_NAME = name
    return _WHISPER_MODEL


def transcribe_audio_file(
    audio_path: Path,
    *,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[TranscriptSegment]:
    model = _load_whisper_model()
    language = whisper_language()
    if log_fn:
        lang_label = language or "auto"
        log_fn(
            f"Running Whisper ({whisper_model_name()}, device={whisper_device()}, language={lang_label}) "
            f"on {audio_path.name}."
        )
    # fp16 must be off on CPU; otherwise Whisper errors or silently degrades.
    kwargs = {
        "verbose": False,
        "fp16": whisper_device() != "cpu",
        "condition_on_previous_text": True,
    }
    if language:
        kwargs["language"] = language
    result = model.transcribe(str(audio_path), **kwargs)
    segments = segments_from_whisper(result.get("segments") or [])
    if not segments:
        full_text = str(result.get("text") or "").strip()
        if full_text:
            segments = [TranscriptSegment(start=0.0, end=0.0, text=full_text)]
    return segments


def transcribe_video_file(
    video_path: Path,
    *,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[TranscriptSegment]:
    """Extract audio from any ffmpeg-readable video, then transcribe with Whisper."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file was not found: {video_path}")

    if log_fn:
        log_fn(f"Extracting audio with ffmpeg: {video_path.name}")

    with tempfile.TemporaryDirectory(prefix="pastor_ai_whisper_") as tmp:
        wav_path = Path(tmp) / f"{video_path.stem}.wav"
        extract_audio_wav(video_path, wav_path)
        return transcribe_audio_file(wav_path, log_fn=log_fn)
