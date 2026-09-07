"""Load config.env / tokens.env into os.environ.

RunPod CPU containers often zero /proc/pid/environ. Gunicorn then re-execs
workers with an empty environment, so RUNPOD_API_KEY never reaches Django and
chat 401s against Serverless. Reading the files from the network volume is the
reliable source of those keys.

The kernel can also zero the libc environ *after* import, so this loader
re-applies file values on every call instead of caching a one-shot `_LOADED`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

_SECRET_KEYS = {
    "DJANGO_SECRET_KEY",
    "DJANGO_ADMIN_URL",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "POSTGRES_PASSWORD",
    "RUNPOD_API_KEY",
    "VLLM_API_KEY",
    "WHISPER_API_KEY",
}


def _placeholder(value: str) -> bool:
    lowered = value.replace("\x00", "").strip().lower()
    if not lowered:
        return True
    return lowered in {"not-needed", "empty", "paste_here"} or "paste_here" in lowered


def _candidate_files() -> list[Path]:
    files: list[Path] = []
    env_hint = (os.environ.get("CONFIG_ENV") or "").strip()
    if env_hint:
        files.append(Path(env_hint))
    ws = Path(os.environ.get("WORKSPACE_ROOT") or "/workspace/pastor-ai")
    files.extend([ws / "config.env", ws / "tokens.env"])
    # backend/app/pastor_ai/workspace_env.py → repo root (pastor-ai/)
    try:
        repo_root = Path(__file__).resolve().parents[3]
        files.extend([repo_root / "config.env", repo_root / "tokens.env"])
    except IndexError:
        pass
    seen: set[Path] = set()
    out: list[Path] = []
    for path in files:
        resolved = path if path.is_absolute() else path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _parse_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return parsed
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip().strip("'").strip('"')
    return parsed


def workspace_env_values() -> dict[str, str]:
    """Parse config.env then tokens.env. Does not touch os.environ."""
    merged: dict[str, str] = {}
    for path in _candidate_files():
        if path.is_file():
            merged.update(_parse_env_file(path))
    return merged


def load_workspace_env(*, force: bool = False) -> None:
    """Fill os.environ from config.env then tokens.env.

    Secrets are always overwritten from the files so a zeroed gunicorn
    environ cannot keep serving `not-needed` / empty RunPod keys.
    """
    merged = workspace_env_values()
    for key, value in merged.items():
        if not value:
            continue
        current = (os.environ.get(key) or "").replace("\x00", "").strip()
        if force or not current or _placeholder(current) or key in _SECRET_KEYS:
            os.environ[key] = value


def env_with_workspace(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """os.environ overlay with file secrets winning.

    RunPod CPU images can zero libc environ after gunicorn starts, so callers
    that need RUNPOD_API_KEY must not trust os.environ alone.
    """
    files = workspace_env_values()
    merged: dict[str, str] = dict(files)
    source = os.environ if env is None else env
    for key, raw in source.items():
        value = str(raw).replace("\x00", "").strip()
        if not value or _placeholder(value):
            continue
        if key in _SECRET_KEYS and files.get(key) and not _placeholder(files[key]):
            continue
        merged[key] = value
    for key in _SECRET_KEYS:
        file_val = files.get(key, "")
        if file_val and not _placeholder(file_val):
            merged[key] = file_val
    return merged
