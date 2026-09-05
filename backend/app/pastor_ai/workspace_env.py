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

_SECRET_KEYS = {
    "DJANGO_SECRET_KEY",
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


def load_workspace_env(*, force: bool = False) -> None:
    """Fill os.environ from config.env then tokens.env.

    Secrets are always overwritten from the files so a zeroed gunicorn
    environ cannot keep serving `not-needed` / empty RunPod keys.
    """
    merged: dict[str, str] = {}
    for path in _candidate_files():
        if path.is_file():
            merged.update(_parse_env_file(path))
    for key, value in merged.items():
        if not value:
            continue
        current = (os.environ.get(key) or "").replace("\x00", "").strip()
        if force or not current or _placeholder(current) or key in _SECRET_KEYS:
            os.environ[key] = value
