"""RunPod Serverless Faster-Whisper client for CPU-pod video ingest.

The CPU host still runs ffmpeg. Audio is compressed and posted to a dedicated
Whisper GPU endpoint (not the vLLM worker) via ``/runsync``.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

from .transcript_normalize import TranscriptSegment, segments_from_whisper

logger = logging.getLogger(__name__)

_RUNPOD_V2_PREFIX = "https://api.runpod.ai/v2/"


def _env_get(env: Mapping[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        raw = env.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return default


def _placeholder_key(value: str) -> bool:
    lowered = (value or "").strip().lower()
    if not lowered:
        return True
    return lowered in {"not-needed", "empty", "paste_here"} or "paste_here" in lowered


def _resolved_env(env: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
    """Use caller env when provided; otherwise overlay config.env / tokens.env.

    Passing raw ``os.environ`` is treated as unset so a zeroed gunicorn
    environ cannot skip the file overlay and 401 against Serverless Whisper.
    """
    if env is not None and env is not os.environ:
        return env
    from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

    load_workspace_env()
    return env_with_workspace()


def resolve_whisper_runsync_url(env: Optional[Mapping[str, str]] = None) -> str:
    env = _resolved_env(env)
    endpoint_id = _env_get(env, "RUNPOD_WHISPER_ENDPOINT_ID")
    if endpoint_id:
        return f"{_RUNPOD_V2_PREFIX}{endpoint_id}/runsync"
    raw = _env_get(env, "WHISPER_URL").rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/runsync") or raw.endswith("/run"):
        return raw if raw.endswith("/runsync") else f"{raw}sync"
    if "api.runpod.ai/v2/" in raw and "/openai/" not in raw:
        return f"{raw}/runsync"
    return raw


def resolve_whisper_api_key(env: Optional[Mapping[str, str]] = None) -> str:
    env = _resolved_env(env)
    key = _env_get(env, "WHISPER_API_KEY", "RUNPOD_API_KEY", "VLLM_API_KEY")
    if _placeholder_key(key):
        return ""
    return key


def whisper_is_remote(env: Optional[Mapping[str, str]] = None) -> bool:
    env = _resolved_env(env)
    mode = _env_get(env, "WHISPER_MODE").lower()
    if mode in {"serverless", "remote", "gpu"}:
        return True
    if _env_get(env, "RUNPOD_WHISPER_ENDPOINT_ID"):
        return True
    url = resolve_whisper_runsync_url(env)
    return bool(url) and "127.0.0.1" not in url and "localhost" not in url


def parse_runsync_payload(data) -> List[TranscriptSegment]:
    """Turn a RunPod /runsync JSON body (or a worker output object) into segments."""
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Whisper worker returned unexpected payload type: {type(data).__name__}")

    status = str(data.get("status") or "").upper()
    if status and status not in {"COMPLETED", "SUCCESS"}:
        detail = data.get("error") or data.get("output") or status
        raise RuntimeError(f"RunPod Whisper job {status}: {detail}")

    output = data.get("output", data)
    if isinstance(output, list):
        output = output[0] if output else {}
    if not isinstance(output, dict):
        raise RuntimeError("Whisper worker output was not an object")

    nested = output.get("output")
    if isinstance(nested, dict) and ("segments" in nested or "transcription" in nested):
        output = nested

    segs = segments_from_whisper(output.get("segments") or [])
    if segs:
        return segs
    text = str(output.get("transcription") or output.get("text") or "").strip()
    if text:
        return [TranscriptSegment(start=0.0, end=0.0, text=text)]
    raise RuntimeError("Whisper worker returned no transcript segments")


def stitch_chunk_segments(
    chunks: Sequence[tuple[float, Sequence[TranscriptSegment]]],
    overlap_s: float,
) -> List[TranscriptSegment]:
    """Merge per-chunk transcripts. ``chunks`` is (audio_offset_seconds, segments)."""
    out: List[TranscriptSegment] = []
    half = max(0.0, float(overlap_s) / 2.0)
    for index, (offset, segs) in enumerate(chunks):
        skip_before = offset if index == 0 else offset + half
        for seg in segs:
            start = float(seg.start) + offset
            end = float(seg.end) + offset
            if index > 0 and start < skip_before:
                continue
            if end < start:
                end = start
            out.append(TranscriptSegment(start=start, end=end, text=seg.text))
    return out


def wav_duration_s(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as handle:
        rate = handle.getframerate() or 1
        return handle.getnframes() / float(rate)


def _ffmpeg_bin() -> str:
    binary = shutil.which(os.environ.get("FFMPEG_PATH", "ffmpeg"))
    if not binary:
        raise RuntimeError("Video transcription requires ffmpeg on PATH.")
    return binary


def encode_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "48k") -> None:
    timeout_s = int(os.environ.get("VIDEO_FFMPEG_TIMEOUT_S", "900"))
    result = subprocess.run(
        [
            _ffmpeg_bin(),
            "-y",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(mp3_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0 or not mp3_path.is_file() or mp3_path.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"ffmpeg failed to encode mp3 for Whisper: {detail[:800]}")


def slice_wav(wav_path: Path, dest_path: Path, start_s: float, duration_s: float) -> None:
    timeout_s = int(os.environ.get("VIDEO_FFMPEG_TIMEOUT_S", "900"))
    result = subprocess.run(
        [
            _ffmpeg_bin(),
            "-y",
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{duration_s:.3f}",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dest_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0 or not dest_path.is_file() or dest_path.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"ffmpeg failed to slice audio for Whisper: {detail[:800]}")


def _max_base64_chars(env: Mapping[str, str]) -> int:
    raw = _env_get(env, "WHISPER_MAX_BASE64_CHARS", default="5500000")
    try:
        return max(500_000, int(raw))
    except ValueError:
        return 5_500_000


def _chunk_seconds(env: Mapping[str, str]) -> float:
    try:
        return max(60.0, float(_env_get(env, "WHISPER_REMOTE_CHUNK_S", default="480")))
    except ValueError:
        return 480.0


def _overlap_seconds(env: Mapping[str, str]) -> float:
    try:
        return max(0.0, float(_env_get(env, "WHISPER_REMOTE_OVERLAP_S", default="5")))
    except ValueError:
        return 5.0


def _file_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def post_whisper_runsync(
    *,
    audio_base64: str,
    env: Optional[Mapping[str, str]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[TranscriptSegment]:
    env = _resolved_env(env)
    url = resolve_whisper_runsync_url(env)
    key = resolve_whisper_api_key(env)
    if not url:
        raise RuntimeError(
            "Whisper serverless is enabled but RUNPOD_WHISPER_ENDPOINT_ID / WHISPER_URL is empty."
        )
    if not key:
        raise RuntimeError("Whisper serverless needs RUNPOD_API_KEY (or WHISPER_API_KEY).")

    import requests

    model = _env_get(env, "WHISPER_MODEL", default="base")
    language = _env_get(env, "WHISPER_LANGUAGE") or None
    timeout_s = float(_env_get(env, "WHISPER_TIMEOUT_S", default="600"))
    payload = {
        "audio_base64": audio_base64,
        "model": model,
        "transcription": "plain_text",
        "translate": False,
        "condition_on_previous_text": True,
        "enable_vad": False,
        "word_timestamps": False,
    }
    if language:
        payload["language"] = language
    if log_fn:
        log_fn(f"Sending audio to serverless Whisper ({model}) at {url}.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        url,
        json={"input": payload},
        headers=headers,
        timeout=timeout_s,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = (response.text or "")[:500]
        raise RuntimeError(f"Whisper serverless HTTP {response.status_code}: {body}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Whisper serverless returned non-JSON") from exc
    return parse_runsync_payload(data)


def transcribe_audio_remote(
    wav_path: Path,
    *,
    env: Optional[Mapping[str, str]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[TranscriptSegment]:
    """Compress a local WAV and transcribe it on the RunPod Whisper GPU worker."""
    env = _resolved_env(env)
    wav_path = Path(wav_path)
    bitrate = _env_get(env, "WHISPER_REMOTE_BITRATE", default="48k")
    max_b64 = _max_base64_chars(env)
    overlap_s = _overlap_seconds(env)

    with tempfile.TemporaryDirectory(prefix="pastor_ai_whisper_remote_") as tmp:
        tmp_dir = Path(tmp)
        mp3_path = tmp_dir / "full.mp3"
        encode_mp3(wav_path, mp3_path, bitrate=bitrate)
        encoded = _file_to_base64(mp3_path)
        if len(encoded) <= max_b64:
            return post_whisper_runsync(audio_base64=encoded, env=env, log_fn=log_fn)

        duration = wav_duration_s(wav_path)
        chunk_s = _chunk_seconds(env)
        if log_fn:
            log_fn(
                f"Audio is too large for one Whisper request "
                f"({len(encoded)} chars); splitting into {chunk_s:.0f}s GPU chunks."
            )
        stitched: List[tuple[float, List[TranscriptSegment]]] = []
        start = 0.0
        index = 0
        while start < duration:
            piece = tmp_dir / f"chunk-{index}.wav"
            slice_wav(wav_path, piece, start, min(chunk_s, duration - start + overlap_s))
            part_mp3 = tmp_dir / f"chunk-{index}.mp3"
            encode_mp3(piece, part_mp3, bitrate=bitrate)
            segs = post_whisper_runsync(
                audio_base64=_file_to_base64(part_mp3),
                env=env,
                log_fn=log_fn,
            )
            stitched.append((start, segs))
            start += chunk_s
            index += 1
            if index > 64:
                raise RuntimeError("Whisper remote split produced too many chunks")
        return stitch_chunk_segments(stitched, overlap_s)
