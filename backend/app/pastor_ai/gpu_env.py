"""GPU process flags shared by manage.py and Whisper.

vLLM owns most of the GPU. Django/gunicorn stay on CPU so chat embeddings
cannot CUDA-OOM against the chat model. The video-ingest worker is the
exception: Whisper should use leftover VRAM on the same MIG device.
"""

from __future__ import annotations

import os
from typing import Iterable, Mapping, Optional


_TRUTHY = {"1", "true", "yes", "on"}


def env_flag(name: str, env: Optional[Mapping[str, str]] = None) -> bool:
    value = (env or os.environ).get(name, "").strip().lower()
    return value in _TRUTHY


def should_hide_gpu(
    argv: Optional[Iterable[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return True when this process must not see CUDA devices."""
    env = env or os.environ
    if env_flag("PASTOR_AI_ALLOW_GPU", env):
        return False
    argv = list(argv or [])
    if any("run_video_ingestion_worker" in arg for arg in argv):
        return False
    return True


def apply_hide_gpu(argv: Optional[Iterable[str]] = None, env: Optional[Mapping[str, str]] = None) -> None:
    if should_hide_gpu(argv=argv, env=env):
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ.setdefault("EMBEDDING_DEVICE", "cpu")
